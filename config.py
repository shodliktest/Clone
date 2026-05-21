"""⚙️ KONFIGURATSIYA — Firebase yo'q, faqat Telegram"""
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

# Yopiq Telegram kanal — bot shu kanalga admin (post + pin huquqi)
STORAGE_CHANNEL_ID:  int  = int(_s("STORAGE_CHANNEL_ID", "0"))

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
