## OceanBase

**Author:** oceanbase  
**Version:** 0.0.2
**Type:** tool  
**Repo:** https://github.com/oceanbase/dify-plugin-oceanbase

### Description

This plugin is used to query OceanBase databases and includes multiple tools to help users interact with OceanBase databases.

### Tools Introduction

#### 1. Execute SQL

- **Function**: Execute SQL queries on existing OceanBase databases
- **Usage**: Directly execute SQL statements starting with SELECT, SHOW, or WITH
- **Output Format**: Supports multiple formats including JSON, CSV, YAML, Markdown, Excel, HTML, etc.
- **Security Restrictions**: Only supports query statements to ensure database security

#### 2. Get Table Schema

- **Function**: Get table structure information from the database
- **Usage**: Provide database context for LLM to help understand table structure
- **Flexibility**: Can specify specific tables or get structure information for all tables
- **Use Cases**: Understand database structure before generating SQL queries

#### 3. Text to SQL

- **Function**: Use LLM to convert natural language queries into SQL statements
- **Usage**: Allow users to describe query requirements in natural language and automatically generate corresponding SQL
- **Intelligence**: Generate accurate SQL based on database context and table structure information
- **Model Selection**: Support selecting different large language models for conversion

#### 4. Hybrid Search

- **Function**: Execute hybrid search combining vector similarity and full-text search on OceanBase or SeekDB tables
- **Requirements**: Supported on OceanBase 4.4.1+ and SeekDB. Tables must have vector indexes or full-text indexes.
- **Features**:
  - Combines vector similarity search with full-text search for more accurate results
  - Supports searching across multiple tables
  - Uses embedding models to convert query text to vectors
  - Optional reranking with rerank models for improved result quality
  - Required rerank model when searching multiple tables
- **Use Cases**: Semantic search, document retrieval, question answering systems

### Usage Instructions

1. **Database Connection**: Configure OceanBase database connection information
2. **Select Tools**: Choose appropriate tools based on requirements
3. **Execute Queries**: Query data through natural language or direct SQL
4. **Get Results**: Obtain query results in specified format

### Notes

- This plugin only supports query operations and does not support data modification
- It is recommended to use read-only database accounts to ensure security
- Supports multiple output formats that can be selected as needed
- Hybrid Search requires OceanBase 4.4.1+ or SeekDB, and tables must have appropriate indexes

### References

This plugin references [dify-plugin-database](https://github.com/hjlarry/dify-plugin-database) and has been adapted and optimized for OceanBase databases.
