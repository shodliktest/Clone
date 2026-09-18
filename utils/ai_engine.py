"""Production AI engine for Quiztime.

Text solving: Groq primary -> Gemini fallback.
Parser/format handling is performed by utils.parser; this module is AI-solving only.
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


class _RateGate:
    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, float(min_interval))
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self.min_interval - (time.monotonic() - self._last)
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
    result = []
    for name in names:
        try:
            value = str(sec.get(name, "") or "").strip()
        except Exception:
            value = os.environ.get(name, "").strip()
        if value and len(value) > 10 and value not in result:
            result.append(value)
    return result


_groq_env_model = os.getenv("GROQ_AI_MODEL", "").strip()
GROQ_MODEL = _groq_env_model or "openai/gpt-oss-120b"
_gemini_env_model = os.getenv("GEMINI_AI_MODEL", "").strip()
# Never let an old deployment override the required current Gemini model.
GEMINI_MODEL = "gemini-3.6-flash" if (not _gemini_env_model or re.search(r"gemini-2\.\d", _gemini_env_model.lower())) else _gemini_env_model
GROQ_MIN_INTERVAL = float(os.getenv("GROQ_AI_MIN_INTERVAL", "4.0"))
GEMINI_MIN_INTERVAL = float(os.getenv("GEMINI_AI_MIN_INTERVAL", "2.0"))
GROQ_MAX_OUTPUT = int(os.getenv("GROQ_AI_MAX_OUTPUT", "5000"))
GEMINI_MAX_OUTPUT = int(os.getenv("GEMINI_AI_MAX_OUTPUT", "5000"))

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

def _extract_json(text: str) -> Any:
    """Parse JSON robustly, including fenced/object/array responses."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("AI bo'sh javob qaytardi")
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        starts = [p for p in (raw.find("{"), raw.find("[")) if p >= 0]
        if not starts:
            raise
        start = min(starts)
        end_obj = raw.rfind("}")
        end_arr = raw.rfind("]")
        end = max(end_obj, end_arr)
        if end <= start:
            raise
        return json.loads(raw[start:end + 1])


def _normalize_results(data: Any) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("results")
    if not isinstance(data, list):
        raise ValueError("AI javobi results array emas")
    out = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["idx"])
            ci = int(item["correct_idx"])
        except Exception:
            continue
        if idx in seen:
            continue
        seen.add(idx)
        out.append({
            "idx": idx,
            "correct_idx": ci,
            "explanation": str(item.get("explanation", "") or "").strip(),
        })
    if not out:
        raise ValueError("AI javobida yaroqli natija yo'q")
    return out


def _clean_option(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[A-Ha-h]\s*[).:]\s*", "", text)
    text = re.sub(r"^(?:\*|\+|#|===|==)\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _status_code(exc: BaseException) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for name in ("status_code", "code"):
            value = getattr(obj, name, None)
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
            try:
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
    ))


def _is_network_error(exc: BaseException) -> bool:
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
    if client is None:
        return
    candidates = []
    aio = getattr(client, "aio", None)
    if aio is not None:
        candidates.extend([getattr(aio, "aclose", None), getattr(aio, "close", None)])
    candidates.extend([getattr(client, "aclose", None), getattr(client, "close", None)])
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

    schema = RESULT_SCHEMA
    name = "quiz_solution"
    for _ in range(len(keys)):
        key = keys[_groq_index % len(keys)]
        _groq_index += 1
        client = None
        try:
            await _groq_gate.wait()
            client = AsyncGroq(api_key=key)
            completion = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_completion_tokens=GROQ_MAX_OUTPUT,
                reasoning_effort="high",
                include_reasoning=False,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": schema, "strict": True},
                },
            )
            raw = completion.choices[0].message.content or ""
            data = _extract_json(raw)
            result = _normalize_results(data)
            _groq_circuit.success()
            return result, "Groq"
        except Exception as exc:
            msg = str(exc)
            if _is_rate_limit(exc):
                delay = _groq_circuit.trip(_retry_after(exc), base=30, cap=300)
                raise AIProviderError("Groq", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
            if _is_network_error(exc):
                delay = _groq_circuit.trip(base=15, cap=120)
                raise AIProviderError("Groq", f"network error; cooldown {delay:.0f}s: {msg[:160]}", retryable=True, retry_after=delay) from exc
            # Do not pretend another API key fixes a schema/model/input error.
            raise AIProviderError("Groq", f"{_status_code(exc) or ''}: {msg[:220]}", retryable=False) from exc
        finally:
            await _close_client(client)
    raise AIProviderError("Groq", "Groq credential urinishlari muvaffaqiyatsiz", retryable=True)


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

    schema = RESULT_SCHEMA
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
                    response_json_schema=schema,
                ),
            )
            data = _extract_json(response.text or "")
            result = _normalize_results(data)
            _gemini_circuit.success()
            return result, "Gemini"
        except Exception as exc:
            msg = str(exc)
            if _is_rate_limit(exc):
                delay = _gemini_circuit.trip(_retry_after(exc), base=30, cap=300)
                raise AIProviderError("Gemini", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
            if _is_network_error(exc):
                delay = _gemini_circuit.trip(base=15, cap=120)
                raise AIProviderError("Gemini", f"network error; cooldown {delay:.0f}s: {msg[:160]}", retryable=True, retry_after=delay) from exc
            raise AIProviderError("Gemini", f"{_status_code(exc) or ''}: {msg[:220]}", retryable=False) from exc
        finally:
            await _close_client(client)
    raise AIProviderError("Gemini", "Gemini credential urinishlari muvaffaqiyatsiz", retryable=True)


async def solve_text_batch(system_prompt: str, user_prompt: str) -> tuple[list[dict], str]:
    """Groq primary; Gemini is used automatically when Groq fails."""
    errors = []
    if _keys("GROQ_API_KEY", 20):
        try:
            return await _call_groq(system_prompt, user_prompt)
        except AIProviderError as exc:
            errors.append(str(exc))
    try:
        return await _call_gemini(system_prompt, user_prompt)
    except AIProviderError as exc:
        errors.append(str(exc))
    raise AIProviderError("AI", "; ".join(errors), retryable=True,
                          rate_limited=any("rate limit" in e.lower() or "cooldown" in e.lower() for e in errors))


async def solve_image(image_bytes: bytes, mime_type: str, prompt: str) -> dict:
    """Gemini Vision helper retained for existing image-question flow."""
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
                config=types.GenerateContentConfig(
                    temperature=0,
                    max_output_tokens=700,
                    response_mime_type="application/json",
                ),
            )
            data = _extract_json(response.text or "")
            if not isinstance(data, dict):
                raise ValueError("Gemini Vision javobi object emas")
            _gemini_circuit.success()
            return data
        except Exception as exc:
            msg = str(exc)
            if _is_rate_limit(exc):
                delay = _gemini_circuit.trip(_retry_after(exc), base=30, cap=300)
                raise AIProviderError("Gemini", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
            if _is_network_error(exc):
                delay = _gemini_circuit.trip(base=15, cap=120)
                raise AIProviderError("Gemini", f"network error; cooldown {delay:.0f}s: {msg[:160]}", retryable=True, retry_after=delay) from exc
            raise AIProviderError("Gemini", f"{_status_code(exc) or ''}: {msg[:220]}", retryable=False) from exc
        finally:
            await _close_client(client)
    raise AIProviderError("Gemini", "Gemini credential urinishlari muvaffaqiyatsiz", retryable=True)
