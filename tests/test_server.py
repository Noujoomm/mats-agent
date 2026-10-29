import json

import pytest
from fastapi.testclient import TestClient

from conftest import FakeLLM


@pytest.fixture
def client(settings, memory, monkeypatch):
    from app import server
    from app.agent import Agent
    monkeypatch.setattr(server, "settings", settings)
    llm = FakeLLM({
        "route": [json.dumps({"intent": "data", "standalone": "How many pilgrims are missing?"})],
        "sql": ["SELECT COUNT(*) AS missing FROM pilgrims WHERE status = 'missing'"],
        "answer": ["Seven pilgrims are missing."],
    })
    monkeypatch.setattr(server, "get_memory", lambda: memory)
    monkeypatch.setattr(server, "get_agent", lambda: Agent(llm, settings, memory, None))
    return TestClient(server.app)


def test_chat_streams_sse(client):
    r = client.post("/api/chat", json={"message": "How many pilgrims are missing?", "lang": "en"})
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    types = [e["type"] for e in events]
    assert "trace" in types and "sql" in types and "table" in types and "token" in types
    assert events[-1]["type"] == "done" and events[-1]["answer"] == "Seven pilgrims are missing."


def test_runtime(client):
    d = client.get("/api/runtime").json()
    assert d["provider"] == "Nebius Token Factory"
    assert d["campaign"]["name_en"] == "MATS Demo Campaign"
    assert d["asr"]["enabled"] is False and d["tavily"] is False


def test_feedback_right_and_wrong(client):
    sql = "SELECT COUNT(*) FROM groups"
    assert client.post("/api/feedback", json={"question": "How many groups?", "sql": sql,
                                              "verdict": "right"}).json()["verified"]
    assert client.post("/api/feedback", json={"question": "How many groups?", "sql": sql,
                                              "verdict": "wrong"}).json()["forgotten"] >= 1
    assert client.post("/api/feedback", json={"question": "x", "sql": "DROP TABLE pilgrims",
                                              "verdict": "right"}).status_code == 400


def test_transcribe_without_asr_returns_503(client):
    r = client.post("/api/transcribe", files={"file": ("a.webm", b"123", "audio/webm")})
    assert r.status_code == 503


def test_wrong_feedback_becomes_a_lesson(client, memory):
    sql = "SELECT COUNT(*) FROM buses"
    r = client.post("/api/feedback", json={"question": "How many delayed buses?", "sql": sql,
                                           "verdict": "wrong"}).json()
    assert r["lesson"] is True
    assert memory.lessons("How many delayed buses?")[0]["bad_sql"] == sql


def test_memory_endpoints(client, memory):
    memory.add_fact("b1", "The user supervises group 7.")
    assert client.get("/api/memory?client_id=b1").json()["facts"] == ["The user supervises group 7."]
    assert client.delete("/api/memory/facts?client_id=b1").json()["forgotten"] == 1


def test_tts_is_off_by_default(client):
    assert client.get("/api/runtime").json()["tts"]["provider"] == "browser"
    assert client.get("/api/tts?text=hello&lang=en").status_code == 503
