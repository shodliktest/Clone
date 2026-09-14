"""Provider-aware AI engine for quiz solving.

Groq is the primary text solver; Gemini (google-genai) is an independent
fallback. Rate limiting is provider-wide (organization/project), not key-wide.
"""
from __future__ import annotations

import asyncio
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

GEMINI_MODEL = os.getenv("GEMINI_AI_MODEL", "gemini-2.5-flash")
GEMINI_MIN_INTERVAL = float(os.getenv("GEMINI_AI_MIN_INTERVAL", "7.0"))
GEMINI_MAX_OUTPUT = int(os.getenv("GEMINI_AI_MAX_OUTPUT", "600"))

_groq_gate = _RateGate(GROQ_MIN_INTERVAL)
_gemini_gate = _RateGate(GEMINI_MIN_INTERVAL)
_groq_index = 0
_gemini_index = 0


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


async def solve_text_batch(system_prompt: str, user_prompt: str) -> tuple[list[dict], str]:
    """Groq -> Gemini fallback. Other legacy providers remain outside this engine."""
    global _groq_index, _gemini_index

    groq_keys = _keys("GROQ_API_KEY", 20)
    gemini_keys = _keys("GEMINI_API_KEY", 20)
    errors = []

    # Primary: official Groq SDK. Key rotation is only for credential rotation;
    # Groq quotas are organization-level, so it is NOT treated as extra quota.
    if groq_keys:
        try:
            from groq import AsyncGroq
        except Exception as exc:
            errors.append(f"Groq SDK missing: {exc}")
        else:
            for _ in range(len(groq_keys)):
                key = groq_keys[_groq_index % len(groq_keys)]
                _groq_index += 1
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
                        include_reasoning=False,
                    )
                    text = completion.choices[0].message.content or ""
                    return _normalize(_json_text(text)), "Groq"
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    msg = str(exc)
                    is_rate = status == 429 or "rate limit" in msg.lower() or "quota" in msg.lower()
                    errors.append(f"Groq {status or ''}: {msg[:180]}")
                    if not is_rate:
                        # Bad request/model/schema errors should not burn all keys.
                        break

    # Dedicated Gemini fallback via the current official google-genai SDK.
    if gemini_keys:
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            errors.append(f"Gemini SDK missing: {exc}")
        else:
            for _ in range(len(gemini_keys)):
                key = gemini_keys[_gemini_index % len(gemini_keys)]
                _gemini_index += 1
                try:
                    await _gemini_gate.wait()
                    client = genai.Client(api_key=key)
                    config = types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0,
                        max_output_tokens=GEMINI_MAX_OUTPUT,
                        response_mime_type="application/json",
                    )
                    response = await client.aio.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=user_prompt,
                        config=config,
                    )
                    text = response.text or ""
                    return _normalize(_json_text(text)), "Gemini"
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    msg = str(exc)
                    is_rate = code == 429 or "429" in msg or "resource exhausted" in msg.lower() or "quota" in msg.lower()
                    errors.append(f"Gemini {code or ''}: {msg[:180]}")
                    if not is_rate:
                        break

    raise AIProviderError(
        "AI",
        "; ".join(errors) if errors else "GROQ_API_KEY/GEMINI_API_KEY topilmadi",
        retryable=True,
        rate_limited=bool(errors),
    )


async def solve_image(image_bytes: bytes, mime_type: str, prompt: str) -> dict:
    """Gemini multimodal solver using the official google-genai SDK."""
    global _gemini_index
    keys = _keys("GEMINI_API_KEY", 20)
    if not keys:
        raise AIProviderError("Gemini", "GEMINI_API_KEY topilmadi", retryable=False)

    from google import genai
    from google.genai import types

    errors = []
    for _ in range(len(keys)):
        key = keys[_gemini_index % len(keys)]
        _gemini_index += 1
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
                    max_output_tokens=400,
                    response_mime_type="application/json",
                ),
            )
            data = _json_text(response.text or "")
            if not isinstance(data, dict):
                raise ValueError("Gemini vision javobi object emas")
            return data
        except Exception as exc:
            code = getattr(exc, "code", None)
            msg = str(exc)
            errors.append(f"Gemini {code or ''}: {msg[:180]}")
            is_rate = code == 429 or "429" in msg or "resource exhausted" in msg.lower() or "quota" in msg.lower()
            if not is_rate:
                break
    raise AIProviderError("Gemini", "; ".join(errors), rate_limited=True)
