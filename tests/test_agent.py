import json

from conftest import collect

from app.agent import extract_sql

GOOD = "SELECT COUNT(*) AS missing FROM pilgrims WHERE status = 'missing'"
BAD = "SELECT COUNT(*) FROM no_such_table"


def route(intent, standalone):
    return json.dumps({"intent": intent, "standalone": standalone}, ensure_ascii=False)


def steps(events):
    return [(e["step"], e["model"], e["status"]) for e in events if e["type"] == "trace"]


def test_data_question_uses_super_and_fast(make_agent, settings):
    agent, llm = make_agent({
        "route": [route("data", "كم حاج ضايع الحين؟")],
        "sql": [GOOD],
        "answer": ["فيه 7 حجاج ضايعين الحين."],
    })
    ev = collect(agent, "كم حاج ضايع الحين؟")
    assert llm.models_for("route") == [settings.model_fast]
    assert llm.models_for("sql") == [settings.model_sql]
    assert llm.models_for("answer") == [settings.model_fast]
    table = next(e for e in ev if e["type"] == "table")
    assert table["rows"] == [[7]]
    done = ev[-1]
    assert done["type"] == "done" and "7" in done["answer"] and done["sql"] == GOOD
    assert [s[0] for s in steps(ev)] == ["route", "memory", "sql", "guard", "answer"]


def test_repair_then_escalate_to_ultra(make_agent, settings):
    agent, llm = make_agent({
        "route": [route("data", "How many pilgrims are missing?")],
        "sql": [BAD, "DELETE FROM pilgrims", GOOD],
        "answer": ["7 pilgrims are missing."],
    })
    ev = collect(agent, "How many pilgrims are missing?", lang="en")
    assert llm.models_for("sql") == [settings.model_sql, settings.model_sql, settings.model_complex]
    guards = [s for s in steps(ev) if s[0] == "guard"]
    assert [g[2] for g in guards] == ["error", "error", "ok"]
    assert next(e for e in ev if e["type"] == "table")["rows"] == [[7]]
    assert ev[-1]["lang"] == "en"


def test_repair_succeeds_without_escalation(make_agent, settings):
    agent, llm = make_agent({
        "route": [route("data", "How many pilgrims are missing?")],
        "sql": [BAD, GOOD],
        "answer": ["7."],
    })
    collect(agent, "How many pilgrims are missing?", lang="en")
    assert llm.models_for("sql") == [settings.model_sql, settings.model_sql]


def test_all_attempts_fail_gives_safe_message(make_agent):
    agent, llm = make_agent({"route": [route("data", "x")], "sql": [BAD, BAD, BAD]})
    ev = collect(agent, "How many?", lang="en")
    assert "couldn't" in ev[-1]["answer"]
    assert llm.models_for("answer") == []


def test_complex_question_routes_straight_to_ultra(make_agent, settings):
    agent, llm = make_agent({
        "route": [route("complex", "Which group has the worst boarding rate to Arafat?")],
        "sql": ["SELECT group_id, COUNT(*) AS n FROM pilgrims GROUP BY group_id ORDER BY n LIMIT 3"],
        "answer": ["Group 1 is behind. I recommend calling its supervisor."],
    })
    collect(agent, "Which group has the worst boarding rate to Arafat?", lang="en")
    assert settings.model_sql not in llm.models_for("sql")
    assert llm.models_for("sql") == [settings.model_complex]
    assert llm.models_for("answer") == [settings.model_complex]


def test_follow_up_is_rewritten_and_uses_history(make_agent):
    agent, llm = make_agent({
        "route": [route("data", "وش وضع باصات فوج 5 لعرفات؟")],
        "sql": ["SELECT status FROM trips t JOIN groups g ON g.id = t.group_id "
                "JOIN routes r ON r.id = t.route_id WHERE g.group_no = 5 AND r.code = 'MNA-ARF'"],
        "answer": ["باصات فوج 5 وصلت عرفات."],
    })
    history = [{"role": "user", "content": "وش وضع باصات فوج 3 لعرفات؟"},
               {"role": "assistant", "content": "باصات فوج 3 وصلت."}]
    ev = collect(agent, "وفوج ٥؟", history)
    intent = next(e for e in ev if e["type"] == "intent")
    assert intent["standalone"] == "وش وضع باصات فوج 5 لعرفات؟"
    assert next(e for e in ev if e["type"] == "table")["rows"] == [["arrived"], ["arrived"]]


def test_smalltalk_skips_sql(make_agent):
    agent, llm = make_agent({"route": [route("smalltalk", "هلا")], "answer": ["هلا والله!"]})
    ev = collect(agent, "هلا")
    assert llm.models_for("sql") == [] and ev[-1]["answer"] == "هلا والله!"


def test_router_garbage_falls_back_to_heuristic(make_agent):
    agent, llm = make_agent({"route": ["not json"], "sql": [GOOD], "answer": ["7"]})
    ev = collect(agent, "كم حاج ضايع؟")
    assert next(e for e in ev if e["type"] == "intent")["intent"] == "data"


class FakeWeb:
    enabled = True

    def __init__(self):
        self.queries = []

    def search(self, q):
        self.queries.append(q)
        return {"answer": "Hot and sunny, 44C.",
                "results": [{"title": "Weather Arafat", "url": "https://example.org/w",
                             "content": "44C"}]}


def test_hybrid_merges_database_and_tavily(make_agent):
    web = FakeWeb()
    agent, llm = make_agent({
        "route": [route("hybrid", "Given the weather in Arafat, which groups are still in Mina?")],
        "sql": ["SELECT DISTINCT g.group_no FROM trips t JOIN groups g ON g.id = t.group_id "
                "WHERE t.route_id = 2 AND t.status = 'scheduled'"],
        "answer": ["It is 44C in Arafat; groups 17 to 20 are still in Mina."],
    }, web=web)
    ev = collect(agent, "Given the weather in Arafat, which groups are still in Mina?", lang="en")
    assert web.queries and any(e["type"] == "sources" for e in ev)
    assert any(e["type"] == "table" for e in ev)
    assert ("web", "Tavily", "ok") in steps(ev)


def test_successful_query_is_remembered(make_agent, memory):
    before = memory.stats()["examples"]
    agent, _ = make_agent({"route": [route("data", "Count missing pilgrims")],
                           "sql": [GOOD], "answer": ["7"]})
    collect(agent, "Count missing pilgrims", lang="en")
    assert memory.stats()["examples"] == before + 1


def test_extract_sql_strips_fences_and_prose():
    assert extract_sql("Here you go:\n```sql\nSELECT 1;\n```") == "SELECT 1"
