"""
MATS Agent web server: FastAPI + SSE streaming.

Run:  uvicorn app.server:app --port 8000     then open http://localhost:8000
"""
import json
import sqlite3
from functools import lru_cache

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import guard
from .agent import Agent
from .config import ROOT, settings
from .memory import Memory
from .web_search import Tavily

WEB = ROOT / "web"

TTS_VOICES = {   # provider -> lang -> [(voice id, label)]; the first is the default
    "edge": {
        "ar": [("ar-SA-HamedNeural", "حامد · سعودي"), ("ar-SA-ZariyahNeural", "زارية · سعودية"),
               ("ar-KW-FahedNeural", "فهد · كويتي"), ("ar-AE-HamdanNeural", "حمدان · إماراتي")],
        "en": [("en-US-AndrewNeural", "Andrew · US"), ("en-US-AvaNeural", "Ava · US"),
               ("en-GB-RyanNeural", "Ryan · UK")],
    },
}
app = FastAPI(title="MATS Agent", docs_url=None, redoc_url=None)


def ensure_db():
    if not settings.db_path.exists():
        from data.generate_mock_data import build
        build(settings.db_path)


@lru_cache(maxsize=1)
def get_memory():
    ensure_db()
    settings.memory_db_path.parent.mkdir(parents=True, exist_ok=True)
    return Memory(settings.memory_db_path, settings.db_path)


@lru_cache(maxsize=1)
def get_agent():
    from .llm import NebiusLLM
    return Agent(NebiusLLM(settings), settings, get_memory(), Tavily(settings.tavily_api_key))


class Turn(BaseModel):
    role: str
    content: str
    context: str | None = None     # compact data behind an earlier answer


class ChatRequest(BaseModel):
    message: str
    history: list[Turn] = []
    lang: str = "ar"
    client_id: str | None = None   # per-browser id for remembered user facts


class FeedbackRequest(BaseModel):
    question: str
    sql: str | None = None
    verdict: str                   # right | wrong
    client_id: str | None = None


def sse(ev):
    return f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/runtime")
def runtime():
    ensure_db()
    conn = guard.connect(settings.db_path)
    try:
        name_ar, name_en, now = conn.execute(
            "SELECT name_ar, name_en, simulated_now FROM campaign").fetchone()
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("pilgrims", "groups", "buses", "trips", "incidents")}
    finally:
        conn.close()
    return {
        "provider": "Nebius Token Factory",
        "base_url": settings.nebius_base_url,
        "api_key_set": bool(settings.nebius_api_key),
        "models": {
            "fast": settings.model_fast,
            "fast_fallback": settings.model_fast_fallback,
            "answer": settings.model_answer,
            "router_reasoning": settings.model_router_reasoning,
            "sql": settings.model_sql,
            "complex": settings.model_complex,
        },
        "asr": {"enabled": bool(settings.asr_url), "model": settings.asr_model,
                "fallback": "browser Web Speech API"},
        "tavily": bool(settings.tavily_api_key),
        "tts": {"provider": tts_provider(),
                "voices": {lang: [{"id": v, "label": l} for v, l in vs]
                           for lang, vs in TTS_VOICES.get(tts_provider(), {}).items()}},
        "campaign": {"name_ar": name_ar, "name_en": name_en},
        "simulated_now": now,
        "counts": counts,
        "memory": get_memory().stats(),
        "safety": {"max_rows": settings.max_rows, "timeout_s": settings.query_timeout},
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    agent = get_agent()
    history = [t.model_dump() for t in req.history]

    def events():
        try:
            for ev in agent.run(req.message, history, req.lang if req.lang in ("ar", "en") else "ar",
                                client_id=(req.client_id or "")[:64] or None):
                yield sse(ev)
        except Exception as e:                       # never leave the stream hanging
            yield sse({"type": "error", "message": str(e)})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/feedback")
def feedback(fb: FeedbackRequest):
    mem = get_memory()
    if fb.verdict == "right":
        if not fb.sql:
            raise HTTPException(400, "No SQL to verify")
        try:
            res = mem.mark_right(fb.question, fb.sql)
        except (guard.UnsafeQuery, sqlite3.Error, TimeoutError) as e:
            raise HTTPException(400, f"SQL failed verification: {e}") from None
        return {"ok": True, "verified": True, **res}
    if fb.verdict == "wrong":
        if fb.sql:   # learn from the mistake, not just forget it
            mem.add_lesson(fb.question, fb.sql, "The user said this answer was wrong.", None, "wrong")
        return {"ok": True, "forgotten": mem.forget(fb.question, fb.sql), "lesson": bool(fb.sql)}
    raise HTTPException(400, "verdict must be 'right' or 'wrong'")


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("ar")):
    """Proxy audio to the Nemotron ASR endpoint (OpenAI-compatible /v1/audio/transcriptions)."""
    if not settings.asr_url:
        raise HTTPException(503, "ASR_URL not configured; use browser speech recognition")
    audio = await file.read()
    if len(audio) > 15 * 1024 * 1024:
        raise HTTPException(413, "Audio too large")
    url = settings.asr_url.rstrip("/")
    if not url.endswith("/v1/audio/transcriptions"):
        url += "/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.asr_token}"} if settings.asr_token else {}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                url, headers=headers,
                files={"file": (file.filename or "audio.webm", audio,
                                file.content_type or "audio/webm")},
                data={"model": settings.asr_model, "language": language})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"ASR endpoint error: {e}") from None
    return {"text": r.json().get("text", "").strip(), "model": settings.asr_model}


def tts_provider():
    p = settings.tts_provider
    if p == "openai" and not settings.tts_url:
        return "browser"
    return p if p in ("edge", "openai") else "browser"


@app.get("/api/tts")
async def tts(text: str, lang: str = "ar", voice: str = ""):
    """Stream one spoken sentence as MP3 (GET, so an <audio> element can play it as it arrives)."""
    provider = tts_provider()
    text = text.strip()[:600]
    if provider == "browser" or not text:
        raise HTTPException(503, "Server TTS is off; the browser voice is used")
    lang = "en" if lang == "en" else "ar"
    if provider == "edge":
        import edge_tts
        allowed = [v for v, _ in TTS_VOICES["edge"][lang]]
        comm = edge_tts.Communicate(text, voice if voice in allowed else allowed[0],
                                    rate=settings.tts_rate)

        async def audio():
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        return StreamingResponse(audio(), media_type="audio/mpeg",
                                 headers={"Cache-Control": "no-store"})
    # OpenAI-compatible speech endpoint (e.g. NVIDIA Magpie TTS on a Nebius endpoint)
    url = settings.tts_url.rstrip("/")
    if not url.endswith("/v1/audio/speech"):
        url += "/v1/audio/speech"
    headers = {"Authorization": f"Bearer {settings.tts_token}"} if settings.tts_token else {}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json={
            "model": settings.tts_model, "input": text, "voice": voice or lang,
            "response_format": "mp3"})
    if r.status_code != 200:
        raise HTTPException(502, f"TTS endpoint error {r.status_code}")
    return Response(r.content, media_type=r.headers.get("content-type", "audio/mpeg"))


@app.get("/api/memory")
def memory_view(client_id: str = ""):
    return get_memory().stats(client_id[:64] or None)


@app.delete("/api/memory/facts")
def forget_facts(client_id: str):
    return {"ok": True, "forgotten": get_memory().clear_facts(client_id[:64])}


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=WEB), name="static")
