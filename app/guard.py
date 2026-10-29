"""
Read-only SQL guard, three independent layers (ported and extended from Bari):

  1. Static check   - a single SELECT/WITH statement; write/DDL keywords are
                      blocked outside string literals and comments.
  2. Read-only file - the database is opened with file:...?mode=ro.
  3. Engine limits  - a SQLite authorizer that allows reads only, a time budget
                      enforced by a progress handler, and a cap on returned rows.

Any one layer can be bypassed in theory; all three together cannot.
"""
import re
import sqlite3
import time

from .arabic import normalize

FORBIDDEN = [
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "attach", "detach", "pragma", "vacuum", "reindex", "analyze",
    "grant", "revoke", "commit", "rollback", "savepoint", "begin", "release",
    "load_extension", "writefile", "readfile", "edit", "fts3_tokenizer",
]
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)
# Strings and comments in ONE left-to-right pass: a quote inside a comment, or "--"
# inside a string, must not confuse the other.
_TOKEN_RE = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?(?:\*/|$)", re.DOTALL)
_DENIED_FUNCS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


class UnsafeQuery(ValueError):
    """Rejected by the static check (layer 1)."""


def _strip(sql: str) -> str:
    """Blank out string literals, then comments, so keywords inside values don't count."""
    return _TOKEN_RE.sub(lambda m: "''" if m.group(0).startswith("'") else " ", sql)


def check(sql: str) -> str:
    """Layer 1. Returns the cleaned statement or raises UnsafeQuery."""
    if not sql or not sql.strip():
        raise UnsafeQuery("Empty query")
    raw = sql.strip().rstrip(";").strip()
    bare = _strip(raw)
    if ";" in bare:
        raise UnsafeQuery("Only a single statement is allowed")
    low = bare.strip().lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise UnsafeQuery("Only SELECT / WITH queries are allowed (read-only)")
    m = _FORBIDDEN_RE.search(bare)
    if m:
        raise UnsafeQuery(f"Forbidden keyword in a read-only query: {m.group(1).upper()}")
    return raw


def _authorizer(action, arg1, arg2, dbname, source):
    """Layer 3a. Allow reads only; deny everything else at prepare time."""
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or "").lower() in _DENIED_FUNCS else sqlite3.SQLITE_OK
    if action == getattr(sqlite3, "SQLITE_RECURSIVE", -1):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connect(db_path) -> sqlite3.Connection:
    """Layer 2 + 3a: read-only file handle with a read-only authorizer."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only = ON")
    # norm(): Arabic-tolerant matching, e.g. WHERE norm(name_ar) LIKE '%' || norm('احمد') || '%'
    conn.create_function("norm", 1, normalize, deterministic=True)
    conn.set_authorizer(_authorizer)
    return conn


def run(conn, sql, max_rows=200, timeout=3.0) -> dict:
    """Validate and execute. Layer 3b: time budget; layer 3c: row cap."""
    safe = check(sql)
    deadline = time.monotonic() + timeout
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
    t0 = time.monotonic()
    try:
        cur = conn.execute(safe)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            raise TimeoutError(f"Query exceeded the {timeout:g}s time budget") from None
        raise
    finally:
        conn.set_progress_handler(None, 0)
    truncated = len(rows) > max_rows
    return {"columns": cols, "rows": [list(r) for r in rows[:max_rows]],
            "truncated": truncated, "ms": int((time.monotonic() - t0) * 1000),
            "sql": safe}
