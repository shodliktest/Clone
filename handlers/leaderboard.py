"""🏆 LEADERBOARD — Global va Guruh"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from utils.db import get_leaderboard, get_all_tests
from utils.ram_cache import get_test_meta, get_global_leaderboard, get_group_leaderboard

log    = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "🏆 Reyting")
async def lb_msg(message: Message):
    await _show_global_lb(message)

@router.callback_query(F.data == "leaderboard")
async def lb_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_global_lb(callback.message, edit=True)

@router.callback_query(F.data == "group_leaderboard")
async def group_lb_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_group_lb(callback.message, edit=True)

@router.callback_query(F.data.startswith("lb_test_"))
async def lb_test(callback: CallbackQuery):
    await callback.answer()
    tid = callback.data[8:]
    await _show_test_lb(callback.message, tid, edit=True)

async def show_leaderboard(event, tid):
    if hasattr(event, 'message'):
        await _show_test_lb(event.message, tid)
    else:
        await _show_test_lb(event, tid)


async def _show_global_lb(msg, edit=False):
    # Avval RAMdan
    leaders = get_global_leaderboard()
    # RAMda yo'q bo'lsa — db dan
    if not leaders:
        leaders = get_leaderboard(20)

    medals = ["🥇","🥈","🥉"]
    b      = InlineKeyboardBuilder()

    if not leaders:
        text = "🏆 <b>REYTING</b>\n\nHali natijalar yo'q.\nBirinchi bo'lib test yeching! 🚀"
        b.row(InlineKeyboardButton(text="📚 Testlarga o'tish", callback_data="go_tests"))
        b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    text = f"🏆 <b>GLOBAL REYTING</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, u in enumerate(leaders):
        medal  = medals[i] if i < 3 else f"{i+1}."
        avg    = round(u.get("avg_score", 0), 1)
        total  = u.get("total_tests", 0)
        name   = u.get("name", "?")[:20]
        filled = int(avg / 10)
        bar    = "█" * filled + "░" * (10 - filled)
        text  += f"{medal} <b>{name}</b>\n   <code>[{bar}]</code> {avg}% | {total} test\n\n"

    b.row(InlineKeyboardButton(text="👥 Guruh reytingi", callback_data="group_leaderboard"))
    b.row(InlineKeyboardButton(text="📋 Test reytinglari", callback_data="lb_tests_list"))
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


async def _show_group_lb(msg, edit=False):
    """Bugungi guruh leaderboard — faqat guruhda yechganlar"""
    from datetime import date
    lb    = get_group_leaderboard()
    today = str(date.today())
    b     = InlineKeyboardBuilder()

    if not lb:
        text = (
            f"🏆 <b>GURUH REYTINGI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {today}\n\n"
            f"Bugun hali guruhda test yechilmagan."
        )
        b.row(InlineKeyboardButton(text="⬅️ Global reyting", callback_data="leaderboard"))
        b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    medals = ["🥇","🥈","🥉"]
    text   = f"🏆 <b>GURUH REYTINGI</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n📅 {today}\n\n"
    for i, u in enumerate(lb):
        medal  = medals[i] if i < 3 else f"{i+1}."
        score  = u.get("best_score", 0)
        cor    = u.get("correct", 0)
        tot    = u.get("total", 0)
        name   = u.get("name", "?")[:20]
        filled = int(score / 10)
        bar    = "█" * filled + "░" * (10 - filled)
        text  += f"{medal} <b>{name}</b>\n   <code>[{bar}]</code> {score}% ({cor}/{tot})\n\n"

    b.row(InlineKeyboardButton(text="⬅️ Global reyting", callback_data="leaderboard"))
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "lb_tests_list")
async def lb_tests_list(callback: CallbackQuery):
    await callback.answer()
    tests = [t for t in get_all_tests() if t.get("solve_count", 0) > 0]
    tests.sort(key=lambda x: x.get("solve_count", 0), reverse=True)

    text = "🏆 <b>TEST REYTINGLARI</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    b    = InlineKeyboardBuilder()
    for i, t in enumerate(tests[:10], 1):
        tid   = t.get("test_id", "")
        title = t.get("title", "?")[:20]
        sc    = t.get("solve_count", 0)
        avg   = round(t.get("avg_score", 0), 1)
        text += f"{i}. <b>{title}</b>\n   👥{sc} marta | ⭐{avg}%\n\n"
        b.row(InlineKeyboardButton(text=f"🏆 {title[:15]}", callback_data=f"lb_test_{tid}"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="leaderboard"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


async def _show_test_lb(msg, tid, edit=False):
    from utils.ram_cache import get_all_solvers_for_test
    meta    = get_test_meta(tid)
    solvers = get_all_solvers_for_test(tid)

    title  = meta.get("title", "Test") if meta else tid
    medals = ["🥇","🥈","🥉"]
    text   = (
        f"🏆 <b>{title.upper()} — REYTING</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 {len(solvers)} qatnashchi\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    if not solvers:
        text += "Hali hech kim yechmagan."
    for i, sv in enumerate(solvers[:15]):
        medal  = medals[i] if i < 3 else f"{i+1}."
        filled = int(sv["best_score"] / 10)
        bar    = "█" * filled + "░" * (10 - filled)
        text  += (
            f"{medal} <b>{sv['name']}</b>\n"
            f"   <code>[{bar}]</code> {sv['best_score']}% | {sv['attempts']} urinish\n\n"
        )

    b = InlineKeyboardBuilder()
    if meta:
        b.row(
            InlineKeyboardButton(text="▶️ Boshlash",   callback_data=f"start_test_{tid}"),
            InlineKeyboardButton(text="📊 Poll rejim", callback_data=f"start_poll_{tid}"),
        )
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="leaderboard"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",  callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())
