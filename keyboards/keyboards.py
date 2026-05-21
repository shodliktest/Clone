"""⌨️ BARCHA KLAVIATURALAR"""
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                            ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import SUBJECTS

COLORS = ["🔵","🟣","🟢","🔴","🟡","🟠","⚪","⚫","🔷","🔶"]
CAT_ICONS = {
    # O'zbekcha nomlar (botda yaratilgan testlar)
    "Matematika":   "🧮",
    "Fizika":       "⚡",
    "Kimyo":        "⚗️",
    "Biologiya":    "🧬",
    "Tarix":        "🏛️",
    "Geografiya":   "🌍",
    "Ingliz tili":  "🇬🇧",
    "Rus tili":     "🇷🇺",
    "Ona tili":     "🇺🇿",
    "Informatika":  "💻",
    "Adabiyot":     "✍️",
    "Huquq":        "⚖️",
    "Iqtisodiyot":  "📈",
    "Sport":        "⚽",
    "Din":          "📖",
    "Boshqa":       "📚",

    # Inglizcha kalitlar (saytdan yaratilgan testlar)
    "english":      "🇬🇧",
    "russian":      "🇷🇺",
    "uzbek":        "🇺🇿",
    "arabic":       "🕌",
    "turkish":      "🇹🇷",
    "korean":       "🇰🇷",
    "german":       "🇩🇪",
    "french":       "🇫🇷",
    "chinese":      "🇨🇳",
    "math":         "🧮",
    "mathematics":  "🧮",
    "physics":      "⚡",
    "chemistry":    "⚗️",
    "biology":      "🧬",
    "history":      "🏛️",
    "geography":    "🌍",
    "it":           "💻",
    "informatika":  "💻",
    "literature":   "✍️",
    "science":      "🔬",
    "religion":     "📖",
    "sport":        "⚽",
    "economics":    "📈",
    "law":          "⚖️",
    "other":        "📚",
}


def get_cat_icon(category: str) -> str:
    """
    Kategoriya nomiga mos emoji qaytaradi.
    O'zbekcha yoki inglizcha, katta-kichik harfdan qat'i nazar.
    Topilmasa — 📚
    """
    if not category:
        return "📚"
    # To'g'ridan qidirish
    icon = CAT_ICONS.get(category)
    if icon:
        return icon
    # Kichik harf bilan
    low = category.lower().strip()
    icon = CAT_ICONS.get(low)
    if icon:
        return icon
    # Qisman moslik (masalan "Ingliz tili (B2)" → "Ingliz tili")
    for key, val in CAT_ICONS.items():
        if key.lower() in low or low in key.lower():
            return val
    return "📚"
DIFFICULTY_LEVELS = {
    "easy":"🟢 Oson","medium":"🟡 O'rtacha","hard":"🔴 Qiyin","expert":"⚡ Ekspert",
}

def main_kb(uid=None, chat_type="private"):
    if chat_type != "private":
        return ReplyKeyboardRemove()
    kb = [
        [KeyboardButton(text="📚 Testlar"),          KeyboardButton(text="➕ Test Yaratish")],
        [KeyboardButton(text="📊 Natijalarim"),       KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="🗂 Mening testlarim"),  KeyboardButton(text="👥 Referallarim")],
        [KeyboardButton(text="👤 Profil"),            KeyboardButton(text="ℹ️ Yordam")],
    ]
    if uid:
        from config import ADMIN_IDS
        if uid in ADMIN_IDS:
            kb.append([
                KeyboardButton(text="👑 Admin Panel"),
                KeyboardButton(text="⚙️ Sozlamalar"),
            ])
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        persistent=True,
        is_persistent=True,
    )


# ── Test kartochkasi (katalogda) ──────────────────────────────
def test_info_kb(tid, creator_id=None, viewer_uid=None, back_cb="back_to_cats"):
    from utils.ram_cache import get_test_meta
    from config import ADMIN_IDS
    b      = InlineKeyboardBuilder()
    meta   = get_test_meta(tid)
    paused = meta.get("is_paused", False)
    is_own = viewer_uid and (viewer_uid == creator_id or viewer_uid in ADMIN_IDS)

    if paused:
        b.row(InlineKeyboardButton(text="⚠️ Vaqtincha to'xtatilgan", callback_data="noop"))
        if is_own:
            b.row(InlineKeyboardButton(text="▶️ Qayta boshlash", callback_data=f"test_resume_{tid}"))
    else:
        b.row(
            InlineKeyboardButton(text="▶️ Inline test", callback_data=f"start_test_{tid}"),
            InlineKeyboardButton(text="📊 Quiz Poll",   callback_data=f"start_poll_{tid}"),
        )
    b.row(InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"test_{tid}"))
    if is_own and not paused:
        b.row(
            InlineKeyboardButton(text="⏸ To'xtatib qo'yish", callback_data=f"test_pause_{tid}"),
            InlineKeyboardButton(text="📊 Kim yechgan",       callback_data=f"test_solvers_{tid}_0"),
        )
    b.row(
        InlineKeyboardButton(text="🏆 Reyting", callback_data=f"lb_test_{tid}"),
        InlineKeyboardButton(text="⬅️ Orqaga",  callback_data=back_cb),
    )
    return b.as_markup()


def test_created_kb(tid, bot_username=""):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Boshlash",  callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Quiz Poll", callback_data=f"start_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))
    return b.as_markup()


