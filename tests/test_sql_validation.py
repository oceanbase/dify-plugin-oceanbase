import pytest

from tools.execute_sql import _normalize_sql, _validate_readonly_sql


class TestNormalizeSql:
    def test_strip_single_quoted_string(self) -> None:
        assert "WHERE name =  " in _normalize_sql("WHERE name = 'INTO OUTFILE'")

    def test_strip_double_quoted_string(self) -> None:
        assert "SELECT   FROM t" == _normalize_sql('SELECT "col" FROM t').strip()

    def test_strip_escaped_quotes(self) -> None:
        result = _normalize_sql(r"SELECT 'it\'s' FROM t")
        assert result.strip() == "SELECT   FROM t"

    def test_strip_doubled_quotes(self) -> None:
        result = _normalize_sql("SELECT 'it''s' FROM t")
        assert "INTO" not in result or "OUTFILE" not in result

    def test_strip_block_comment(self) -> None:
        assert "DROP" not in _normalize_sql("SELECT /* DROP TABLE */ 1")

    def test_strip_line_comment_dash(self) -> None:
        assert "DROP" not in _normalize_sql("SELECT 1 -- DROP TABLE")

    def test_strip_line_comment_hash(self) -> None:
        assert "DROP" not in _normalize_sql("SELECT 1 # DROP TABLE")

    def test_keep_conditional_comment_body(self) -> None:
        result = _normalize_sql("SELECT /*!50000 SLEEP(5) */")
        assert "SLEEP" in result

    def test_strip_regular_block_comment_body(self) -> None:
        result = _normalize_sql("SELECT /* SLEEP(5) */ 1")
        assert "SLEEP" not in result

    def test_strip_backtick_identifier(self) -> None:
        result = _normalize_sql("SELECT `drop` FROM t")
        assert "drop" not in result.lower()

    def test_unterminated_single_quote(self) -> None:
        with pytest.raises(ValueError, match="Unterminated string literal"):
            _normalize_sql("SELECT * FROM t WHERE x = '")

    def test_unterminated_backtick(self) -> None:
        with pytest.raises(ValueError, match="Unterminated backtick"):
            _normalize_sql("SELECT `col FROM t")

    def test_unterminated_block_comment(self) -> None:
        with pytest.raises(ValueError, match="Unterminated block comment"):
            _normalize_sql("SELECT /* never closed")

    def test_double_backslash_in_string(self) -> None:
        result = _normalize_sql("SELECT * FROM t WHERE x = '\\\\' INTO OUTFILE '/tmp/x'")
        assert "INTO" in result and "OUTFILE" in result


