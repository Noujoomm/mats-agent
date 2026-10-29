"""
Nemotron ASR server: OpenAI-compatible POST /v1/audio/transcriptions.

Model: nvidia/nemotron-3.5-asr-streaming-0.6b (NeMo). Audio of any format is
converted to 16 kHz mono WAV with ffmpeg, then transcribed on the GPU.

Auth: if ASR_TOKEN is set, requests must send "Authorization: Bearer <ASR_TOKEN>".
(On a Nebius Serverless Endpoint created with --auth token, the platform checks
the token in front of the container as well.)
"""
import os
import subprocess
import tempfile
import threading
import time

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

MODEL_NAME = os.environ.get("ASR_MODEL", "nvidia/nemotron-3.5-asr-streaming-0.6b")
TOKEN = os.environ.get("ASR_TOKEN", "")

app = FastAPI(title="MATS ASR (Nemotron)")
_model = None
_lock = threading.Lock()


def model():
    global _model
    if _model is None:
        import nemo.collections.asr as nemo_asr
        _model = nemo_asr.models.ASRModel.from_pretrained(model_name=MODEL_NAME)
        _model.eval()
    return _model


@app.on_event("startup")
def warm():
    model()


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
                    "-ac", "1", "-ar", "16000", "-f", "wav", dst], check=True, timeout=60)


def _text(out):
    first = out[0] if isinstance(out, (list, tuple)) else out
    if isinstance(first, (list, tuple)):          # some versions return (best, all)
        first = first[0]
    return getattr(first, "text", first) or ""


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_NAME, "loaded": _model is not None}


@app.post("/v1/audio/transcriptions")
async def transcriptions(file: UploadFile = File(...), model_: str = Form(None, alias="model"),
                         language: str = Form(None), authorization: str = Header(None)):
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "Invalid token")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty audio")
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as d:
        src, wav = os.path.join(d, "in"), os.path.join(d, "in.wav")
        with open(src, "wb") as f:
            f.write(data)
        try:
            to_wav(src, wav)
        except subprocess.CalledProcessError:
            raise HTTPException(400, "Could not decode audio") from None
        with _lock:
            out = model().transcribe([wav], batch_size=1)
    return {"text": str(_text(out)).strip(), "model": MODEL_NAME, "language": language,
            "duration_ms": int((time.perf_counter() - t0) * 1000)}
