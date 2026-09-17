"""AI engine: Groq primary, Gemini fallback, plus explicit format repair.

IMPORTANT: format repair is NEVER called by the parser automatically.  The
handler calls repair_questions_from_text only after the user presses the
"AI bilan formatni tuzatish" inline button.
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
    out: list[str] = []
    for name in names:
        value = str(sec.get(name, "") or "").strip()
        if value and len(value) > 10 and value not in out:
            out.append(value)
    return out


GROQ_MODEL = os.getenv("GROQ_AI_MODEL", "openai/gpt-oss-120b")
GROQ_MIN_INTERVAL = float(os.getenv("GROQ_AI_MIN_INTERVAL", "3.0"))
GROQ_MAX_OUTPUT = int(os.getenv("GROQ_AI_MAX_OUTPUT", "5000"))

GEMINI_MODEL = os.getenv("GEMINI_AI_MODEL", "gemini-3.6-flash")
GEMINI_MIN_INTERVAL = float(os.getenv("GEMINI_AI_MIN_INTERVAL", "3.0"))
GEMINI_MAX_OUTPUT = int(os.getenv("GEMINI_AI_MAX_OUTPUT", "5000"))

REPAIR_CHUNK_CHARS = int(os.getenv("AI_REPAIR_CHUNK_CHARS", "70000"))

_groq_gate = _RateGate(GROQ_MIN_INTERVAL)
_gemini_gate = _RateGate(GEMINI_MIN_INTERVAL)
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

REPAIR_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["question", "options"],
    "additionalProperties": False,
}
REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": REPAIR_ITEM_SCHEMA}},
    "required": ["questions"],
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
        # Fallback faqat SDK structured-output bo'lmagan javoblar uchun.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1])
        raise


def _normalize_results(data: Any) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("results")
    if not isinstance(data, list):
        raise ValueError("AI javobida results array yo'q")
    result = []
    for item in data:
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
        raise ValueError("AI javobida yaroqli natija yo'q")
    return result


def _strip_option_label(value: str) -> str:
    value = re.sub(r"^\s*(?:[A-Ha-h]|\d{1,2})\s*[\).:\-]\s*", "", value)
    return value.strip()


def _normalize_repair(data: Any) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("questions")
    if not isinstance(data, list):
        raise ValueError("AI repair javobida questions array yo'q")
    out = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "") or "").strip()
        raw_opts = item.get("options")
        if len(q) < 2 or not isinstance(raw_opts, list):
            continue
        opts: list[str] = []
        for raw in raw_opts:
            value = _strip_option_label(str(raw or ""))
            if value and value not in opts:
                opts.append(value)
        # Repair is MCQ-only. Preserve the number of recoverable choices
        # (the bot parser accepts 2+ options); never invent a missing choice.
        if len(opts) < 2 or len(opts) > 8:
            continue
        key = re.sub(r"\s+", " ", q).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "type": "multiple_choice",
            "question": q,
            "options": opts,
            "correct": "",
            "_marked": False,
            "_ai_repaired": True,
        })
    if not out:
        raise ValueError("AI repair yaroqli variantli savol qaytarmadi")
    return out


def _status_code(exc: BaseException) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for attr in ("status_code", "code"):
            value = getattr(obj, attr, None)
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
        for attr in ("retry_after", "retry_after_seconds"):
            value = getattr(obj, attr, None)
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
    status = _status_code(exc)
    if status == 429:
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
            pass


async def _call_groq(system_prompt: str, user_prompt: str, schema: dict) -> tuple[Any, str]:
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
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "quiz_response", "strict": True, "schema": schema},
            },
        )
        content = completion.choices[0].message.content or ""
        data = _json_text(content)
        _groq_circuit.success()
        return data, "Groq"
    except Exception as exc:
        msg = str(exc)
        if _is_rate_limit(exc):
            delay = _groq_circuit.trip(_retry_after(exc), base=30, cap=300)
            raise AIProviderError("Groq", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
        if _is_network_error(exc):
            delay = _groq_circuit.trip(base=15, cap=120)
            raise AIProviderError("Groq", f"network error; cooldown {delay:.0f}s: {msg[:180]}", retry_after=delay) from exc
        raise AIProviderError("Groq", f"{_status_code(exc) or ''}: {msg[:240]}", retryable=False) from exc
    finally:
        await _close_client(client)


async def _call_gemini(system_prompt: str, user_prompt: str, schema: dict) -> tuple[Any, str]:
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
        data = _json_text(response.text or "")
        _gemini_circuit.success()
        return data, "Gemini"
    except Exception as exc:
        msg = str(exc)
        if _is_rate_limit(exc):
            delay = _gemini_circuit.trip(_retry_after(exc), base=30, cap=300)
            raise AIProviderError("Gemini", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
        if _is_network_error(exc):
            delay = _gemini_circuit.trip(base=15, cap=120)
            raise AIProviderError("Gemini", f"network error; cooldown {delay:.0f}s: {msg[:180]}", retry_after=delay) from exc
        raise AIProviderError("Gemini", f"{_status_code(exc) or ''}: {msg[:240]}", retryable=False) from exc
    finally:
        await _close_client(client)


async def solve_text_batch(system_prompt: str, user_prompt: str) -> tuple[list[dict], str]:
    """Groq primary -> Gemini fallback for answer solving."""
    errors = []
    if _keys("GROQ_API_KEY", 20):
        try:
            data, provider = await _call_groq(system_prompt, user_prompt, RESULT_SCHEMA)
            return _normalize_results(data), provider
        except AIProviderError as exc:
            errors.append(str(exc))
    try:
        data, provider = await _call_gemini(system_prompt, user_prompt, RESULT_SCHEMA)
        return _normalize_results(data), provider
    except AIProviderError as exc:
        errors.append(str(exc))
    raise AIProviderError("AI", "; ".join(errors), retryable=True,
                          rate_limited=any("rate limit" in x.lower() or "cooldown" in x.lower() for x in errors))


def _chunk_text(text: str, max_chars: int = REPAIR_CHUNK_CHARS) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            cut = text.rfind("\n\n", start, end)
            if cut < start + max_chars // 2:
                cut = text.rfind("\n", start, end)
            if cut > start:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


_REPAIR_SYSTEM = (
    "Siz test faylini FORMAT REPAIR qiluvchi tizimsiz. "
    "Sizning vazifangiz faqat xom matndan savol va uning variantlarini ajratish. "
    "TO'G'RI JAVOBNI ANIQLAMANG VA BELGILAMANG. "
    "Matnda nechta haqiqiy variant bo'lsa, o'sha variantlarni saqlang (kamida 2 ta). "
    "Yetishmayotgan variantni o'ylab topmang. "
    "Variant matnlarini original mazmunni saqlagan holda tozalang. "
    "Savol yoki variantni o'ylab topmang; matnda aniq tiklab bo'lmasa, o'sha savolni tashlang. "
    "Natija faqat berilgan JSON schema bo'yicha bo'lsin."
)


async def repair_questions_from_text(text: str) -> tuple[list[dict], str]:
    """Explicitly invoked format repair; never used by parse_file()."""
    chunks = _chunk_text(text)
    if not chunks:
        raise AIProviderError("AI", "Xom matn bo'sh")

    all_questions: list[dict] = []
    providers: list[str] = []
    errors: list[str] = []
    for n, chunk in enumerate(chunks, 1):
        user_prompt = (
            f"Bu {n}/{len(chunks)} qism. Xom test matnini botning MCQ formatiga keltiring. "
            "Hech qaysi variantni to'g'ri deb belgilamang. Savol + matnda mavjud haqiqiy variantlarni qaytaring.\n\n"
            + chunk
        )
        try:
            # Gemini is preferred for repair because it is the dedicated fallback
            # provider in this flow; Groq is used only if Gemini fails.
            data, provider = await _call_gemini(_REPAIR_SYSTEM, user_prompt, REPAIR_SCHEMA)
            repaired = _normalize_repair(data)
        except AIProviderError as gem_exc:
            errors.append(str(gem_exc))
            try:
                data, provider = await _call_groq(_REPAIR_SYSTEM, user_prompt, REPAIR_SCHEMA)
                repaired = _normalize_repair(data)
            except AIProviderError as groq_exc:
                errors.append(str(groq_exc))
                raise AIProviderError("AI", f"chunk {n}: {gem_exc}; {groq_exc}", retryable=True) from groq_exc
        all_questions.extend(repaired)
        providers.append(provider)

    # De-duplicate questions after chunking.
    unique: list[dict] = []
    seen: set[str] = set()
    for q in all_questions:
        key = re.sub(r"\s+", " ", q["question"]).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    if not unique:
        raise AIProviderError("AI", "; ".join(errors) or "AI repair natija bermadi", retryable=True)
    provider_label = providers[0] if len(set(providers)) == 1 else "Gemini/Groq"
    return unique, provider_label


async def solve_image(image_bytes: bytes, mime_type: str, prompt: str) -> dict:
    """Existing Gemini vision path retained for compatibility."""
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
    key = keys[_gemini_index % len(keys)]
    _gemini_index += 1
    client = None
    try:
        await _gemini_gate.wait()
        client = genai.Client(api_key=key)
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=800,
                response_mime_type="application/json",
            ),
        )
        data = _json_text(response.text or "")
        if not isinstance(data, dict):
            raise ValueError("Gemini vision javobi object emas")
        _gemini_circuit.success()
        return data
    except Exception as exc:
        msg = str(exc)
        if _is_rate_limit(exc):
            delay = _gemini_circuit.trip(_retry_after(exc), base=30, cap=300)
            raise AIProviderError("Gemini", f"rate limit; cooldown {delay:.0f}s", rate_limited=True, retry_after=delay) from exc
        if _is_network_error(exc):
            delay = _gemini_circuit.trip(base=15, cap=120)
            raise AIProviderError("Gemini", f"network error; cooldown {delay:.0f}s: {msg[:180]}", retry_after=delay) from exc
        raise AIProviderError("Gemini", f"{_status_code(exc) or ''}: {msg[:240]}", retryable=False) from exc
    finally:
        await _close_client(client)
