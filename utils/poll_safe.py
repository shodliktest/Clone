"""Telegram Poll uchun xavfsiz matn/variant normalizatsiyasi."""
import re as _re

MAX_OPTIONS = 10
MAX_QUESTION = 300
MAX_OPTION = 100
MAX_EXPL = 200
MAX_MESSAGE = 4096
_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def esc(s) -> str:
    return _re.sub(r"[&<>]", lambda m: _ESC[m.group()], str(s if s is not None else ""))


def _opt_text(opt) -> str:
    s = str(opt).strip()
    return _re.sub(r"^[A-Ha-h]\s*[).:]\s*", "", s).strip()


def sanitize_poll(question, options, correct_index=0, *, true_false=False, strip_label=True):
    q = str(question if question is not None else "").strip() or "Savol"
    q = _truncate_tg(esc(q), MAX_QUESTION)
    if true_false:
        ci = 0 if correct_index in (0, "0", None) else (0 if str(correct_index).lower().startswith("ha") else 1)
        return q, ["Ha", "Yo'q"], ci
    cleaned=[]
    for o in (options or []):
        t = _opt_text(o) if strip_label else str(o).strip()
        cleaned.append(_truncate_tg(esc(t or "—"), MAX_OPTION))
    while len(cleaned)<2:
        cleaned.append("—")
    try: ci=int(correct_index)
    except (TypeError,ValueError): ci=0
    if len(cleaned)>MAX_OPTIONS:
        if 0 <= ci < len(cleaned) and ci >= MAX_OPTIONS:
            cleaned=cleaned[:MAX_OPTIONS-1]+[cleaned[ci]]; ci=MAX_OPTIONS-1
        else:
            cleaned=cleaned[:MAX_OPTIONS]
    ci=max(0,min(ci,len(cleaned)-1))
    return q, cleaned, ci


def sanitize_explanation(expl):
    if not expl: return None
    if str(expl).strip() in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"): return None
    return _truncate_tg(esc(expl), MAX_EXPL)


def _tg_len(text: str) -> int:
    # Telegram Bot API limitlari UTF-16 code unit bilan hisoblanadi.
    return len(str(text).encode("utf-16-le")) // 2


def _truncate_tg(text: str, limit: int) -> str:
    text = str(text)
    if _tg_len(text) <= limit:
        return text
    out=[]; units=0
    for ch in text:
        u=_tg_len(ch)
        if units + u > limit:
            break
        out.append(ch); units += u
    return "".join(out)


def _split_text_4096(text: str):
    """HTML-escaped textni Telegram 4096 UTF-16 limitidan oshirmasdan bo'ladi."""
    if _tg_len(text) <= MAX_MESSAGE: return [text]
    parts=[]; rest=text
    while _tg_len(rest) > MAX_MESSAGE:
        # Avval limit ichidagi eng yaqin newline/space ni topamiz.
        probe=_truncate_tg(rest, MAX_MESSAGE)
        cut=probe.rfind("\n")
        if cut < 1000: cut=probe.rfind(" ")
        if cut < 1: cut=len(probe)
        parts.append(rest[:cut].rstrip())
        rest=rest[cut:].lstrip()
    if rest: parts.append(rest)
    return parts


def needs_question_split(question: str, header: str = "") -> bool:
    # Telegram parse_mode HTML bo'lgani uchun real yuboriladigan escaped uzunlikni tekshiramiz.
    return _tg_len(esc(str(header or "") + str(question or "").strip())) > MAX_QUESTION

QUESTION_SPLIT_LABEL = "👆 Yuqoridagi savolga javob bering"

def split_long_question(question: str, header: str = ""):
    """(full_messages_or_None, poll_question) qaytaradi.

    full_messages — uzun savol 4096 dan ham oshsa bir nechta oddiy xabar;
    poll_question esa doim <=300 belgi. Shunday qilib variantlar har doim
    alohida Telegram Quiz Poll ichida qoladi.
    """
    q=str(question if question is not None else "").strip() or "Savol"
    escaped_full=esc(str(header or "") + q)
    if _tg_len(escaped_full) <= MAX_QUESTION:
        return None, escaped_full
    full_messages=_split_text_4096(escaped_full)
    poll_q=_truncate_tg(esc(str(header or "") + QUESTION_SPLIT_LABEL), MAX_QUESTION)
    return full_messages, poll_q
