"""
Savol modeli — variantlar va to'g'ri javob uchun YAGONA manba.

Muammo (tarixan): variant "A) matn" dan label'ni bir necha joyda `split(")")` bilan
kesib olardi. Matnda qavs bo'lsa (masalan "Rinit (burun oqishi)") matn buzilar edi,
ikki marta kesilganda esa bo'sh qolib "—" placeholder chiqardi. To'g'ri javob esa
matn sifatida saqlanib, birinchi harf bo'yicha indeks deb o'qilardi.

Qoida:
  • Label (A) / B. / C: ...) faqat variant BOSHIDAN, bir marta olib tashlanadi.
  • Matn ichidagi qavs va belgilar o'zgarmaydi.
  • To'g'ri javob indeksi quyidagi tartibda aniqlanadi:
        1) correct_index (int)           — eng ishonchli
        2) correct (int)                 — indeks
        3) correct (matn)                — variant matni bo'yicha (tartibga bog'liq emas)
        4) correct (faqat harf "C", "C)") — variant tartibi bo'yicha
    Topilmasa None — jim 0 qilinmaydi.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Bitta harfli label: A) / A. / A: — variant boshida. Bundan keyingi matn o'zgarmaydi.
_LABEL_RE = re.compile(r"^\s*([A-Ja-j])\s*[\)\.:]\s*")
_LETTER_ONLY_RE = re.compile(r"^\s*([A-Ja-j])\s*[\)\.:]?\s*$")
_WS_RE = re.compile(r"\s+")
_TRAILING_MARK_RE = re.compile(r"\s*[\*✅✔✓]+\s*$")
# Telegram poll: bitta variant ≤ 100 belgi (sanitize_poll o'zi kesadi, bu yerda faqat tozalash)


def strip_label(text) -> str:
    """Boshidagi bitta 'A)' labelini olib tashlaydi. Ichki qavslarga tegmaydi."""
    s = str(text if text is not None else "")
    s = _LABEL_RE.sub("", s, count=1)
    return _WS_RE.sub(" ", s).strip()


def label_of(text) -> str | None:
    m = _LABEL_RE.match(str(text if text is not None else ""))
    return m.group(1).upper() if m else None


def _norm(s: str) -> str:
    """Solishtirish uchun normalizatsiya: kichik harf, bo'shliq, apostrof variantlari."""
    s = strip_label(s)
    s = s.lower().replace("’", "'").replace("ʻ", "'").replace("`", "'").replace("‘", "'")
    s = _TRAILING_MARK_RE.sub("", s)
    return _WS_RE.sub(" ", s).strip()


def option_texts(q: dict) -> list[str]:
    """Variant matnlari (label'siz), tartib saqlangan. Bo'sh variantlar ham qaytadi ('')."""
    out = []
    for o in (q.get("options") or []):
        out.append(strip_label(o))
    return out


def resolve_correct(q: dict) -> int | None:
    """To'g'ri javob indeksi (0-based, q['options'] tartibida) yoki None."""
    opts = option_texts(q)
    n = len(opts)
    if n == 0:
        return None

    ci = q.get("correct_index")
    if isinstance(ci, int) and 0 <= ci < n:
        return ci

    corr = q.get("correct")
    if isinstance(corr, bool):
        return None
    if isinstance(corr, int):
        return corr if 0 <= corr < n else None

    if isinstance(corr, str) and corr.strip():
        # 3) matn bo'yicha (eng ishonchli, tartibga bog'liq emas)
        target = _norm(corr)
        if target:
            hits = [i for i, o in enumerate(opts) if _norm(o) == target]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                log.warning("resolve_correct: bir xil matnli variantlar (%s) — birinchisi", hits)
                return hits[0]
        # 4) faqat harf
        m = _LETTER_ONLY_RE.match(corr)
        if m:
            idx = ord(m.group(1).upper()) - ord("A")
            if 0 <= idx < n:
                return idx
        # 4b) "C) matn" — harf + matn: matn ustuvor bo'lgani uchun yuqorida topilmagan bo'lsa,
        #     harfga tayanamiz, lekin variant matni ham mos kelishi tekshiriladi
        lbl = label_of(corr)
        if lbl:
            idx = ord(lbl) - ord("A")
            if 0 <= idx < n:
                return idx
    return None


def poll_payload(q: dict) -> tuple[list[str], int | None]:
    """Telegram poll uchun: (variant matnlari label'siz, to'g'ri javob indeksi | None).

    Bo'sh variant matni bo'lsa, u indeks tartibini buzmasligi uchun o'sha joyda
    qoldiriladi, lekin sanitize_poll uni '—' qiladi (kamdan-kam holat)."""
    texts = option_texts(q)
    ci = resolve_correct(q)
    if ci is None:
        log.error("poll_payload: to'g'ri javob aniqlanmadi (savol=%r)",
                  str(q.get("question") or q.get("text") or "")[:80])
    return texts, ci


def is_valid(q: dict) -> bool:
    """Savol saqlashga/o'ynashga yaroqlimi: matn bor, kamida 2 ta to'liq variant."""
    if not str(q.get("question") or q.get("text") or "").strip():
        return False
    texts = option_texts(q)
    return len([t for t in texts if t]) >= 2 and all(texts)


def set_correct(q: dict, index: int) -> None:
    """To'g'ri javobni HAM indeks, HAM 'X) matn' ko'rinishida yozadi (DB va aralashtirish uchun)."""
    texts = option_texts(q)
    if not (0 <= index < len(texts)):
        raise IndexError(f"set_correct: index={index}, options={len(texts)}")
    q["correct_index"] = index
    q["correct"] = f"{chr(ord('A') + index)}) {texts[index]}"
