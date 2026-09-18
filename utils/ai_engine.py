"""Quiztime AI engine.

- Text solving: Groq -> Gemini fallback.
- Up to 10 Groq credentials: GROQ_API_KEY, GROQ_API_KEY1..10.
- Up to 10 Gemini credentials: GEMINI_API_KEY, GEMINI_API_KEY1..10.
- Per-credential cooldowns; one exhausted key does not block the others.
- 503/network errors get short exponential retries.
- 429/quota errors cooldown only the affected credential and fail over.
- Gemini uses the current stable Gemini 3.8 Flash model by default.
- No format-repair API exists here: parsing is strictly parser-only.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class AIProviderError(Exception):
    provider: str
    message: str
    retryable: bool = True
    rate_limited: bool = False
    retry_after: float | None = None

    def __str__(self) -> str:
        return f"[{self.provider}] {self.message}"


@dataclass
class _CredentialState:
    cooldown_until: float = 0.0
    failures: int = 0
    last_used: float = 0.0

    def available(self) -> bool:
        return time.monotonic() >= self.cooldown_until

    def trip(self, retry_after: float | None = None, *, base: float, cap: float) -> float:
        self.failures += 1
        delay = retry_after if retry_after is not None else min(cap, base * (2 ** min(self.failures - 1, 4)))
        delay = max(1.0, min(cap, float(delay)))
        self.cooldown_until = time.monotonic() + delay
        return delay

    def success(self) -> None:
        self.cooldown_until = 0.0
        self.failures = 0
        self.last_used = time.monotonic()


class _CredentialPool:
    def __init__(self, prefix: str, maximum: int = 10):
        self.prefix = prefix
        self.maximum = maximum
        self._states: dict[str, _CredentialState] = {}
        self._cursor = 0
        self._lock = asyncio.Lock()

    def _read_keys(self) -> list[str]:
        sec = _secrets()
        names = [self.prefix] + [f"{self.prefix}{i}" for i in range(1, self.maximum + 1)]
        out: list[str] = []
        for name in names:
            value = str(sec.get(name, "") or "").strip()
            if value and len(value) > 10 and value not in out:
                out.append(value)
        for key in out:
            self._states.setdefault(key, _CredentialState())
        # Remove keys that were deleted from secrets so stale state cannot linger.
        for key in list(self._states):
            if key not in out:
                self._states.pop(key, None)
        return out

    async def acquire(self) -> tuple[str, _CredentialState] | None:
        async with self._lock:
            keys = self._read_keys()
            if not keys:
                return None
            now = time.monotonic()
            available = [k for k in keys if self._states[k].cooldown_until <= now]
            if not available:
                return None
            # Prefer the least-recently-used available credential, with a stable
            # cursor tie-breaker. This avoids hammering one key repeatedly.
            available.sort(key=lambda k: (self._states[k].last_used, keys.index(k)))
            key = available[0]
            self._states[key].last_used = now
            self._cursor = (keys.index(key) + 1) % len(keys)
            return key, self._states[key]

    async def next_wait(self) -> float:
        async with self._lock:
            keys = self._read_keys()
            if not keys:
                return 0.0
            now = time.monotonic()
            waits = [max(0.0, self._states[k].cooldown_until - now) for k in keys]
            return min(waits) if waits else 0.0

    def count(self) -> int:
        return len(self._read_keys())



def _secrets():
    try:
        import streamlit as st
        return st.secrets
    except Exception:
        class _Env:
            def get(self, key, default=""):
                return os.environ.get(key, default)
        return _Env()


GROQ_MODEL = os.getenv("GROQ_AI_MODEL", "openai/gpt-oss-120b")
GROQ_MAX_OUTPUT = int(os.getenv("GROQ_AI_MAX_OUTPUT", "1800"))
GROQ_MAX_ATTEMPTS = int(os.getenv("GROQ_AI_MAX_ATTEMPTS", "3"))
GROQ_MIN_INTERVAL = float(os.getenv("GROQ_AI_MIN_INTERVAL", "1.2"))

GEMINI_MODEL = os.getenv("GEMINI_AI_MODEL", "gemini-3.8-flash")
GEMINI_MAX_OUTPUT = int(os.getenv("GEMINI_AI_MAX_OUTPUT", "2200"))
GEMINI_MAX_ATTEMPTS = int(os.getenv("GEMINI_AI_MAX_ATTEMPTS", "3"))
GEMINI_MIN_INTERVAL = float(os.getenv("GEMINI_AI_MIN_INTERVAL", "1.2"))
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_AI_THINKING_LEVEL", "high").strip().lower()
if GEMINI_THINKING_LEVEL not in {"low", "medium", "high"}:
    GEMINI_THINKING_LEVEL = "high"

_GROQ_POOL = _CredentialPool("GROQ_API_KEY", 10)
_GEMINI_POOL = _CredentialPool("GEMINI_API_KEY", 10)
_GROQ_GATE = asyncio.Lock()
_GEMINI_GATE = asyncio.Lock()
_GROQ_LAST = 0.0
_GEMINI_LAST = 0.0

RESULT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "idx": {"type": "integer"},
        "correct_idx": {"type": "integer"},
        "explanation": {"type": "string"},
    },
    "required": ["idx", "correct_idx", "explanation"],
    "additionalProperties": False,
}
RESULT_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": RESULT_ITEM_SCHEMA}},
    "required": ["results"],
    "additionalProperties": False,
}


def _json_text(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("AI bo'sh javob qaytardi")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for opener, closer in (("{", "}"), ("[", "]")):
            start, end = text.find(opener), text.rfind(closer)
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1])
        raise


def _normalize_results(data: Any) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("results")
    if not isinstance(data, list):
        raise ValueError("AI javobida results array yo'q")
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["idx"])
            ci = int(item["correct_idx"])
        except Exception:
            continue
        out.append({
            "idx": idx,
            "correct_idx": ci,
            "explanation": str(item.get("explanation", "") or "").strip(),
        })
    if not out:
        raise ValueError("AI javobida yaroqli natija yo'q")
    return out


def _status_code(exc: BaseException) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for attr in ("status_code", "code"):
            try:
                value = getattr(obj, attr, None)
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _retry_after(exc: BaseException) -> float | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for attr in ("retry_after", "retry_after_seconds"):
            try:
                value = getattr(obj, attr, None)
                if value is not None:
                    return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
        headers = getattr(obj, "headers", None)
        if headers:
            try:
                value = headers.get("retry-after") or headers.get("Retry-After")
                if value is not None:
                    return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
    return None


def _is_rate_limit(exc: BaseException) -> bool:
    if _status_code(exc) == 429:
        return True
    msg = str(exc).lower()
    return any(x in msg for x in (
        "rate limit", "rate_limit", "too many requests", "resource exhausted",
        "quota exceeded", "quota exhausted", "daily limit", "tokens per minute",
        "requests per minute", "requests per day",
    ))


def _is_transient(exc: BaseException) -> bool:
    status = _status_code(exc)
    if status in {408, 409, 425, 500, 502, 503, 504}:
        return True
    msg = str(exc).lower()
    return any(x in msg for x in (
        "service unavailable", "temporarily unavailable", "overloaded",
        "server disconnected", "connection reset", "connection refused",
        "network is unreachable", "timed out", "timeout", "temporary failure",
        "dns", "name or service not known",
    ))


async def _pace(lock: asyncio.Lock, last_name: str, interval: float) -> None:
    # Kept as a small shared helper; callers update the global timestamp.
    global _GROQ_LAST, _GEMINI_LAST
    async with lock:
        now = time.monotonic()
        last = _GROQ_LAST if last_name == "groq" else _GEMINI_LAST
        wait = interval - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        now = time.monotonic()
        if last_name == "groq":
            _GROQ_LAST = now
        else:
            _GEMINI_LAST = now


async def _close_client(client: Any) -> None:
    if client is None:
        return
    funcs = []
    aio = getattr(client, "aio", None)
    if aio is not None:
        funcs += [getattr(aio, "aclose", None), getattr(aio, "close", None)]
    funcs += [getattr(client, "aclose", None), getattr(client, "close", None)]
    seen = set()
    for fn in funcs:
        if not callable(fn) or id(fn) in seen:
            continue
        seen.add(id(fn))
        try:
            result = fn()
            if inspect.isawaitable(result):
                await result
            return
        except Exception:
            pass


async def _groq_once(system_prompt: str, user_prompt: str, key: str) -> Any:
    try:
        from groq import AsyncGroq
    except Exception as exc:
        raise AIProviderError("Groq", f"SDK yuklanmadi: {exc}", retryable=False) from exc
    client = None
    try:
        await _pace(_GROQ_GATE, "groq", GROQ_MIN_INTERVAL)
        client = AsyncGroq(api_key=key)
        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_completion_tokens=GROQ_MAX_OUTPUT,
            # json_object is intentionally used instead of provider-specific
            # json_schema: it is accepted by a wider range of Groq models.
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or ""
        return _json_text(content)
    finally:
        await _close_client(client)


async def _gemini_once(system_prompt: str, user_prompt: str, key: str, *, image: bytes | None = None, mime_type: str = "image/jpeg") -> Any:
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise AIProviderError("Gemini", f"SDK yuklanmadi: {exc}", retryable=False) from exc
    client = None
    try:
        await _pace(_GEMINI_GATE, "gemini", GEMINI_MIN_INTERVAL)
        client = genai.Client(api_key=key)
        if image is None:
            contents: Any = user_prompt
        else:
            contents = [
                types.Part.from_text(text=user_prompt),
                types.Part.from_bytes(data=image, mime_type=mime_type),
            ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=GEMINI_MAX_OUTPUT,
            response_mime_type="application/json",
            response_json_schema=RESULT_SCHEMA if image is None else None,
            thinking_config=types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL),
        )
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        return _json_text(response.text or "")
    finally:
        await _close_client(client)


async def _try_pool_call(pool: _CredentialPool, provider: str, fn, *, attempts: int, base: float, cap: float) -> tuple[Any, str]:
    errors: list[str] = []
    attempted_keys: set[str] = set()
    max_rounds = max(1, min(pool.maximum, pool.count() or 1))

    for _round in range(max_rounds):
        acquired = await pool.acquire()
        if acquired is None:
            wait = await pool.next_wait()
            if wait > 0:
                # Do not sleep for a long quota cooldown here; another provider
                # should get a chance immediately. Caller can invoke this pool again later.
                break
            break
        key, state = acquired
        if key in attempted_keys:
            break
        attempted_keys.add(key)

        for attempt in range(1, max(1, attempts) + 1):
            try:
                data = await fn(key)
                state.success()
                return data, provider
            except Exception as exc:
                if isinstance(exc, AIProviderError):
                    status = exc
                else:
                    status = None
                rate = _is_rate_limit(exc)
                transient = _is_transient(exc)
                msg = str(exc)

                if rate:
                    delay = state.trip(_retry_after(exc), base=base, cap=cap)
                    errors.append(f"{provider} key#{len(attempted_keys)} 429/cooldown {delay:.0f}s")
                    # Quota is not helped by retrying the same credential.
                    break

                if transient and attempt < max(1, attempts):
                    delay = min(cap, base * (2 ** (attempt - 1)))
                    errors.append(f"{provider} key#{len(attempted_keys)} transient { _status_code(exc) or '' } retry {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

                if transient:
                    delay = state.trip(_retry_after(exc), base=base, cap=cap)
                    errors.append(f"{provider} key#{len(attempted_keys)} transient cooldown {delay:.0f}s")
                else:
                    errors.append(f"{provider} key#{len(attempted_keys)}: {msg[:180]}")
                break

    raise AIProviderError(provider, "; ".join(errors) or f"{provider} credentiallari mavjud emas", retryable=True,
                          rate_limited=any("429" in e or "cooldown" in e for e in errors))


async def solve_text_batch(system_prompt: str, user_prompt: str) -> tuple[list[dict], str]:
    """Solve one batch. Groq is primary; Gemini is fallback."""
    errors: list[str] = []
    if _GROQ_POOL.count():
        try:
            data, provider = await _try_pool_call(
                _GROQ_POOL, "Groq", lambda key: _groq_once(system_prompt, user_prompt, key),
                attempts=GROQ_MAX_ATTEMPTS, base=1.5, cap=12.0,
            )
            return _normalize_results(data), provider
        except AIProviderError as exc:
            errors.append(str(exc))

    if _GEMINI_POOL.count():
        try:
            data, provider = await _try_pool_call(
                _GEMINI_POOL, "Gemini", lambda key: _gemini_once(system_prompt, user_prompt, key),
                attempts=GEMINI_MAX_ATTEMPTS, base=2.0, cap=15.0,
            )
            return _normalize_results(data), provider
        except AIProviderError as exc:
            errors.append(str(exc))

    raise AIProviderError("AI", "; ".join(errors) or "Groq/Gemini API key topilmadi", retryable=True,
                          rate_limited=any("429" in e or "cooldown" in e for e in errors))


async def solve_image(image_bytes: bytes, mime_type: str, prompt: str) -> dict:
    """Solve an image question with Gemini Vision using the same 10-key pool."""
    if not _GEMINI_POOL.count():
        raise AIProviderError("Gemini", "GEMINI_API_KEY topilmadi", retryable=False)
    system = (
        "Siz yuqori aniqlikdagi test eksperti. Rasmni diqqat bilan o'qing. "
        "Faqat berilgan savol va variantlardan foydalaning. Fakt to'qimang. "
        "Natijani faqat JSON object sifatida qaytaring: "
        '{"correct_idx":0,"explanation":"..."}. correct_idx 0-based.'
    )
    schema = {
        "type": "object",
        "properties": {
            "correct_idx": {"type": "integer"},
            "explanation": {"type": "string"},
        },
        "required": ["correct_idx", "explanation"],
        "additionalProperties": False,
    }
    # Use a dedicated call because solve_image has a different output schema.
    errors: list[str] = []
    acquired_attempts = max(1, min(_GEMINI_POOL.maximum, _GEMINI_POOL.count() or 1))
    seen: set[str] = set()
    for _ in range(acquired_attempts):
        acquired = await _GEMINI_POOL.acquire()
        if acquired is None:
            break
        key, state = acquired
        if key in seen:
            break
        seen.add(key)
        for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
            try:
                try:
                    from google import genai
                    from google.genai import types
                except Exception as exc:
                    raise AIProviderError("Gemini", f"SDK yuklanmadi: {exc}", retryable=False) from exc
                client = None
                try:
                    await _pace(_GEMINI_GATE, "gemini", GEMINI_MIN_INTERVAL)
                    client = genai.Client(api_key=key)
                    config = types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=900,
                        response_mime_type="application/json",
                        response_json_schema=schema,
                        thinking_config=types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL),
                    )
                    response = await client.aio.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
                        config=config,
                    )
                    data = _json_text(response.text or "")
                finally:
                    await _close_client(client)
                if not isinstance(data, dict):
                    raise ValueError("Gemini vision javobi object emas")
                state.success()
                return data
            except Exception as exc:
                if _is_rate_limit(exc):
                    delay = state.trip(_retry_after(exc), base=30, cap=300)
                    errors.append(f"Gemini key#{len(seen)} 429 cooldown {delay:.0f}s")
                    break
                if _is_transient(exc) and attempt < GEMINI_MAX_ATTEMPTS:
                    delay = min(15.0, 2.0 * (2 ** (attempt - 1)))
                    await asyncio.sleep(delay)
                    continue
                if _is_transient(exc):
                    delay = state.trip(_retry_after(exc), base=10, cap=120)
                    errors.append(f"Gemini key#{len(seen)} transient cooldown {delay:.0f}s")
                else:
                    errors.append(f"Gemini key#{len(seen)}: {str(exc)[:180]}")
                break
    raise AIProviderError("Gemini", "; ".join(errors) or "Gemini credentiallari mavjud emas", retryable=True,
                          rate_limited=any("429" in e for e in errors))
