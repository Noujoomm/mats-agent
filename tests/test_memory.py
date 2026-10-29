import pytest

from app import guard
from app.memory import SEEDS


def test_seeds_are_bilingual():
    assert len(SEEDS) == 9
    for questions, _ in SEEDS:
        assert any("؀" <= ch <= "ۿ" for ch in questions[0])
        assert questions[1].isascii()


@pytest.mark.parametrize("sql", [s for _, s in SEEDS])
def test_every_seed_executes_and_returns_rows(db_path, sql):
    conn = guard.connect(db_path)
    try:
        res = guard.run(conn, sql)
    finally:
        conn.close()
    assert res["rows"], sql


def test_not_boarded_seed_finds_the_seven_missing(db_path):
    conn = guard.connect(db_path)
    res = guard.run(conn, SEEDS[0][1])
    conn.close()
    assert len(res["rows"]) == 7


def test_dialect_and_misspelling_retrieval(memory):
    hits = memory.similar("كم حاج ضايع الحين")          # no question mark
    assert "missing" in hits[0]["sql"]
    hits = memory.similar("وش وضع باصات الفوج ٧ لعرفات")   # different group, Arabic digit
    assert "MNA-ARF" in hits[0]["sql"]
    hits = memory.similar("which buses are delayed?")
    assert "delayed" in hits[0]["sql"]


def test_right_verifies_and_wrong_forgets(memory):
    sql = "SELECT COUNT(*) FROM buses"
    memory.mark_right("How many buses?", sql)
    assert memory.similar("How many buses?")[0]["verified"]
    assert memory.forget("How many buses?", sql) >= 1
    assert all(e["sql"] != sql for e in memory.similar("How many buses?"))


def test_right_rejects_unsafe_sql(memory):
    with pytest.raises(guard.UnsafeQuery):
        memory.mark_right("drop it", "DROP TABLE pilgrims")


def test_still_in_mina_seed_matches_simulated_state(db_path):
    conn = guard.connect(db_path)
    rows = guard.run(conn, SEEDS[7][1])["rows"]
    conn.close()
    assert [r[0] for r in rows] == list(range(10, 21))
