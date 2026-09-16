"""Provider-aware AI engine for quiz solving.

Groq is the primary text solver; Gemini (google-genai) is an independent
fallback. Rate limiting is provider-wide (organization/project), not key-wide.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
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


class _RateGate:
    def __init__(self, min_interval: float):
        self.min_interval = float(min_interval)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self.min_interval - (now - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


def _secrets():
    try:
        import streamlit as st
        return st.secrets
    except Exception:
        class _Env:
            def get(self, key, default=""):
                return os.environ.get(key, default)
        return _Env()


def _keys(prefix: str, maximum: int = 20) -> list[str]:
    sec = _secrets()
    names = [prefix] + [f"{prefix}{i}" for i in range(1, maximum + 1)]
    out = []
    for name in names:
        value = str(sec.get(name, "") or "").strip()
        if value and len(value) > 10 and value not in out:
            out.append(value)
    return out


# These are deliberately conservative. Actual limits are account/project/org
# specific and must be read from provider dashboards/headers; these settings
# prevent the bot itself from generating a burst that is likely to hit them.
GROQ_MODEL = os.getenv("GROQ_AI_MODEL", "openai/gpt-oss-20b")
GROQ_MIN_INTERVAL = float(os.getenv("GROQ_AI_MIN_INTERVAL", "3.0"))
GROQ_MAX_OUTPUT = int(os.getenv("GROQ_AI_MAX_OUTPUT", "900"))

GEMINI_MODEL = os.getenv("GEMINI_AI_MODEL", "gemini-3.6-flash")
GEMINI_MIN_INTERVAL = float(os.getenv("GEMINI_AI_MIN_INTERVAL", "7.0"))
GEMINI_MAX_OUTPUT = int(os.getenv("GEMINI_AI_MAX_OUTPUT", "600"))

_groq_gate = _RateGate(GROQ_MIN_INTERVAL)
_gemini_gate = _RateGate(GEMINI_MIN_INTERVAL)
@dataclass
class _Circuit:
    cooldown_until: float = 0.0
    failures: int = 0

    def available(self) -> bool:
        return time.monotonic() >= self.cooldown_until

    def trip(self, retry_after: float | None = None, base: float = 30.0, cap: float = 300.0) -> float:
        self.failures += 1
        delay = retry_after if retry_after is not None else min(cap, base * (2 ** min(self.failures - 1, 4)))
        delay = max(1.0, min(cap, float(delay)))
        self.cooldown_until = time.monotonic() + delay
        return delay

    def success(self) -> None:
        self.cooldown_until = 0.0
        self.failures = 0


_groq_index = 0
_gemini_index = 0
_groq_circuit = _Circuit()
_gemini_circuit = _Circuit()



def _json_text(text: str) -> Any:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.replace("```json", "", 1).replace("```", "", 1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _normalize(items: Any) -> list[dict]:
    if not isinstance(items, list):
        raise ValueError("AI javobi JSON array emas")
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["idx"])
            ci = int(item["correct_idx"])
        except Exception:
            continue
        result.append({
            "idx": idx,
            "correct_idx": ci,
            "explanation": str(item.get("explanation", "") or "").strip(),
        })
    if not result:
        raise ValueError("AI javobida yaroqli savol natijasi yo'q")
    return result



def _status_code(exc: BaseException) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        value = getattr(obj, "status_code", None)
        if value is None:
            value = getattr(obj, "code", None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _retry_after(exc: BaseException) -> float | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for name in ("retry_after", "retry_after_seconds"):
            value = getattr(obj, name, None)
            if value is not None:
                try:
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
    status = _status_code(exc)
    if status == 429:
        return True
    msg = str(exc).lower()
    return any(x in msg for x in (
        "rate limit", "rate_limit", "too many requests", "resource exhausted",
        "quota exceeded", "quota exhausted", "daily limit", "tokens per minute",
    ))


def _is_network_error(exc: BaseException) -> bool:
    # aiohttp connection exceptions are imported from their supported module.
    try:
        from aiohttp.client_exceptions import ClientConnectionError
        if isinstance(exc, ClientConnectionError):
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    return any(x in msg for x in (
        "clientconnector", "dns", "name or service not known",
        "temporary failure in name resolution", "connection reset",
        "connection refused", "network is unreachable", "timed out",
        "timeout", "server disconnected",
    ))


async def _close_client(client: Any) -> None:
    """Best-effort cleanup for official async SDK clients."""
    if client is None:
        return
    candidates = []
    aio = getattr(client, "aio", None)
    if aio is not None:
        candidates += [getattr(aio, "aclose", None), getattr(aio, "close", None)]
    candidates += [getattr(client, "aclose", None), getattr(client, "close", None)]
    seen = set()
    for fn in candidates:
        if not callable(fn) or id(fn) in seen:
            continue
        seen.add(id(fn))
        try:
            result = fn()
            if inspect.isawaitable(result):
                await result
            return
        except Exception:
            continue


async def _call_groq(system_prompt: str, user_prompt: str) -> tuple[list[dict], str]:
    global _groq_index
    keys = _keys("GROQ_API_KEY", 20)
    if not keys:
        raise AIProviderError("Groq", "GROQ_API_KEY topilmadi", retryable=False)
    if not _groq_circuit.available():
        remaining = max(0, _groq_circuit.cooldown_until - time.monotonic())
        raise AIProviderError("Groq", f"rate-limit cooldown: {remaining:.0f}s", rate_limited=True, retry_after=remaining)
    try:
        from groq import AsyncGroq
    except Exception as exc:
        raise AIProviderError("Groq", f"SDK yuklanmadi: {exc}", retryable=False) from exc
    for _ in range(len(keys)):
        key = keys[_groq_index % len(keys)]
        _groq_index += 1
        client = None
        try:
            await _groq_gate.wait()
            client = AsyncGroq(api_key=key)
            completion = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0,
                max_completion_tokens=GROQ_MAX_OUTPUT,
                include_reasoning=False,
            )
            result = _normalize(_json_text(completion.choices[0].message.content or ""))
            _groq_circuit.success()
            return result, "Groq"
        except Exception as exc:
            msg = str(exc)
            if _is_rate_limit(exc):
                delay = _groq_circuit.trip(_retry_after(exc), base=30.0, cap=300.0)
                raise AIProviderError("Groq", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
            if _is_network_error(exc):
                delay = _groq_circuit.trip(base=15.0, cap=120.0)
                raise AIProviderError("Groq", f"network error; cooldown {delay:.0f}s: {msg[:140]}", retryable=True, retry_after=delay) from exc
            raise AIProviderError("Groq", f"{_status_code(exc) or ''}: {msg[:180]}", retryable=False) from exc
        finally:
            await _close_client(client)
    raise AIProviderError("Groq", "barcha Groq credential urinishlari muvaffaqiyatsiz", retryable=True)


async def _call_gemini(system_prompt: str, user_prompt: str) -> tuple[list[dict], str]:
    global _gemini_index
    keys = _keys("GEMINI_API_KEY", 20)
    if not keys:
        raise AIProviderError("Gemini", "GEMINI_API_KEY topilmadi", retryable=False)
    if not _gemini_circuit.available():
        remaining = max(0, _gemini_circuit.cooldown_until - time.monotonic())
        raise AIProviderError("Gemini", f"rate-limit cooldown: {remaining:.0f}s", rate_limited=True, retry_after=remaining)
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise AIProviderError("Gemini", f"SDK yuklanmadi: {exc}", retryable=False) from exc
    for _ in range(len(keys)):
        key = keys[_gemini_index % len(keys)]
        _gemini_index += 1
        client = None
        try:
            await _gemini_gate.wait()
            client = genai.Client(api_key=key)
            response = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0,
                    max_output_tokens=GEMINI_MAX_OUTPUT,
                    response_mime_type="application/json",
                ),
            )
            result = _normalize(_json_text(response.text or ""))
            _gemini_circuit.success()
            return result, "Gemini"
        except Exception as exc:
            msg = str(exc)
            if _is_rate_limit(exc):
                delay = _gemini_circuit.trip(_retry_after(exc), base=30.0, cap=300.0)
                raise AIProviderError("Gemini", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
            if _is_network_error(exc):
                delay = _gemini_circuit.trip(base=15.0, cap=120.0)
                raise AIProviderError("Gemini", f"network error; cooldown {delay:.0f}s: {msg[:140]}", retryable=True, retry_after=delay) from exc
            raise AIProviderError("Gemini", f"{_status_code(exc) or ''}: {msg[:180]}", retryable=False) from exc
        finally:
            await _close_client(client)
    raise AIProviderError("Gemini", "barcha Gemini credential urinishlari muvaffaqiyatsiz", retryable=True)


async def solve_text_batch(system_prompt: str, user_prompt: str) -> tuple[list[dict], str]:
    """Groq primary -> Gemini fallback; successful Groq auto-restores primary."""
    errors = []
    # Groq is optional. If no Groq key exists, go directly to Gemini without
    # polluting the error log with a missing-optional-provider message.
    if _keys("GROQ_API_KEY", 20):
        try:
            return await _call_groq(system_prompt, user_prompt)
        except AIProviderError as exc:
            errors.append(str(exc))
    try:
        return await _call_gemini(system_prompt, user_prompt)
    except AIProviderError as exc:
        errors.append(str(exc))
    raise AIProviderError(
        "AI", "; ".join(errors), retryable=True,
        rate_limited=any("rate limit" in x.lower() or "cooldown" in x.lower() for x in errors),
    )


async def solve_image(image_bytes: bytes, mime_type: str, prompt: str) -> dict:
    """Gemini multimodal solver using the official google-genai SDK."""
    global _gemini_index
    keys = _keys("GEMINI_API_KEY", 20)
    if not keys:
        raise AIProviderError("Gemini", "GEMINI_API_KEY topilmadi", retryable=False)
    if not _gemini_circuit.available():
        remaining = max(0, _gemini_circuit.cooldown_until - time.monotonic())
        raise AIProviderError("Gemini", f"rate-limit cooldown: {remaining:.0f}s", rate_limited=True, retry_after=remaining)
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise AIProviderError("Gemini", f"SDK yuklanmadi: {exc}", retryable=False) from exc
    for _ in range(len(keys)):
        key = keys[_gemini_index % len(keys)]
        _gemini_index += 1
        client = None
        try:
            await _gemini_gate.wait()
            client = genai.Client(api_key=key)
            response = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=400, response_mime_type="application/json"),
            )
            data = _json_text(response.text or "")
            if not isinstance(data, dict):
                raise ValueError("Gemini vision javobi object emas")
            _gemini_circuit.success()
            return data
        except Exception as exc:
            msg = str(exc)
            if _is_rate_limit(exc):
                delay = _gemini_circuit.trip(_retry_after(exc), base=30.0, cap=300.0)
                raise AIProviderError("Gemini", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
            if _is_network_error(exc):
                delay = _gemini_circuit.trip(base=15.0, cap=120.0)
                raise AIProviderError("Gemini", f"network error; cooldown {delay:.0f}s: {msg[:140]}", retryable=True, retry_after=delay) from exc
            raise AIProviderError("Gemini", f"{_status_code(exc) or ''}: {msg[:180]}", retryable=False) from exc
        finally:
            await _close_client(client)
    raise AIProviderError("Gemini", "barcha Gemini credential urinishlari muvaffaqiyatsiz", retryable=True)