def result_kb(tid, rid):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Batafsil tahlil", callback_data=f"analysis_{rid}_0"))
    b.row(
        InlineKeyboardButton(text="🔄 Qaytadan",  callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Quiz Poll", callback_data=f"start_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📤 Ulashish",    switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    return b.as_markup()


def analysis_kb(rid, page, total):
    b   = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"analysis_{rid}_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="noop"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"analysis_{rid}_{page+1}"))
    b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Natijaga", callback_data=f"res_back_{rid}"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    return b.as_markup()



def answer_kb(letters):
    """Inline test javob tugmalari"""
    b = InlineKeyboardBuilder()
    for i, l in enumerate(letters):
        icon = COLORS[i] if i < len(COLORS) else "▫️"
        b.add(InlineKeyboardButton(text=f"{icon} {l}", callback_data=f"ans_{l}"))
    b.adjust(len(letters))
    return b.as_markup()

def poll_pause_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="▶️ Davom etish",     callback_data="resume_poll"))
    b.row(InlineKeyboardButton(text="❌ Testni yakunlash", callback_data="cancel_poll"))
    return b.as_markup()

def inline_pause_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="▶️ Davom etish",     callback_data="resume_inline"))
    b.row(InlineKeyboardButton(text="❌ Testni yakunlash", callback_data="cancel_test"))
    return b.as_markup()


def admin_kb():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="👥 Userlar",    callback_data="admin_users"),
        InlineKeyboardButton(text="📋 Testlar",    callback_data="admin_tests"),
    )
    b.row(
        InlineKeyboardButton(text="📈 Statistika", callback_data="admin_stats"),
        InlineKeyboardButton(text="📢 Broadcast",  callback_data="admin_broadcast"),
    )
    b.row(
        InlineKeyboardButton(text="📣 Guruh E'lon",    callback_data="admin_group_broadcast"),
        InlineKeyboardButton(text="🗑 O'chirilganlar", callback_data="admin_deleted_tests"),
    )
    b.row(
        InlineKeyboardButton(text="⚡ RAM → TG", callback_data="adm_flush"),
        InlineKeyboardButton(text="🔄 TG → RAM", callback_data="adm_refresh"),
    )
    b.row(
        InlineKeyboardButton(text="💾 JSON export", callback_data="adm_export_json"),
        InlineKeyboardButton(text="🗂 Backuplar",   callback_data="adm_backups"),
    )
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    return b.as_markup()


def subject_kb(extra_subjects=None):
    """Fan tanlash — user maxsus fanlari birinchi ko'rsatiladi"""
    b    = InlineKeyboardBuilder()
    seen = set()
    if extra_subjects:
        for s in extra_subjects:
            if s not in seen and s not in SUBJECTS:
                b.add(InlineKeyboardButton(text=f"⭐ {s}", callback_data=f"subj_{s}"))
                seen.add(s)
    for s in SUBJECTS:
        if s not in seen:
            b.add(InlineKeyboardButton(text=s, callback_data=f"subj_{s}"))
            seen.add(s)
    b.adjust(2)
    b.row(InlineKeyboardButton(text="✏️ Boshqa fan nomi yozing", callback_data="subj_other"))
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
    return b.as_markup()

def difficulty_kb():
    b = InlineKeyboardBuilder()
    icons = {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}
    for k, v in DIFFICULTY_LEVELS.items():
        b.add(InlineKeyboardButton(text=f"{icons.get(k,'')} {v}", callback_data=f"diff_{k}"))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
    return b.as_markup()

def visibility_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🌍 Ommaviy",       callback_data="vis_public"))
    b.row(InlineKeyboardButton(text="🔗 Ssilka orqali", callback_data="vis_link"))
    b.row(InlineKeyboardButton(text="🔒 Shaxsiy",       callback_data="vis_private"))
    b.row(InlineKeyboardButton(text="❌ Bekor",          callback_data="cancel_create"))
    return b.as_markup()

def mytest_settings_kb(tid, is_paused=False):
    """Mening testlarim — test sozlamalari"""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="👁 Ko'rish",          callback_data=f"mytest_view_{tid}"))
    b.row(
        InlineKeyboardButton(text="📤 Ulashish",           switch_inline_query=f"test_{tid}"),
        InlineKeyboardButton(text="🔍 Demo ulashish",      switch_inline_query=f"demo_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="📊 Kim yechgan",        callback_data=f"test_solvers_{tid}_0"),
        InlineKeyboardButton(text="📄 TXT yuklab olish",   callback_data=f"mytest_txt_{tid}"),
    )
    b.row(
        InlineKeyboardButton(
            text="▶️ Davom ettirish" if is_paused else "⏸ To'xtatib qo'yish",
            callback_data=f"test_resume_{tid}" if is_paused else f"test_pause_{tid}"
        ),
    )
    b.row(
        InlineKeyboardButton(text="✏️ Nomini o'zgartirish", callback_data=f"edit_title_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="🔄 Urinishlar soni", callback_data=f"edit_att_{tid}"),
        InlineKeyboardButton(text="⏱ Poll vaqti",         callback_data=f"edit_poll_time_{tid}"),
    )
    b.row(InlineKeyboardButton(text="🔐 Kirish nazorati",  callback_data=f"edit_allowed_{tid}"))
    b.row(InlineKeyboardButton(text="🗑 Testni o'chirish", callback_data=f"del_mytest_{tid}"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga",           callback_data="back_to_mytests_cat"))
    return b.as_markup()
