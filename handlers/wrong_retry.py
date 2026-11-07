"""❌ XATOLAR USTIDA ISHLASH — oxirgi yechilgan testning xato savollarini Quiz Poll rejimida qayta yechish.
Xatolar Statistika kanalidan (RAM keshi 5 daqiqa) olinadi; faqat OXIRGI xatosi bor test saqlanadi."""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from utils import stats_store
from utils.states import PollTest, TestSolving

log = logging.getLogger(__name__)
router = Router()

_ACTIVE = (PollTest.active.state, PollTest.paused.state,
           TestSolving.answering.state, TestSolving.text_answer.state, TestSolving.paused.state)

NO_SAVED = ("❌ Saqlangan xatolar yo'q.\n"
            "Xatolar faqat OXIRGI yechilgan (xatosi bor) test uchun saqlanadi.")


@router.message(Command("xatolar"))
async def cmd_xatolar(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    uid = message.from_user.id
    if not stats_store.enabled():
        return await message.answer("⚠️ Xatolarni saqlash hozircha sozlanmagan.")
    row = await stats_store.get_wrong_row(uid)
    if not row or not row.get("wrong_count") or not row.get("test_id"):
        return await message.answer(NO_SAVED)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📊 Xatolarni Quiz Poll'da yechish",
                               callback_data=f"wr_go_{row['test_id']}"))
    await message.answer(
        f"❌ <b>Xatolar ustida ishlash</b>\n\n"
        f"📝 <b>{row.get('title') or 'Test'}</b>\n"
        f"❌ Xato savollar: <b>{row['wrong_count']}</b> ta\n"
        f"🕒 {str(row.get('updated_at', ''))[:16].replace('T', ' ')}\n\n"
        f"<i>Faqat oxirgi yechilgan test xatolari saqlanadi.</i>",
        reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("wr_go_"))
async def wr_go(callback: CallbackQuery, state: FSMContext):
    tid = callback.data[len("wr_go_"):]
    uid = callback.from_user.id
    if not callback.message or callback.message.chat.type != "private":
        return await callback.answer("Bu faqat shaxsiy chatda ishlaydi.", show_alert=True)

    cur = await state.get_state()
    if cur in _ACTIVE:
        return await callback.answer(
            "⚠️ Hozir faol test bor.\nAvval uni yakunlang yoki to'xtating.", show_alert=True)

    data = await stats_store.load_wrong(callback.bot, uid, tid)
    if not data:
        return await callback.answer(
            "❌ Bu testning xatolari saqlanmagan.\n"
            "Faqat oxirgi yechilgan (xatosi bor) test xatolari saqlanadi.", show_alert=True)

    questions = data.get("questions", [])
    test = {
        "test_id":      f"{tid}_wr",
        "orig_test_id": tid,
        "title":        f"❌ Xatolar: {data.get('title', 'Test')}",
        "questions":    questions,
        "poll_time":    int(data.get("poll_time", 30) or 30),
        "passing_score": 60,
        "is_retry":     True,
        "total":        int(data.get("total", len(questions))),
    }
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    from handlers.poll_test import _begin_poll
    await _begin_poll(callback.bot, state, uid, callback.message.chat.id,
                      test["test_id"], False, test=test, is_demo=False)
