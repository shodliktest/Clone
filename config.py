"""⚙️ KONFIGURATSIYA — Supabase (Postgres) asosiy baza"""
import os

def _s(key, default=None):
    try:
        import streamlit as st
        if "." in key:
            sec, sub = key.split(".", 1)
            return st.secrets[sec][sub]
        return st.secrets[key]
    except Exception:
        return os.environ.get(key.replace(".", "_").upper(), default)

BOT_TOKEN:           str  = _s("BOT_TOKEN", "")
_raw                      = str(_s("ADMIN_IDS", "123456789"))
ADMIN_IDS:           list = [int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()]
ADMIN_PASSWORD:      str  = _s("ADMIN_PASSWORD", "admin123")
ADMIN_USERNAME:      str  = _s("ADMIN_USERNAME", "Shodlikai")

# ── Supabase — asosiy ma'lumotlar bazasi ────────────────────────
SUPABASE_URL: str = _s("SUPABASE_URL", "")
SUPABASE_KEY: str = _s("SUPABASE_KEY", "")   # service_role kalit (Project Settings → API)

# ── Eski Telegram Storage Channel — endi ISHLATILMAYDI,
#    lekin orqaga moslik (eski kodlar import qilsa xato bermasligi) uchun qoldirildi
STORAGE_CHANNEL_ID:  int  = int(_s("STORAGE_CHANNEL_ID", "0"))

# Streamlit app URL — sayt bilan integratsiya uchun
STREAMLIT_URL: str = _s("STREAMLIT_URL", "https://quizmakerbot-hwttylmp5igdczywefchjt.streamlit.app")

# GitHub Pages URL — edit.html sahifasi uchun
GITHUB_PAGES_URL: str = _s("GITHUB_PAGES_URL", "https://shodliktest.github.io/TestPro")

# Test Baza Guruhi — har yangi test shu guruhga e'lon qilinadi
BAZA_GROUP_ID: int = int(_s("BAZA_GROUP_ID", "0"))

# ── Statistika kanali (xatolar va batafsil tahlil JSON fayllari) ─────────────
# Bot test tugagach shu kanalga JSON yozadi; Supabase'da faqat indeks qatorlari turadi.
# Bot kanalda ADMIN bo'lishi shart (xabar yuborish va tahrirlash huquqi bilan).
# Secret nomi: STATISTIKA_ID  (kanal ID si, masalan -1001234567890)
def _int_secret(*keys, default=0):
    for k in keys:
        try:
            v = str(_s(k, "") or "").strip()
            if v:
                return int(v)
        except Exception:
            continue
    return default

STATS_CHANNEL_ID: int = _int_secret("STATISTIKA_ID", "STATISTIKA_CHANNEL_ID", "STATS_CHANNEL_ID",
                                    "USER_FALSE_ID", "User_false_id", "USER_FALSE_CHANNEL_ID")
USER_FALSE_ID: int = STATS_CHANNEL_ID          # eski nom (moslik uchun)

# ── Testlar kanali (test JSON arxivi) ────────────────────────────────────────
# Har test (meta + savollar) shu kanalga JSON qilib yoziladi. ARCHIVE_AFTER_DAYS kun hech kim
# ochmagan test Supabase'dan "sovutiladi" (savollari olinadi, meta va indeks qoladi) va
# qayta murojaatda shu kanaldan tiklanadi. Bot kanalda ADMIN bo'lishi shart.
# Secret nomi: TESTLAR_ID  (kanal ID si, masalan -1001234567890)
TESTS_CHANNEL_ID: int = _int_secret("TESTLAR_ID", "TESTS_CHANNEL_ID", "TESTLAR_CHANNEL_ID")
ARCHIVE_AFTER_DAYS: int = _int_secret("ARCHIVE_AFTER_DAYS", default=14)
MAX_ANALYSIS_PER_USER_TG: int = _int_secret("MAX_ANALYSIS_PER_USER", default=30)

PASSING_SCORE = 60
MAX_FILE_MB   = 20

SUBJECTS = [
    "Matematika","Fizika","Kimyo","Biologiya","Tarix","Geografiya",
    "Ingliz tili","Rus tili","Ona tili","Informatika","Adabiyot",
    "Huquq","Iqtisodiyot","Boshqa",
]
DIFFICULTY_LEVELS = {
    "easy":   "🟢 Oson",
    "medium": "🟡 O'rtacha",
    "hard":   "🔴 Qiyin",
    "expert": "⚡ Ekspert",
}

