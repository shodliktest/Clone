"""
💰 COIN MENYUSI — balans, ishlash yo'llari, Teacher sotib olish.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_USERNAME
from utils import coins as C

log = logging.getLogger(__name__)
router = Router()


def _menu_text(uid: int) -> str:
    rr, rn = C.ref_rewards()
    p30 = C.teacher_price(30)
    p90 = C.teacher_price(90)
    return (
        "💰 <b>COIN HISOBIM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👛 Balans: <b>{C.get_balance(uid)} coin</b>\n\n"
        "📌 <b>Coin nimaga ketadi?</b>\n"
        f"  📝 Test yaratish — savollar soniga qarab\n"
        f"  🤖 AI bilan qayta yechish\n"
        f"  🎓 Teacher daraja: 30 kun <b>{p30}</b> / 90 kun <b>{p90}</b> coin\n\n"
        "💎 <b>Coin qanday ishlanadi?</b>\n"
        f"  👥 Do'st chaqirish — har biri <b>+{rr} coin</b>\n"
        f"  🎁 Yangi do'stingiz ham <b>+{rn} coin</b> oladi\n"
        f"  💳 Hisob to'ldirish — admin orqali"
    )


def _menu_kb(uid: int, bot_username: str):
    link = f"https://t.me/{bot_username}?start=ref{uid}"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="👥 Do'st chaqirish",
        switch_inline_query=f"\n👋 Men bilan testlar yeching! {link}"))
    b.row(InlineKeyboardButton(text="🔗 Havolani ko'rish",
                               callback_data="coins_my_ref"))
    b.row(
        InlineKeyboardButton(text=f"🎓 Teacher 30 kun ({C.teacher_price(30)})",
                             callback_data="coins_buy_t30"),
        InlineKeyboardButton(text=f"🎓 90 kun ({C.teacher_price(90)})",
                             callback_data="coins_buy_t90"),
    )
    b.row(InlineKeyboardButton(text="💳 Hisob to'ldirish",
                               url=f"https://t.me/{ADMIN_USERNAME}"))
    return b.as_markup()


@router.message(Command("balance"))
@router.message(Command("coins"))
@router.message(F.text == "💰 Balansim")
async def cmd_balance(message: Message):
    bu = (await message.bot.me()).username
    await message.answer(_menu_text(message.from_user.id),
                         reply_markup=_menu_kb(message.from_user.id, bu))


@router.callback_query(F.data == "coins_menu")
async def cb_coins_menu(callback: CallbackQuery):
    await callback.answer()
    bu = (await callback.bot.me()).username
    await callback.message.answer(
        _menu_text(callback.from_user.id),
        reply_markup=_menu_kb(callback.from_user.id, bu))


@router.callback_query(F.data == "coins_my_ref")
async def cb_my_ref(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    bu  = (await callback.bot.me()).username
    rr, rn = C.ref_rewards()
    link = f"https://t.me/{bu}?start=ref{uid}"
    await callback.message.answer(
        "🔗 <b>Sizning referal havolangiz:</b>\n"
        f"<code>{link}</code>\n\n"
        f"Har bir yangi do'st uchun: siz <b>+{rr}</b>, do'stingiz <b>+{rn}</b> coin.")


# ── 🎓 Teacher sotib olish ───────────────────────────────────
async def _buy_teacher(callback: CallbackQuery, days: int, dur_key: str):
    uid   = callback.from_user.id
    price = C.teacher_price(days)
    from utils.roles import get_role, set_role
    if get_role(uid) in ("teacher", "admin"):
        return await callback.answer("✅ Sizda allaqachon Teacher+ daraja bor",
                                     show_alert=True)
    if not C.spend_coins(uid, price, f"buy teacher {days}d"):
        await callback.answer("❌ Coin yetarli emas", show_alert=True)
        return await callback.message.answer(
            C.insufficient_text(uid, price, f"Teacher {days} kun"))
    try:
        set_role(uid, "teacher", dur_key)
    except Exception as e:
        C.add_coins(uid, price, "buy teacher refund")
        log.error(f"buy teacher: {e}")
        return await callback.answer("❌ Xato, coin qaytarildi", show_alert=True)
    await callback.answer("🎉 Tabriklaymiz!", show_alert=True)
    await callback.message.answer(
        "🎓 <b>TEACHER DARAJASI FAOL!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Muddat: <b>{days} kun</b>\n"
        f"💰 Sarflandi: <b>{price} coin</b> | Qoldiq: <b>{C.get_balance(uid)}</b>\n\n"
        "Endi siz:\n"
        "  🌍 Ommaviy testlar yarata olasiz\n"
        "  💸 Coin xarajatlarida chegirma olasiz")


@router.callback_query(F.data == "coins_buy_t30")
async def cb_buy_t30(callback: CallbackQuery):
    await _buy_teacher(callback, 30, "30d")


@router.callback_query(F.data == "coins_buy_t90")
async def cb_buy_t90(callback: CallbackQuery):
    await _buy_teacher(callback, 90, "90d")
