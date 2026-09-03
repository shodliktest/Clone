"""
🤖 AI BILAN QAYTA YECHISH
Mavjud testning javoblarini AI (akademik prompt) bilan qaytadan aniqlaydi
va testni AYNAN SHU KOD ostida almashtiradi — havola/QR o'zgarmaydi.

Kim ishlatadi: test egasi yoki admin.
Narx: coins.ai_resolve_cost (admin bepul, teacher chegirma).
Xavfsizlik: eski versiya zaxiraga olinadi; AI hech narsa yecha olmasa
coin to'liq qaytariladi.
"""
import copy
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS, ADMIN_USERNAME
from utils import coins as C
from utils.ram_cache import get_test_meta

log = logging.getLogger(__name__)
router = Router()


def _can_touch(uid: int, meta: dict) -> bool:
    return uid in ADMIN_IDS or str(meta.get("creator_id")) == str(uid)


# ── 1-bosqich: tasdiqlash oynasi ─────────────────────────────
@router.callback_query(F.data.startswith("aisolve_")
                       & ~F.data.startswith("aisolve_go_")
                       & (F.data != "aisolve_close"))
async def aisolve_confirm(callback: CallbackQuery):
    tid  = callback.data[8:].upper()
    uid  = callback.from_user.id
    meta = get_test_meta(tid) or {}
    if not meta:
        return await callback.answer("❌ Test topilmadi", show_alert=True)
    if not _can_touch(uid, meta):
        return await callback.answer("🚫 Faqat test egasi yoki admin", show_alert=True)
    await callback.answer()

    qc   = meta.get("question_count", 0)
    cost = C.ai_resolve_cost(uid, qc)
    bal  = C.get_balance(uid)

    b = InlineKeyboardBuilder()
    if cost == 0 or bal >= cost:
        b.row(InlineKeyboardButton(
            text=f"🤖 Boshlash ({'bepul' if cost == 0 else f'{cost} coin'})",
            callback_data=f"aisolve_go_{tid}"))
    else:
        b.row(InlineKeyboardButton(text="🔗 Referal havolam (+coin)",
                                   callback_data="coins_my_ref"))
        b.row(InlineKeyboardButton(text="💳 Hisob to'ldirish",
                                   url=f"https://t.me/{ADMIN_USERNAME}"))
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="aisolve_close"))

    afford = "✅" if (cost == 0 or bal >= cost) else "❌ yetarli emas"
    await callback.message.answer(
        "🤖 <b>AI BILAN QAYTA YECHISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>{meta.get('title','?')}</b>\n"
        f"🆔 <code>{tid}</code> | 📋 {qc} savol\n\n"
        "AI barcha savollarni <b>akademik darajada</b> qaytadan yechadi,\n"
        "to'g'ri javoblar yangilanadi va test <b>SHU KOD</b> ostida\n"
        "almashtiriladi — havolani qayta tarqatish shart emas.\n"
        "🗄 Eski versiya zaxiraga olinadi.\n\n"
        f"💰 Narx: <b>{cost} coin</b> | Balans: <b>{bal}</b> {afford}",
        reply_markup=b.as_markup())


@router.callback_query(F.data == "aisolve_close")
async def aisolve_close(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass


# ── 2-bosqich: yechish va almashtirish ───────────────────────
@router.callback_query(F.data.startswith("aisolve_go_"))
async def aisolve_go(callback: CallbackQuery):
    tid  = callback.data[11:].upper()
    uid  = callback.from_user.id
    meta = get_test_meta(tid) or {}
    if not meta or not _can_touch(uid, meta):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer()

    # To'liq testni olish
    from utils.db import get_test_full
    full = await get_test_full(tid)
    if not full or not full.get("questions"):
        return await callback.message.edit_text("❌ Test savollari yuklanmadi.")

    qs   = full["questions"]
    cost = C.ai_resolve_cost(uid, len(qs))
    if cost > 0 and not C.spend_coins(uid, cost, f"aisolve {tid}"):
        return await callback.message.edit_text(
            C.insufficient_text(uid, cost, "AI qayta yechish"))

    status = await callback.message.edit_text(
        f"🤖 <b>AI tayyorlanmoqda...</b>\n📋 {len(qs)} savol")

    # AI yechish — mavjud universal yechgichdan foydalanamiz
    try:
        from handlers.create_test import _ai_solve
        new_qs = copy.deepcopy(qs)
        for q in new_qs:
            q.pop("_marked", None)       # hammasi qayta yechilsin
            q.pop("_ai_solved", None)
        new_qs = await _ai_solve(new_qs, status)
    except Exception as e:
        if cost > 0:
            C.add_coins(uid, cost, f"aisolve refund {tid}")
        log.error(f"aisolve {tid}: {e}")
        return await status.edit_text(
            f"❌ AI xatosi: {e}\n💰 {cost} coin qaytarildi.")

    solved = sum(1 for q in new_qs if q.get("_ai_solved"))
    if solved == 0:
        if cost > 0:
            C.add_coins(uid, cost, f"aisolve refund {tid}")
        return await status.edit_text(
            "❌ AI hech bir savolni yecha olmadi (limit/aloqa).\n"
            f"💰 {cost} coin qaytarildi. Keyinroq urinib ko'ring.")

    # Yangi test hujjati — meta o'zgarmaydi, faqat savollar yangilanadi
    new_test = dict(full)
    for q in new_qs:
        q.pop("_marked", None)
    new_test["questions"]   = new_qs
    new_test["ai_resolved"] = True

    from utils import tg_db
    res = await tg_db.replace_test_full(tid, new_test, replaced_by=uid)
    if not res.get("ok"):
        if cost > 0:
            C.add_coins(uid, cost, f"aisolve refund {tid}")
        return await status.edit_text(
            f"❌ Saqlash xatosi: {res.get('error')}\n💰 {cost} coin qaytarildi.")

    await status.edit_text(
        "✅ <b>AI QAYTA YECHIB BO'LDI!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{tid}</code> (kod o'zgarmadi)\n"
        f"📝 <b>{meta.get('title','?')}</b>\n"
        f"🤖 Yechildi: <b>{solved}/{len(qs)}</b> savol\n"
        f"{f'💰 Sarflandi: {cost} coin | Qoldiq: {C.get_balance(uid)}' if cost > 0 else '💰 Bepul (admin)'}\n\n"
        "📢 Eski havola ishlaydi — qayta tarqatish shart emas.\n"
        "🗄 Eski versiya zaxirada.")
