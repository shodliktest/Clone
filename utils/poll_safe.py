"""
🛡 POLL XAVFSIZLIGI — Telegram sendPoll cheklovlarini bir joyda kafolatlaydi.

Telegram sendPoll qoidalari:
  • question  : 1..300 belgi, bo'sh bo'lmasligi shart
  • options   : 2..10 ta, har biri 1..100 belgi, bo'sh bo'lmasligi shart
  • explanation: 0..200 belgi

Bot default parse_mode=HTML bo'lgani uchun question/explanation HTML sifatida
tahlil qilinadi — shu sbabli matndagi "<", ">", "&" belgilari
"can't parse entities: Unsupported start tag" xatosini beradi.
Bu yerda ularni HTML-escape qilamiz, demak parse_mode versiyasiga bog'liq
bo'lmagan, barqaror yechim bo'ladi.
"""
import re as _re

MAX_OPTIONS = 10            # Telegram limiti
MAX_QUESTION = 300
MAX_OPTION = 100
MAX_EXPL = 200

_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def esc(s) -> str:
    """HTML uchun xavfsiz qiladi ('&' birinchi bo'lishi shart)."""
    return _re.sub(r"[&<>]", lambda m: _ESC[m.group()], str(s if s is not None else ""))


def _opt_text(opt) -> str:
    """'A) matn' ko'rinishidan toza variant matnini ajratib oladi."""
    s = str(opt)
    s = s.split(")", 1)[-1].strip() if ")" in s else s.strip()
    return s


def sanitize_poll(question, options, correct_index=0,
                  *, true_false=False, strip_label=True):
    """
    Telegram sendPoll uchun kafolatlangan xavfsiz qiymatlarni qaytaradi.

    Qaytaradi: (question_text, options_list, correct_index)
    Barcha matnlar HTML-escape qilingan, bo'sh emas, cheklovlarga mos.
    To'g'ri javob variantini 10 talik oynadan tashqarida qolib ketmaydi.
    """
    # ── Savol matni ──
    q = str(question if question is not None else "").strip()
    if not q:
        q = "Savol"
    q = esc(q)[:MAX_QUESTION]

    # ── Variantlar ──
    if true_false:
        return q, ["Ha", "Yo'q"], (0 if correct_index in (0, "0", None) else
                                   (0 if str(correct_index).lower().startswith("ha") else 1))

    cleaned = []
    for o in (options or []):
        t = _opt_text(o) if strip_label else str(o).strip()
        if not t:
            t = "—"                       # hech qachon bo'sh bo'lmasin
        cleaned.append(esc(t)[:MAX_OPTION])

    # Kamida 2 ta variant bo'lishi shart
    while len(cleaned) < 2:
        cleaned.append("—")

    # To'g'ri javob indeksi
    try:
        ci = int(correct_index)
    except (TypeError, ValueError):
        ci = 0

    # 10 tadan ortiq bo'lsa — to'g'ri javobni saqlab qolib kesamiz
    if len(cleaned) > MAX_OPTIONS:
        if 0 <= ci < len(cleaned) and ci >= MAX_OPTIONS:
            cleaned = cleaned[:MAX_OPTIONS - 1] + [cleaned[ci]]
            ci = MAX_OPTIONS - 1
        else:
            cleaned = cleaned[:MAX_OPTIONS]

    ci = max(0, min(ci, len(cleaned) - 1))
    return q, cleaned, ci


def sanitize_explanation(expl):
    """Izohni xavfsiz qiladi yoki None qaytaradi."""
    if not expl:
        return None
    if str(expl).strip() in ("Izoh kiritilmagan.", "Izoh yo'q", "Izoh kiritilmagan"):
        return None
    return esc(expl)[:MAX_EXPL]
