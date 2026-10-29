"""Context, memory, learning from mistakes and asking when unsure."""
import json

from conftest import collect

GOOD = "SELECT COUNT(*) AS missing FROM pilgrims WHERE status = 'missing'"
BAD = "SELECT COUNT(*) FROM no_such_table"


def route(**kw):
    return json.dumps(kw, ensure_ascii=False)


def text_of(messages):
    return "\n".join(m["content"] for m in messages)


def test_unsure_question_asks_instead_of_guessing(make_agent):
    options = ["وش وضع باصات فوج 5 من منى لعرفات؟", "وش وضع باصات فوج 5 من عرفات لمزدلفة؟"]
    agent, llm = make_agent({"route": [route(intent="clarify", standalone="وش وضع باصات فوج 5؟",
                                             ask="تقصد رحلة فوج 5 من وين لوين؟", options=options)]})
    ev = collect(agent, "وش وضع باصات فوج 5؟")
    clar = next(e for e in ev if e["type"] == "clarify")
    assert clar["options"] == options
    assert ev[-1]["answer"] == "تقصد رحلة فوج 5 من وين لوين؟" and ev[-1]["intent"] == "clarify"
    assert llm.models_for("sql") == [] and llm.models_for("answer") == []


def test_clarify_without_options_falls_back_to_answering(make_agent):
    agent, llm = make_agent({"route": [route(intent="clarify", standalone="How many missing?")],
                             "sql": [GOOD], "answer": ["7."]})
    ev = collect(agent, "How many missing?", lang="en")
    assert ev[-1]["intent"] == "data" and llm.models_for("sql")


def test_remembers_user_facts_and_uses_them_later(make_agent, memory):
    agent, llm = make_agent({
        "route": [route(intent="smalltalk", standalone="أنا مشرف فوج 7",
                        remember="The user supervises group 7."),
                  route(intent="data", standalone="وش وضع باصات فوج 7 لعرفات؟")],
        "answer": ["أبشر، بتذكر إنك مشرف فوج 7.", "باصات فوجك وصلت."],
        "sql": ["SELECT status FROM trips WHERE group_id = 7 AND route_id = 2"],
    })
    ev = collect(agent, "أنا مشرف فوج 7", client_id="browser-1")
    assert any(e["type"] == "remembered" for e in ev)
    assert memory.facts("browser-1") == ["The user supervises group 7."]
    assert memory.facts("someone-else") == []

    collect(agent, "وش وضع فوجي لعرفات؟", client_id="browser-1")
    second_route = [m for r, m in llm.prompts if r == "route"][1]
    assert "The user supervises group 7." in text_of(second_route)
    answer_prompt = [m for r, m in llm.prompts if r == "answer"][-1]
    assert "supervises group 7" in text_of(answer_prompt)


def test_context_of_previous_answer_reaches_the_router(make_agent):
    agent, llm = make_agent({"route": [route(intent="data", standalone="phone of P-00026")],
                             "sql": [GOOD], "answer": ["ok"]})
    history = [{"role": "user", "content": "مين ما ركب؟"},
               {"role": "assistant", "content": "7 حجاج.", "context": "7 rows: pilgrim_no; P-00026"}]
    collect(agent, "وش رقم أول واحد؟", history)
    assert "[data: 7 rows: pilgrim_no; P-00026]" in text_of(llm.prompts[0][1])


def test_done_event_carries_data_context(make_agent):
    agent, _ = make_agent({"route": [route(intent="data", standalone="missing?")],
                           "sql": [GOOD], "answer": ["7"]})
    done = collect(agent, "missing?", lang="en")[-1]
    assert done["context"].startswith("1 rows: missing; 7")


def test_learns_from_a_repaired_mistake(make_agent, memory):
    agent, llm = make_agent({
        "route": [route(intent="data", standalone="How many pilgrims are missing?"),
                  route(intent="data", standalone="How many pilgrims are missing now?")],
        "sql": [BAD, GOOD, GOOD], "answer": ["7", "7"],
    })
    ev = collect(agent, "How many pilgrims are missing?", lang="en")
    assert any(e["type"] == "trace" and e["step"] == "learn" for e in ev)
    lesson = memory.lessons("How many pilgrims are missing now?")[0]
    assert lesson["bad_sql"] == BAD and lesson["fixed_sql"] == GOOD

    collect(agent, "How many pilgrims are missing now?", lang="en")
    last_sql_prompt = [m for r, m in llm.prompts if r == "sql"][-1]
    assert "Lessons from past mistakes" in text_of(last_sql_prompt) and BAD in text_of(last_sql_prompt)


