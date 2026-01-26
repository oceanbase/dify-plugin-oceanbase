import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.entities.model.text_embedding import TextEmbeddingModelConfig
from dify_plugin.entities.model.rerank import RerankModelConfig
from pyobvector.client.hybrid_search import HybridSearch
from sqlalchemy import create_engine, inspect

from tools.common import OceanBaseConfig


class HybridSearchTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        table_names = tool_parameters.get("table_names", "").strip()
        query = tool_parameters.get("query", "").strip()
        top_k = tool_parameters.get("top_k", 10)
        embedding_model_config = tool_parameters.get("embedding_model")
        rerank_model_config = tool_parameters.get("rerank_model")
        filter_param = tool_parameters.get("filter", "").strip()
        config_options = tool_parameters.get("config_options") or "{}"

        # Validate required parameters
        if not table_names:
            raise ValueError("table_names parameter is required")
        if not query:
            raise ValueError("query parameter is required")
        if not embedding_model_config:
            raise ValueError("embedding_model parameter is required")

        try:
            config_options = json.loads(config_options)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format for Connect Config")

        # Parse filter parameter if provided
        filter_dict = None
        if filter_param:
            try:
                filter_dict = json.loads(filter_param)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON format for filter parameter")

        # Parse table names
        tables = [t.strip() for t in table_names.split(",")]
        
        # Validate rerank model for multiple tables
        if len(tables) > 1 and not rerank_model_config:
            raise ValueError("rerank_model is required when multiple table names are specified")

        # Get OceanBase config
        ob_config = OceanBaseConfig(self.runtime.credentials)
        assert ob_config.is_valid(), f"Invalid OceanBaseConfig: {ob_config}"
        db_uri = ob_config.get_uri()

        # Step 1: Get table structure to extract vector and full-text columns
        table_info = self._get_table_structure(db_uri, config_options, tables)

        # Step 2: Embed the query text using the embedding model
        embedded_query = self._embed_query(query, embedding_model_config)

        # Step 3: Perform hybrid search using pyobvector's HybridSearch
        search_results = self._perform_hybrid_search(
            ob_config, config_options, tables, query, embedded_query, top_k, table_info, filter_dict
        )

        # Step 4: If rerank model is set, re-rank the results
        if rerank_model_config and search_results:
            search_results = self._rerank_results(search_results, query, rerank_model_config, top_k)

        # Step 5: Return the search results
        return_format = tool_parameters.get("format", "json")
        yield from self._format_results(search_results, return_format)

    def _get_table_structure(
        self, db_uri: str, config_options: dict[str, Any], tables: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Get table structure to extract vector columns and full-text index columns."""
        engine = create_engine(db_uri, **config_options)
        inspector = inspect(engine)
        
        table_infos = {}
        with engine.connect() as _:
            for table_name in tables:
                try:
                    columns = inspector.get_columns(table_name)
                    indexes = inspector.get_indexes(table_name)
                    
                    # Extract vector columns (columns with VECTOR or similar types)
                    vector_columns = []
                    fulltext_columns = []
                    
                    for col in columns:
                        col_type = str(col["type"]).upper()
                        if "VECTOR" in col_type or "EMBEDDING" in col_type:
                            vector_columns.append(col["name"])
                    
                    # Extract full-text index columns
                    for idx in indexes:
                        # Check if it's a full-text index
                        # In MySQL/OceanBase, full-text indexes have a specific type
                        if isinstance(idx, dict) and idx.get("type") == "FULLTEXT":
                            fulltext_columns.extend(idx.get("column_names", []))
                    
                    table_infos[table_name] = {
                        "vector_columns": vector_columns,
                        "fulltext_columns": fulltext_columns,
                        "all_columns": [col["name"] for col in columns]
                    }
                except Exception as e:
                    raise ValueError(f"Error getting table info for {table_name}: {str(e)}")
        
        engine.dispose()
        return table_infos

    def _embed_query(self, query: str, embedding_model_config: dict) -> list[float]:
        """Embed the query text using the embedding model."""
        # Convert dict to TextEmbeddingModelConfig if needed
        if isinstance(embedding_model_config, dict):
            embedding_model_config = TextEmbeddingModelConfig(**embedding_model_config)
        
        response = self.session.model.text_embedding.invoke(
            model_config=embedding_model_config,
            texts=[query]
        )
        
        if not response or not response.embeddings:
            raise ValueError("Failed to generate embeddings for the query")
        
        return response.embeddings[0]

    def _perform_hybrid_search(
        self,
        ob_config: OceanBaseConfig,
        config_options: dict[str, Any],
        tables: list[str],
        query: str,
        embedded_query: list[float],
        top_k: int,
        table_info: dict[str, dict[str, Any]],
        filter_dict: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Perform hybrid search using pyobvector's HybridSearch class."""
        # Initialize HybridSearch client
        # The URI format expected by HybridSearch is hostname:port without protocol
        hybrid_client = HybridSearch(
            uri=f"{ob_config.hostname}:{ob_config.port}",
            user=ob_config.username,
            password=ob_config.password,
            db_name=ob_config.db_name,
            **config_options
        )

        all_results = []
        
        for table_name in tables:
            # Get vector and fulltext columns for this table
            table_columns = table_info.get(table_name, {})
            vector_columns = table_columns.get("vector_columns", [])
            fulltext_columns = table_columns.get("fulltext_columns", [])
            
            if not vector_columns and not fulltext_columns:
                raise ValueError(
                    f"Table '{table_name}' does not have a vector index or full-text index. "
                    f"Please ensure the table has at least one vector or full-text index."
                )
            
            # Build the search body for DBMS_HYBRID_SEARCH API
            # The format follows OceanBase DBMS_HYBRID_SEARCH specification
            # Build hybrid query combining vector and full-text search
            search_body = {
                "size": top_k
            }
            
            # Add vector search query if vector columns exist
            if vector_columns:
                # Use the first vector column (most tables will have one vector column)
                vec_col = vector_columns[0]
                search_body["knn"] = {
                    "field": vec_col,
                    "k": top_k,
                    "query_vector": embedded_query
                }
            
            # Add full-text search query if fulltext columns exist
            if fulltext_columns:
                # Use the first fulltext column
                ft_col = fulltext_columns[0]
                search_body["query"] = {
                    "bool": {
                        "should": [
                            {
                                "match": {
                                    ft_col: {
                                        "query": query
                                    }
                                }
                            }
                        ]
                    }
                }
            
            # Add filter if provided
            if filter_dict:
                if "query" in search_body:
                    if "bool" in search_body["query"]:
                        search_body["query"]["bool"]["filter"] = filter_dict
                    else:
                        search_body["query"]["bool"] = {"filter": filter_dict}
                else:
                    search_body["query"] = {
                        "bool": {
                            "filter": filter_dict
                        }
                    }
            
            try:
                # Execute hybrid search
                results = hybrid_client.search(index=table_name, body=search_body)
                
                # Add table name to each result and normalize the structure
                if isinstance(results, dict):
                    # Handle Elasticsearch-style response
                    if "hits" in results:
                        hits = results.get("hits", {}).get("hits", [])
                        for hit in hits:
                            hit["_table"] = table_name
                            all_results.append(hit)
                    else:
                        # If not in expected format, add the whole result
                        results["_table"] = table_name
                        all_results.append(results)
                elif isinstance(results, list):
                    for result in results:
                        if isinstance(result, dict):
                            result["_table"] = table_name
                        all_results.append(result)
            except Exception as e:
                raise ValueError(f"Error executing hybrid search on table '{table_name}': {str(e)}")
        
        # Sort results by score if available
        if all_results and isinstance(all_results[0], dict):
            if "_score" in all_results[0]:
                all_results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        
        # Limit to top_k results
        return all_results[:top_k]

    def _rerank_results(
        self,
        results: list[dict[str, Any]],
        query: str,
        rerank_model_config: dict,
        top_k: int
    ) -> list[dict[str, Any]]:
        """Re-rank the results using the rerank model."""
        if not results:
            return results
        
        # Extract documents from results for reranking
        docs = []
        for result in results:
            # Extract the source document or combine fields
            if "_source" in result:
                doc = result["_source"]
            else:
                doc = result
            
            # Convert to string representation for reranking
            doc_text = " ".join([str(v) for v in doc.values() if v is not None])
            docs.append(doc_text)
        
        # Use rerank model to reorder results
        try:
            # Convert dict to RerankModelConfig if needed
            if isinstance(rerank_model_config, dict):
                # Add default values for required fields if missing
                if "score_threshold" not in rerank_model_config:
                    rerank_model_config["score_threshold"] = 0.0
                if "top_n" not in rerank_model_config:
                    rerank_model_config["top_n"] = top_k
                rerank_model_config = RerankModelConfig(**rerank_model_config)
            
            rerank_response = self.session.model.rerank.invoke(
                model_config=rerank_model_config,
                query=query,
                docs=docs
            )
            
            if not rerank_response or not rerank_response.docs:
                return results
            
            # Create a mapping of reranked positions
            reranked_docs = rerank_response.docs
            
            # Sort by rerank score
            reranked_results = []
            for rerank_doc in reranked_docs:
                idx = rerank_doc.index
                result = results[idx].copy()
                result["_rerank_score"] = rerank_doc.score
                reranked_results.append(result)
            
            # Sort by rerank score and return top_k
            reranked_results.sort(key=lambda x: x.get("_rerank_score", 0), reverse=True)
            return reranked_results[:top_k]
        except Exception as e:
            # If reranking fails, log warning and return original results
            # Note: In production, consider using proper logging framework
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Reranking failed: {str(e)}")
            return results

    def _format_results(
        self, results: list[dict[str, Any]], return_format: str
    ) -> Generator[ToolInvokeMessage]:
        """Format and return the search results."""
        if return_format == "json":
            yield self.create_json_message({"results": results, "count": len(results)})
        elif return_format == "md":
            # Convert to markdown table format
            if not results:
                yield self.create_text_message("No results found.")
                return
            
            # Extract all unique keys from results
            all_keys = set()
            for result in results:
                all_keys.update(result.keys())
            
            # Build markdown table
            headers = sorted(list(all_keys))
            md_lines = ["| " + " | ".join(headers) + " |"]
            md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            
            for result in results:
                row = []
                for key in headers:
                    value = result.get(key, "")
                    # Convert to string and escape pipes
                    value_str = str(value).replace("|", "\\|")
                    row.append(value_str)
                md_lines.append("| " + " | ".join(row) + " |")
            
            yield self.create_text_message("\n".join(md_lines))
        else:
            raise ValueError(f"Unsupported format: {return_format}. Supported formats: json, md")
