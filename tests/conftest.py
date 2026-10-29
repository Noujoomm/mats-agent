"""Offline fixtures: a fresh mock database and a scripted fake LLM (no network)."""
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings as base_settings  # noqa: E402
from data.generate_mock_data import build  # noqa: E402


class FakeLLM:
    """Scripted LLM. `script` maps a role ('route', 'sql', 'answer') to a list of
    replies consumed in order; every call is recorded as (role, model)."""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []
        self.prompts = []          # (role, messages) for every call
        self.last_model = None

    @staticmethod
    def _role(messages):
        sys_ = messages[0]["content"]
        if sys_.startswith("You route"):
            return "route"
        if sys_.startswith("You write one SQLite"):
            return "sql"
        return "answer"

    def _next(self, role, model):
        self.calls.append((role, model))
        self.last_model = model
        queue = self.script.get(role) or []
        if not queue:
            raise AssertionError(f"unexpected {role} call to {model}")
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def complete(self, model, messages, **kw):
        self.prompts.append((self._role(messages), messages))
        return self._next(self._role(messages), model)

    def stream(self, model, messages, **kw):
        self.prompts.append((self._role(messages), messages))
        text = self._next(self._role(messages), model)
        for i in range(0, len(text), 7):
            yield text[i:i + 7]

    def models_for(self, role):
        return [m for r, m in self.calls if r == role]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    return build(tmp_path_factory.mktemp("data") / "mats_demo.db")


@pytest.fixture
def settings(db_path, tmp_path):
    return replace(base_settings, db_path=db_path, memory_db_path=tmp_path / "memory.db",
                   nebius_api_key="test", tavily_api_key="", asr_url="", tts_provider="browser")


@pytest.fixture
def memory(settings):
    from app.memory import Memory
    return Memory(settings.memory_db_path, settings.db_path)


@pytest.fixture
def make_agent(settings, memory):
    from app.agent import Agent

    def _make(script, web=None):
        llm = FakeLLM(script)
        return Agent(llm, settings, memory, web), llm
    return _make


def collect(agent, question, history=None, lang="ar", client_id=None):
    return list(agent.run(question, history or [], lang, client_id=client_id))
