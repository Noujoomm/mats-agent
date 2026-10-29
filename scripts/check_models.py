"""
List the Nemotron models available on Nebius Token Factory and ping each configured one.

Usage:  python scripts/check_models.py          (reads NEBIUS_API_KEY and MODEL_* from env/.env)
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm import strip_think  # noqa: E402


def main():
    if not settings.nebius_api_key:
        sys.exit("NEBIUS_API_KEY is not set (see .env.example)")
    client = OpenAI(base_url=settings.nebius_base_url, api_key=settings.nebius_api_key, timeout=60)

    print(f"Token Factory: {settings.nebius_base_url}\n")
    try:
        ids = sorted(m.id for m in client.models.list().data)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not list models: {e}")
    nemotron = [i for i in ids if "nemotron" in i.lower()]
    print(f"{len(ids)} models available, {len(nemotron)} Nemotron:")
    for i in nemotron:
        print("  ", i)

    roles = [("MODEL_FAST", settings.model_fast), ("MODEL_FAST_FALLBACK", settings.model_fast_fallback),
             ("MODEL_SQL", settings.model_sql), ("MODEL_COMPLEX", settings.model_complex)]
    print("\nPinging configured models:")
    ok = True
    for env, model in roles:
        listed = "listed" if model in ids else "NOT LISTED"
        t0 = time.perf_counter()
        try:
            res = client.chat.completions.create(
                model=model, max_tokens=60, temperature=0,
                messages=[{"role": "user", "content": "Reply with the single word: ready"}])
            reply = strip_think(res.choices[0].message.content or "")[:40]
            print(f"  OK   {env:20} {model}  ({listed}, {int((time.perf_counter() - t0) * 1000)} ms) -> {reply!r}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"  FAIL {env:20} {model}  ({listed}) -> {str(e)[:160]}")
    if not ok:
        print("\nSet the failing MODEL_* variables to IDs from the Nemotron list above.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