class TestValidateReadonlySql:
    # --- happy path ---
    def test_simple_select(self) -> None:
        _validate_readonly_sql("SELECT * FROM users")

    def test_select_with_where(self) -> None:
        _validate_readonly_sql("SELECT id, name FROM users WHERE id = 1")

    def test_show_tables(self) -> None:
        _validate_readonly_sql("SHOW TABLES")

    def test_show_create_table(self) -> None:
        _validate_readonly_sql("SHOW CREATE TABLE users")

    def test_with_cte_select(self) -> None:
        _validate_readonly_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_select_with_leading_whitespace(self) -> None:
        _validate_readonly_sql("  SELECT 1")

    def test_case_insensitive(self) -> None:
        _validate_readonly_sql("select * from t")
        _validate_readonly_sql("Show Tables")

    def test_select_with_subquery(self) -> None:
        _validate_readonly_sql("SELECT * FROM t WHERE id IN (SELECT id FROM t2)")

    def test_trailing_semicolon(self) -> None:
        _validate_readonly_sql("SELECT 1;")

    def test_string_containing_dangerous_keyword(self) -> None:
        _validate_readonly_sql("SELECT * FROM t WHERE name = 'INTO OUTFILE'")

    def test_column_name_with_keyword_substring(self) -> None:
        _validate_readonly_sql("SELECT last_update_time FROM t")

    def test_backtick_quoted_keyword_column(self) -> None:
        _validate_readonly_sql("SELECT `drop`, `update`, `alter` FROM t")

    # --- rejection: non-read prefix ---
    def test_reject_drop(self) -> None:
        with pytest.raises(ValueError, match="SQL must start with"):
            _validate_readonly_sql("DROP TABLE users")

    def test_reject_insert(self) -> None:
        with pytest.raises(ValueError, match="SQL must start with"):
            _validate_readonly_sql("INSERT INTO t VALUES (1)")

    # --- rejection: multi-statement ---
    def test_reject_multi_statement(self) -> None:
        with pytest.raises(ValueError, match="Multiple SQL statements"):
            _validate_readonly_sql("SELECT 1; DROP TABLE users")

    # --- rejection: file I/O ---
    def test_reject_into_outfile(self) -> None:
        with pytest.raises(ValueError, match="INTO OUTFILE"):
            _validate_readonly_sql("SELECT * FROM t INTO OUTFILE '/tmp/x'")

    def test_reject_into_dumpfile(self) -> None:
        with pytest.raises(ValueError, match="INTO OUTFILE"):
            _validate_readonly_sql("SELECT * FROM t INTO DUMPFILE '/tmp/x'")

    def test_reject_load_file(self) -> None:
        with pytest.raises(ValueError, match="LOAD_FILE"):
            _validate_readonly_sql("SELECT LOAD_FILE('/etc/passwd')")

    # --- rejection: locking ---
    def test_reject_for_update(self) -> None:
        with pytest.raises(ValueError, match="FOR UPDATE"):
            _validate_readonly_sql("SELECT * FROM t FOR UPDATE")

    def test_reject_for_share(self) -> None:
        with pytest.raises(ValueError, match="FOR UPDATE/SHARE"):
            _validate_readonly_sql("SELECT * FROM t FOR SHARE")

    def test_reject_lock_in_share_mode(self) -> None:
        with pytest.raises(ValueError, match="LOCK IN SHARE MODE"):
            _validate_readonly_sql("SELECT * FROM t LOCK IN SHARE MODE")

    # --- rejection: side-effect functions ---
    def test_reject_sleep(self) -> None:
        with pytest.raises(ValueError, match="SLEEP"):
            _validate_readonly_sql("SELECT SLEEP(5)")

    def test_reject_benchmark(self) -> None:
        with pytest.raises(ValueError, match="BENCHMARK"):
            _validate_readonly_sql("SELECT BENCHMARK(1000000, MD5('test'))")

    def test_reject_get_lock(self) -> None:
        with pytest.raises(ValueError, match="GET_LOCK"):
            _validate_readonly_sql("SELECT GET_LOCK('mylock', 10)")

    def test_reject_release_lock(self) -> None:
        with pytest.raises(ValueError, match="RELEASE_LOCK"):
            _validate_readonly_sql("SELECT RELEASE_LOCK('mylock')")

    # --- rejection: DML/DDL via WITH CTE ---
    def test_reject_cte_insert(self) -> None:
        with pytest.raises(ValueError, match="INSERT INTO"):
            _validate_readonly_sql("WITH cte AS (SELECT 1) INSERT INTO t SELECT * FROM cte")

    def test_reject_cte_delete(self) -> None:
        with pytest.raises(ValueError, match="DELETE FROM"):
            _validate_readonly_sql("WITH cte AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT * FROM cte)")

    def test_reject_cte_update(self) -> None:
        with pytest.raises(ValueError, match="UPDATE"):
            _validate_readonly_sql("WITH cte AS (SELECT 1) UPDATE t SET x = 1")

    # --- rejection: comment obfuscation ---
    def test_reject_outfile_hidden_in_block_comment(self) -> None:
        with pytest.raises(ValueError):
            _validate_readonly_sql("SELECT * FROM t INTO /*comment*/ OUTFILE '/tmp/x'")

    def test_reject_keyword_split_by_line_comment(self) -> None:
        with pytest.raises(ValueError):
            _validate_readonly_sql("SELECT * FROM t FOR -- bypass\nUPDATE")

    # --- rejection: conditional comment bypass ---
    def test_reject_sleep_in_conditional_comment(self) -> None:
        with pytest.raises(ValueError, match="SLEEP"):
            _validate_readonly_sql("SELECT /*!50000 SLEEP(5) */")

    def test_reject_outfile_in_conditional_comment(self) -> None:
        with pytest.raises(ValueError, match="INTO OUTFILE"):
            _validate_readonly_sql("SELECT /*!32302 INTO OUTFILE '/tmp/x' */ 1")

    # --- rejection: unterminated literals ---
    def test_reject_unterminated_string(self) -> None:
        with pytest.raises(ValueError, match="Unterminated"):
            _validate_readonly_sql("SELECT * FROM t WHERE x = ' INTO OUTFILE")

    # --- rejection: DDL keywords ---
    def test_reject_drop_keyword(self) -> None:
        with pytest.raises(ValueError, match="DROP"):
            _validate_readonly_sql("SELECT DROP FROM t")

    def test_reject_create(self) -> None:
        with pytest.raises(ValueError, match="CREATE"):
            _validate_readonly_sql("WITH cte AS (SELECT 1) CREATE TABLE x AS SELECT * FROM cte")

    def test_reject_create_standalone(self) -> None:
        with pytest.raises(ValueError, match="SQL must start with"):
            _validate_readonly_sql("CREATE TABLE x (id INT)")

    def test_reject_call(self) -> None:
        with pytest.raises(ValueError, match="CALL"):
            _validate_readonly_sql("WITH cte AS (SELECT 1) CALL my_proc()")

    def test_reject_execute(self) -> None:
        with pytest.raises(ValueError, match="EXECUTE"):
            _validate_readonly_sql("WITH cte AS (SELECT 1) EXECUTE my_stmt")