def test_reasoning_router_only_when_needed(make_agent, settings):
    agent, llm = make_agent({"route": [route(intent="data", standalone="How many pilgrims are missing?"),
                                       route(intent="data", standalone="مين مشرف فوج 1؟")],
                             "sql": [GOOD, GOOD], "answer": ["7", "x"]})
    collect(agent, "How many pilgrims are missing?", lang="en")
    history = [{"role": "user", "content": "مين ما ركب؟"}, {"role": "assistant", "content": "7"}]
    collect(agent, "ومين مشرف فوجه؟", history)
    assert llm.models_for("route") == [settings.model_fast, settings.model_router_reasoning]


def test_fast_router_clarification_is_double_checked(make_agent, settings):
    agent, llm = make_agent({
        "route": [route(intent="clarify", standalone="Which buses are delayed?", ask="Which route?",
                        options=["a", "b"]),
                  route(intent="data", standalone="Which buses are delayed?")],
        "sql": [GOOD], "answer": ["6 buses."]})
    ev = collect(agent, "Which buses are delayed?", lang="en")
    assert llm.models_for("route") == [settings.model_fast, settings.model_router_reasoning]
    assert ev[-1]["intent"] == "data"


def test_reasoning_router_outage_falls_back_to_fast(make_agent, settings):
    agent, llm = make_agent({
        "route": [TimeoutError("stalled"), route(intent="data", standalone="مين مشرف فوج 1؟")],
        "sql": [GOOD], "answer": ["x"]})
    history = [{"role": "user", "content": "مين ما ركب؟"}, {"role": "assistant", "content": "7"}]
    ev = collect(agent, "ومين مشرف فوجه؟", history)
    assert llm.models_for("route") == [settings.model_router_reasoning, settings.model_fast]
    route_trace = next(e for e in ev if e["type"] == "trace" and e["step"] == "route")
    assert "unavailable" in route_trace["detail"] and ev[-1]["intent"] == "data"


def test_my_group_without_memory_asks_and_never_guesses(make_agent):
    agent, llm = make_agent({})
    ev = collect(agent, "وش وضع فوجي لعرفات؟", client_id="new-user")
    assert ev[-1]["intent"] == "clarify" and "فوجك" in ev[-1]["answer"]
    assert llm.calls == []          # no model was asked to guess


def test_out_of_scope_is_declined_without_any_model_work(make_agent):
    agent, llm = make_agent({"route": [route(intent="out_of_scope", standalone="Write me Python code")]})
    ev = collect(agent, "Write me Python code", lang="en")
    assert ev[-1]["intent"] == "out_of_scope" and "pilgrim guidance" in ev[-1]["answer"]
    assert llm.models_for("sql") == [] and llm.models_for("answer") == []


def test_religious_rulings_are_referred_to_the_guide(make_agent):
    agent, _ = make_agent({"route": [route(intent="out_of_scope", standalone="وش حكم الحلق قبل الرمي؟")]})
    ev = collect(agent, "وش حكم الحلق قبل الرمي؟")
    assert "مرشد الحملة الشرعي" in ev[-1]["answer"]


def test_web_search_is_limited_to_the_holy_sites(make_agent):
    class Web:
        enabled = True
        queries = []

        def search(self, q):
            self.queries.append(q)
            return {"answer": "", "results": []}
    web = Web()
    agent, _ = make_agent({"route": [route(intent="web", standalone="What's the weather in Riyadh?",
                                           meaning="What's the weather in Riyadh?")]}, web=web)
    ev = collect(agent, "What's the weather in Riyadh?", lang="en")
    assert ev[-1]["intent"] == "out_of_scope" and web.queries == []


def test_introduces_itself_as_mats_agent(make_agent):
    agent, llm = make_agent({})
    ev = collect(agent, "من أنت؟")
    assert "مساعد ماتس" in ev[-1]["answer"] and llm.calls == []


def test_web_question_about_our_groups_becomes_hybrid(make_agent):
    agent, llm = make_agent({"route": [route(intent="web", standalone="Weather in Arafat and which groups are in Mina?",
                                             meaning="Weather in Arafat and which groups are still in Mina?")],
                             "sql": ["SELECT group_no FROM groups LIMIT 2"], "answer": ["ok"]})
    ev = collect(agent, "Weather in Arafat and which groups are in Mina?", lang="en")
    assert ev[-1]["intent"] == "hybrid" and llm.models_for("sql")
