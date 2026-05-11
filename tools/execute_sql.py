import json
import re
from collections.abc import Generator
from typing import Any

import records
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools.common import OceanBaseConfig

_READONLY_PREFIX = re.compile(r'^\s*(SELECT|SHOW|WITH)\s+', re.IGNORECASE)
_SHOW_PREFIX = re.compile(r'^\s*SHOW\b', re.IGNORECASE)

# Patterns that are always checked (even for SHOW statements)
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # File I/O
    (re.compile(r'\bINTO\s+(OUTFILE|DUMPFILE)\b', re.IGNORECASE), 'INTO OUTFILE/DUMPFILE'),
    (re.compile(r'\bLOAD_FILE\s*\(', re.IGNORECASE), 'LOAD_FILE()'),
    # Locking clauses
    (re.compile(r'\bFOR\s+(UPDATE|SHARE)\b', re.IGNORECASE), 'FOR UPDATE/SHARE'),
    (re.compile(r'\bLOCK\s+IN\s+SHARE\s+MODE\b', re.IGNORECASE), 'LOCK IN SHARE MODE'),
    # Side-effect functions (DoS / locking)
    (re.compile(r'\bSLEEP\s*\(', re.IGNORECASE), 'SLEEP()'),
    (re.compile(r'\bBENCHMARK\s*\(', re.IGNORECASE), 'BENCHMARK()'),
    (re.compile(r'\bGET_LOCK\s*\(', re.IGNORECASE), 'GET_LOCK()'),
    (re.compile(r'\bRELEASE_LOCK\s*\(', re.IGNORECASE), 'RELEASE_LOCK()'),
    # DML/DDL (also covers WITH-CTE + DML bypass)
    (re.compile(r'\bINSERT\s+INTO\b', re.IGNORECASE), 'INSERT INTO'),
    (re.compile(r'\bDELETE\s+FROM\b', re.IGNORECASE), 'DELETE FROM'),
    (re.compile(r'\bREPLACE\s+INTO\b', re.IGNORECASE), 'REPLACE INTO'),
    (re.compile(r'\bUPDATE\b', re.IGNORECASE), 'UPDATE'),
    (re.compile(r'\bDROP\b', re.IGNORECASE), 'DROP'),
    (re.compile(r'\bALTER\b', re.IGNORECASE), 'ALTER'),
    (re.compile(r'\bTRUNCATE\b', re.IGNORECASE), 'TRUNCATE'),
    (re.compile(r'\bGRANT\b', re.IGNORECASE), 'GRANT'),
    (re.compile(r'\bREVOKE\b', re.IGNORECASE), 'REVOKE'),
    (re.compile(r'\bRENAME\b', re.IGNORECASE), 'RENAME'),
    (re.compile(r'\bCREATE\b', re.IGNORECASE), 'CREATE'),
    (re.compile(r'\bCALL\b', re.IGNORECASE), 'CALL'),
    (re.compile(r'\bEXECUTE\b', re.IGNORECASE), 'EXECUTE'),
]


def _normalize_sql(sql: str) -> str:
    """Strip string literals and SQL comments to expose raw SQL structure.

    MySQL conditional comments ``/*!NNNNN ... */`` are kept (content only)
    because the server executes them when its version >= NNNNN.
    """
    result: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            quote = c
            start = i
            i += 1
            while i < n:
                if sql[i] == '\\':
                    i += 2
                elif sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            else:
                raise ValueError(
                    f"Unterminated string literal starting at position {start}"
                )
            result.append(' ')
        elif c == '`':
            start = i
            i += 1
            while i < n and sql[i] != '`':
                i += 1
            if i >= n:
                raise ValueError(
                    f"Unterminated backtick identifier starting at position {start}"
                )
            i += 1
            result.append(' ')
        elif c == '/' and i + 1 < n and sql[i + 1] == '*':
            # MySQL conditional comment /*!NNNNN ... */ — keep inner content
            is_conditional = i + 2 < n and sql[i + 2] == '!'
            i += 2
            if is_conditional:
                i += 1
                # Skip optional version digits after '!'
                while i < n and sql[i].isdigit():
                    i += 1
                body_start = i
            while i + 1 < n and not (sql[i] == '*' and sql[i + 1] == '/'):
                i += 1
            if i + 1 >= n:
                raise ValueError("Unterminated block comment")
            if is_conditional:
                result.append(sql[body_start:i])
            i += 2
            result.append(' ')
        elif c == '-' and i + 1 < n and sql[i + 1] == '-':
            i += 2
            while i < n and sql[i] != '\n':
                i += 1
            result.append(' ')
        elif c == '#':
            i += 1
            while i < n and sql[i] != '\n':
                i += 1
            result.append(' ')
        else:
            result.append(c)
            i += 1
    return ''.join(result)


def _validate_readonly_sql(sql: str) -> None:
    """Validate that *sql* is a single, side-effect-free read statement."""
    normalized = _normalize_sql(sql)

    statements = [s.strip() for s in normalized.split(';') if s.strip()]
    if len(statements) > 1:
        raise ValueError("Multiple SQL statements are not allowed")

    if not _READONLY_PREFIX.match(normalized):
        raise ValueError("SQL must start with SELECT, SHOW, or WITH")

    # SHOW CREATE TABLE/VIEW/PROCEDURE/... is a legitimate read-only DDL-inspection command.
    # Skip patterns that would falsely match its keywords.
    is_show = bool(_SHOW_PREFIX.match(normalized))
    _show_safe = {'CREATE', 'CALL', 'EXECUTE'}

    for pattern, name in _DANGEROUS_PATTERNS:
        if is_show and name in _show_safe:
            continue
        if pattern.search(normalized):
            raise ValueError(f"SQL contains disallowed construct: {name}")


class ExecuteSqlTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        sql = tool_parameters.get("sql")
        if not sql:
            raise ValueError("'sql' parameter is required")
        sql = sql.strip()
        return_format = tool_parameters.get("format", "json")
        config_options = tool_parameters.get("config_options") or "{}"

        try:
            config_options = json.loads(config_options)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format for Connect Config")

        _validate_readonly_sql(sql)

        ob_config = OceanBaseConfig(self.runtime.credentials)
        assert ob_config.is_valid(), f"Invalid OceanBaseConfig: {ob_config}"
        db_uri = ob_config.get_uri()
        db = records.Database(db_uri, **config_options)

        try:
            rows = db.query(sql)
            if return_format == "json":
                result = rows.as_dict()
                yield self.create_json_message({"result": result})
            elif return_format == "md":
                result = str(rows.dataset)
                yield self.create_text_message(result)
            elif return_format == "csv":
                result = rows.export("csv").encode()
                yield self.create_blob_message(
                    result, meta={"mime_type": "text/csv", "filename": "result.csv"}
                )
            elif return_format == "yaml":
                result = rows.export("yaml").encode()
                yield self.create_blob_message(
                    result,
                    meta={"mime_type": "text/yaml", "filename": "result.yaml"},
                )
            elif return_format == "xlsx":
                result = rows.export("xlsx")
                yield self.create_blob_message(
                    result,
                    meta={
                        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "filename": "result.xlsx",
                    },
                )
            elif return_format == "html":
                result = rows.export("html").encode()
                yield self.create_blob_message(
                    result,
                    meta={"mime_type": "text/html", "filename": "result.html"},
                )
            else:
                raise ValueError(f"Unsupported format: {return_format}")
        finally:
            db.close()
