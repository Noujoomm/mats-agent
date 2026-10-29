import sqlite3

import pytest

from app import guard


@pytest.fixture
def conn(db_path):
    c = guard.connect(db_path)
    yield c
    c.close()


@pytest.mark.parametrize("sql", [
    "INSERT INTO pilgrims (id) VALUES (99999)",
    "UPDATE pilgrims SET status = 'active'",
    "DELETE FROM incidents",
    "DROP TABLE pilgrims",
    "ALTER TABLE pilgrims ADD COLUMN x",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "PRAGMA writable_schema = ON",
    "CREATE TABLE x (a)",
    "VACUUM",
])
def test_static_check_rejects_writes(sql):
    with pytest.raises(guard.UnsafeQuery):
        guard.check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE pilgrims",
    "SELECT * FROM pilgrims; DELETE FROM pilgrims",
    "SELECT name_en FROM pilgrims WHERE id = 1; UPDATE pilgrims SET status='x'",
    "SELECT 1 /* hide */; INSERT INTO groups VALUES (1)",
    "WITH x AS (SELECT 1) SELECT * FROM x; DROP TABLE x",
])
def test_static_check_rejects_multi_statement_injection(sql):
    with pytest.raises(guard.UnsafeQuery):
        guard.check(sql)


def test_keywords_inside_strings_are_allowed(conn):
    res = guard.run(conn, "SELECT COUNT(*) FROM incidents WHERE description_en LIKE '%delete; drop%'")
    assert res["rows"] == [[0]]


def test_semicolon_inside_string_is_not_multi_statement():
    assert guard.check("SELECT 'a;b' AS x;") == "SELECT 'a;b' AS x"


def test_authorizer_blocks_writes_even_if_static_check_is_bypassed(conn):
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM pilgrims")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("PRAGMA query_only = OFF")
    assert conn.execute("SELECT COUNT(*) FROM pilgrims").fetchone()[0] == 2000


def test_readonly_file_mode(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a)")
    conn.close()


def test_time_budget(conn):
    slow = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
            "SELECT COUNT(*) FROM c")
    with pytest.raises(TimeoutError):
        guard.run(conn, slow, timeout=0.3)


def test_row_cap(conn):
    res = guard.run(conn, "SELECT id FROM pilgrims", max_rows=50)
    assert len(res["rows"]) == 50 and res["truncated"]


def test_norm_function_matches_arabic_variants(conn):
    res = guard.run(conn, "SELECT COUNT(*) FROM pilgrims WHERE norm(name_ar) LIKE '%' || norm('احمد') || '%'")
    assert res["rows"][0][0] > 0


def test_quote_inside_comment_does_not_break_the_check(conn):
    sql = ("SELECT COUNT(*) -- the group's total\nFROM pilgrims WHERE status = 'missing'")
    assert guard.run(conn, sql)["rows"] == [[7]]


def test_comment_marker_inside_string_cannot_hide_injection():
    with pytest.raises(guard.UnsafeQuery):
        guard.check("SELECT '--' AS x; DROP TABLE pilgrims")
