"""
👥 REFERRAL — Taklif tizimi
============================
Buyruqlar:
  /referral   — Referal havolam va statistika
  📊 Referallarim — Menyu tugmasi

Ishlash tartibi:
  1. User /referral yozadi → havola oladi
  2. Havola orqali yangi user keladi → /start?start=refUID
  3. start.py bu parametrni process_referral() ga yuboradi
  4. Referent mukofotlanadi
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command

from config import ADMIN_IDS
from utils.roles import (
    get_referral_code, get_referral_stats, format_role_info,
    ROLE_LABELS, can_create_any_test
)
from utils import ram_cache as ram

log    = logging.getLogger(__name__)
router = Router()


def _ref_text(uid: int, bot_username: str) -> str:
    """Referal xabari matni."""
    code    = get_referral_code(uid)
    link    = f"https://t.me/{bot_username}?start={code}"
    stats   = get_referral_stats(uid)
    role_info = format_role_info(uid)

    today_bonus = stats["today"] > 0

    lines = [
        "👥 <b>REFERAL TIZIMI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🔗 <b>Sizning havolangiz:</b>",
        f"<code>{link}</code>",
        "",
        "📊 <b>Statistika:</b>",
        f"  • Jami taklif: <b>{stats['total']}</b> kishi",
        f"  • Bugungi: <b>{stats['today']}</b> kishi",
        f"  • Bonus kunlar: <b>{stats['bonus_days']}</b>",
        "",
        role_info,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "ℹ️ <b>Qanday ishlaydi:</b>",
        "  • Har kuni 1 ta yangi taklif → test yaratish imkoni",
        "  • 1 kunda 10 ta taklif → <b>30 kun Student</b> status",
        "  • Student → shaxsiy va havola testlar yaratish",
        "  • Teacher → ommaviy test yaratish (admin tayinlaydi)",
        "",
    ]

    from utils.roles import get_creation_settings
    cs = get_creation_settings()
    if today_bonus:
        lines.append("✅ <b>Bugun test yaratish imkoningiz bor!</b>")
    if cs["test_creation_disabled"]:
        lines.append("🔒 Test yaratish hozircha <b>berkitilgan</b>.")
    elif cs["open_test_creation"]:
        lines.append("✅ <b>Test yaratish hammaga ochiq!</b>")
    elif cs["referral_creation_disabled"]:
        lines.append("🔒 Referal orqali test yaratish <b>berkitilgan</b>.")
    else:
        need = cs["refs_needed_for_create"]
        lines.append(f"💡 Bugun test yaratish uchun <b>{need} ta</b> referal yuboring")

    return "\n".join(lines)


def _ref_kb(link: str) -> object:
    b = InlineKeyboardBuilder()
    share_text = "Men bu botda testlar yechyapman! Siz ham qo'shiling 👇"
    share_url  = f"https://t.me/share/url?url={link}&text={share_text}"
    b.row(InlineKeyboardButton(text="📤 Do'stlarga ulashish", url=share_url))
    b.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="ref_refresh"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy sahifa", callback_data="main_menu"))
    return b.as_markup()


@router.message(Command("referral"))
@router.message(F.text.in_({"👥 Referallarim", "📊 Referallarim"}))
async def cmd_referral(message: Message):
    uid      = message.from_user.id
    bot_info = await message.bot.get_me()
    link     = f"https://t.me/{bot_info.username}?start=ref{uid}"
    text     = _ref_text(uid, bot_info.username)
    await message.answer(text, reply_markup=_ref_kb(link))


@router.callback_query(F.data == "ref_refresh")
async def cb_ref_refresh(callback: CallbackQuery):
    uid      = callback.from_user.id
    bot_info = await callback.bot.get_me()
    link     = f"https://t.me/{bot_info.username}?start=ref{uid}"
    text     = _ref_text(uid, bot_info.username)
    try:
        await callback.message.edit_text(text, reply_markup=_ref_kb(link))
    except Exception:
        pass
    await callback.answer("✅ Yangilandi")
