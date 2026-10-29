"""
Nemotron on Nebius Token Factory (OpenAI-compatible API).

Every LLM call in MATS Agent goes through `NebiusLLM`. It:
  * talks to https://api.tokenfactory.nebius.com/v1 with NEBIUS_API_KEY,
  * falls back to a configured backup model when the primary is unavailable,
  * strips <think>...</think> reasoning traces, including across stream chunks.
"""
import re
import threading
import time
from typing import Iterator, Protocol

_THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove complete (or unterminated) <think> blocks and a stray leading </think>."""
    if not text:
        return ""
    text = _THINK_RE.sub("", text)
    # Some templates open the think block in the prompt, so only "</think>" arrives.
    if "</think>" in text.lower():
        text = re.split(r"</think>", text, flags=re.IGNORECASE)[-1]
    return text.strip()


class ThinkFilter:
    """Streaming filter that drops <think>...</think> even when tags are split across chunks."""

    OPEN, CLOSE = "<think>", "</think>"
    PREBUFFER = 48    # chars held back at the start to catch an orphan "</think>"

    def __init__(self):
        self.buf = ""
        self.inside = False
        self.started = False   # emitted any visible text yet?

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = []
        while self.buf:
            low = self.buf.lower()
            if self.inside:
                i = low.find(self.CLOSE)
                if i < 0:
                    # keep a tail that might be the start of "</think>"
                    self.buf = self.buf[-(len(self.CLOSE) - 1):]
                    break
                self.buf = self.buf[i + len(self.CLOSE):]
                self.inside = False
                continue
            i = low.find(self.OPEN)
            j = low.find(self.CLOSE)
            if j >= 0 and (i < 0 or j < i):
                # orphan closing tag: before any output, everything before it was reasoning
                if self.started:
                    out.append(self.buf[:j])
                self.buf = self.buf[j + len(self.CLOSE):]
                continue
            if i < 0 and not self.started and len(self.buf) < self.PREBUFFER:
                break      # wait: an orphan "</think>" may still arrive
            if i >= 0:
                out.append(self.buf[:i])
                self.buf = self.buf[i + len(self.OPEN):]
                self.inside = True
                continue
            # hold back a possible partial tag at the end
            hold = 0
            for k in range(1, len(self.CLOSE)):
                tail = low[-k:]
                if self.OPEN.startswith(tail) or self.CLOSE.startswith(tail):
                    hold = k
            emit = self.buf[: len(self.buf) - hold] if hold else self.buf
            out.append(emit)
            self.buf = self.buf[len(emit):]
            break
        text = "".join(out)
        if not self.started:
            text = text.lstrip()
        if text:
            self.started = True
        return text

    def flush(self) -> str:
        rest = "" if self.inside else self.buf
        self.buf = ""
        low = rest.lower()
        if self.OPEN.startswith(low) or self.CLOSE.startswith(low):
            return ""
        return rest if self.started else rest.lstrip()


class LLM(Protocol):
    def complete(self, model: str, messages: list, *, temperature: float = 0.0,
                 max_tokens: int = 800, timeout: float | None = None) -> str: ...

    def stream(self, model: str, messages: list, *, temperature: float = 0.3,
               max_tokens: int = 400) -> Iterator[str]: ...


class NebiusLLM:
    """OpenAI-compatible client for Nebius Token Factory."""

    def __init__(self, settings):
        from openai import OpenAI
        self.s = settings
        self.client = OpenAI(base_url=settings.nebius_base_url,
                             api_key=settings.nebius_api_key or "missing-key",
                             timeout=settings.llm_timeout, max_retries=1)
        self.fallbacks = {settings.model_fast: settings.model_fast_fallback}
        self._no_kwargs = set()   # models that rejected chat_template_kwargs
        self._local = threading.local()

    @property
    def last_model(self):
        """Model that actually served the last call on this thread (after fallback)."""
        return getattr(self._local, "model", None)

    def _extra(self, model):
        if self.s.disable_thinking and model not in self._no_kwargs:
            return {"chat_template_kwargs": {"enable_thinking": False}}
        return None

    def _create(self, m, timeout=None, **kw):
        from openai import BadRequestError
        client = self.client.with_options(timeout=timeout, max_retries=0) if timeout else self.client
        extra = self._extra(m)
        try:
            res = client.chat.completions.create(model=m, extra_body=extra, **kw)
        except BadRequestError:
            if extra is None:
                raise
            self._no_kwargs.add(m)       # template does not take kwargs: retry plain
            res = client.chat.completions.create(model=m, **kw)
        self._local.model = m
        return res

    def _call(self, model, **kw):
        """Call `model`; on 'model not found/unavailable' fall back to its backup."""
        from openai import BadRequestError, NotFoundError, PermissionDeniedError
        last = None
        for m in [m for m in (model, self.fallbacks.get(model)) if m]:
            try:
                return self._create(m, **kw)
            except (NotFoundError, PermissionDeniedError) as e:
                last = e
            except BadRequestError as e:
                if "model" not in str(e).lower():
                    raise
                last = e
        raise last

    def complete(self, model, messages, *, temperature=0.0, max_tokens=800, timeout=None):
        res = self._call(model, messages=messages, temperature=temperature,
                         max_tokens=max_tokens, timeout=timeout)
        return strip_think(res.choices[0].message.content or "")

    def stream(self, model, messages, *, temperature=0.3, max_tokens=400, timeout=None):
        res = self._call(model, messages=messages, temperature=temperature,
                         max_tokens=max_tokens, stream=True, timeout=timeout)
        f = ThinkFilter()
        for chunk in res:
            if not chunk.choices:
                continue
            piece = chunk.choices[0].delta.content or ""
            if piece:
                out = f.feed(piece)
                if out:
                    yield out
        tail = f.flush()
        if tail:
            yield tail


class Timer:
    def __init__(self):
        self.t0 = time.perf_counter()

    @property
    def ms(self):
        return int((time.perf_counter() - self.t0) * 1000)
