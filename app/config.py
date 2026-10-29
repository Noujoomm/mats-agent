"""Runtime settings. Everything comes from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # optional: load a local .env when python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _env(name, default=""):
    v = os.environ.get(name, "")
    return v.strip() if v.strip() else default


@dataclass
class Settings:
    nebius_base_url: str = field(default_factory=lambda: _env(
        "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"))
    nebius_api_key: str = field(default_factory=lambda: _env("NEBIUS_API_KEY"))

    # Model routing (all NVIDIA Nemotron on Nebius Token Factory)
    model_fast: str = field(default_factory=lambda: _env(
        "MODEL_FAST", "nvidia/Nemotron-3_5-Lightning"))
    model_fast_fallback: str = field(default_factory=lambda: _env(
        "MODEL_FAST_FALLBACK", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"))
    # Streamed spoken answer (defaults to the fast model)
    model_answer: str = field(default_factory=lambda: _env(
        "MODEL_ANSWER", _env("MODEL_FAST", "nvidia/Nemotron-3_5-Lightning")))
    # Routing that needs reasoning: references to earlier answers or remembered facts,
    # and deciding whether to ask a clarifying question (defaults to the SQL model, Super)
    model_router_reasoning: str = field(default_factory=lambda: _env(
        "MODEL_ROUTER_REASONING", _env("MODEL_SQL", "nvidia/nemotron-3-super-120b-a12b")))
    model_sql: str = field(default_factory=lambda: _env(
        "MODEL_SQL", "nvidia/nemotron-3-super-120b-a12b"))
    model_complex: str = field(default_factory=lambda: _env(
        "MODEL_COMPLEX", "nvidia/Nemotron-3-Ultra-550b-a55b"))
    # Ask the chat template to skip reasoning traces (they are stripped anyway)
    disable_thinking: bool = field(default_factory=lambda: _env(
        "LLM_DISABLE_THINKING", "1") == "1")
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "60")))

    db_path: Path = field(default_factory=lambda: Path(_env(
        "DB_PATH", str(ROOT / "data" / "mats_demo.db"))))
    memory_db_path: Path = field(default_factory=lambda: Path(_env(
        "MEMORY_DB_PATH", str(ROOT / "data" / "memory.db"))))
    max_rows: int = field(default_factory=lambda: int(_env("MAX_ROWS", "200")))
    query_timeout: float = field(default_factory=lambda: float(_env("QUERY_TIMEOUT", "3")))

    tavily_api_key: str = field(default_factory=lambda: _env("TAVILY_API_KEY"))

    # Spoken replies: browser (Web Speech) | edge (Microsoft neural voices, incl. Saudi
    # ar-SA Hamed/Zariyah) | openai (any OpenAI-compatible /v1/audio/speech, e.g. a
    # self-hosted NVIDIA Magpie TTS endpoint)
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "browser").lower())
    tts_url: str = field(default_factory=lambda: _env("TTS_URL"))
    tts_token: str = field(default_factory=lambda: _env("TTS_TOKEN"))
    tts_model: str = field(default_factory=lambda: _env("TTS_MODEL", "magpie-tts-multilingual"))
    tts_rate: str = field(default_factory=lambda: _env("TTS_RATE", "+0%"))

    asr_url: str = field(default_factory=lambda: _env("ASR_URL"))
    asr_token: str = field(default_factory=lambda: _env("ASR_TOKEN"))
    asr_model: str = field(default_factory=lambda: _env(
        "ASR_MODEL", "nvidia/nemotron-3.5-asr-streaming-0.6b"))


settings = Settings()
