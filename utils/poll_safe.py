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


# ──────────────────────────────────────────────────────────────────
# UZUN SAVOLLARNI BO'LISH
# ──────────────────────────────────────────────────────────────────
# Telegram sendPoll question maydoni 300 belgi bilan cheklangan. Savol
# matni shundan uzun bo'lsa, kesib "..." qo'yish o'rniga — savolni
# ALOHIDA oddiy xabar qilib to'liq yuboramiz, keyin quiz'ni qisqa
# sarlavha bilan ("👆 Savolga qarang") yuboramiz. Shu tartibda:
# avval to'liq savol matni, keyin variantlar bilan poll keladi.

QUESTION_SPLIT_LABEL = "👆 Yuqoridagi savolga javob bering"


def needs_question_split(question: str, header: str = "") -> bool:
    """header+question MAX_QUESTION dan uzunmi — bo'lish kerakligini bildiradi."""
    q = str(question if question is not None else "").strip()
    return len(header) + len(q) > MAX_QUESTION


def split_long_question(question: str, header: str = ""):
    """
    Savol matnini poll uchun tayyorlaydi.

    Qaytaradi: (full_text_or_None, poll_question)
      • full_text_or_None: agar bo'lish kerak bo'lsa — savolning TO'LIQ matni
        (header bilan), buni chaqiruvchi tomon oldindan oddiy xabar sifatida
        yuborishi kerak. Bo'lish kerak bo'lmasa — None.
      • poll_question: sendPoll uchun ishlatiladigan matn (har doim
        MAX_QUESTION ichida, bo'sh emas).
    """
    q = str(question if question is not None else "").strip()
    if not q:
        q = "Savol"

    if not needs_question_split(q, header):
        return None, esc(header + q)[:MAX_QUESTION]

    full_text = esc(header + q)
    return full_text, esc(header + QUESTION_SPLIT_LABEL)[:MAX_QUESTION]
