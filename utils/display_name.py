"""Foydalanuvchi ismini ko'rsatish uchun yagona qoida (reyting, lobby, natijalar).

Qoida:
  1. first_name ma'noli bo'lsa — shu ism ishlatiladi (familiya bo'lsa, qo'shiladi).
  2. first_name yaroqsiz bo'lsa (faqat emoji, nuqta, ko'rinmas "ㅤ" belgisi) —
     familiya (last_name) ishlatiladi.
  3. Ikkalasi ham yaroqsiz bo'lsa — username, undan keyin "NoName".

Tozalash NFKC normalizatsiya bilan bajariladi: "𝓢𝓱𝓸𝓭𝓲𝓴" kabi fancy yozuvlar
oddiy harflarga aylanadi (eski tozalagich ularni butunlay o'chirib, "NoName"
chiqarardi). Emoji va BMP'dan tashqari belgilar olib tashlanadi.
"""
import unicodedata

FALLBACK = "NoName"

# Ko'rinmas "to'ldiruvchi" belgilar — ism o'rniga yozib qo'yilgan bo'lishi mumkin
_FILLERS = frozenset("ᅟᅠㅤﾠ​‌‍⁠﻿")


def clean_text(text, max_len=None) -> str:
    """Emoji, nazorat va ko'rinmas belgilarni olib tashlaydi; bo'shliqlarni yig'adi."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    kept = []
    for ch in s:
        if ch in _FILLERS or ord(ch) >= 0x10000:
            continue
        if unicodedata.category(ch).startswith(("L", "N", "P", "Z")):
            kept.append(ch)
    out = " ".join("".join(kept).split())
    return _trim(out, max_len)


def has_letters(text) -> bool:
    """Matnda kamida bitta harf bormi (faqat nuqta/belgi bo'lsa — False)."""
    return any(ch.isalpha() and ch not in _FILLERS for ch in str(text or ""))


def display_name(first, last="", username="", max_len=25) -> str:
    """Ism, familiya va username'dan ko'rsatiladigan nomni qaytaradi."""
    f = clean_text(first)
    l = clean_text(last)
    u = clean_text(username)
    if has_letters(f):
        full = f"{f} {l}" if has_letters(l) else f
    elif has_letters(l):
        full = l                       # ism yo'q — familiyani olamiz
    elif has_letters(u):
        full = u
    else:
        return FALLBACK
    return _trim(full, max_len)


def user_display_name(user, max_len=25) -> str:
    """aiogram User (yoki shunga o'xshash obyekt) uchun display_name."""
    if user is None:
        return FALLBACK
    return display_name(
        getattr(user, "first_name", "") or "",
        getattr(user, "last_name", "") or "",
        getattr(user, "username", "") or "",
        max_len=max_len,
    )


def _trim(s: str, max_len) -> str:
    if max_len and len(s) > max_len:
        return s[:max_len].rstrip() + "…"
    return s
