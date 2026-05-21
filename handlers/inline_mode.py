"""📤 INLINE MODE — Test ulashish + Demo rejim"""
import logging
from aiogram import Router, F
from aiogram.types import (InlineQuery, InlineQueryResultArticle,
                            InputTextMessageContent, InlineKeyboardButton)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.ram_cache import get_tests_meta, get_test_by_id

log    = logging.getLogger(__name__)
router = Router()

DEMO_MIN = 10
DEMO_MAX = 20


def _get_all_metas():
    ram_metas = {t["test_id"]: t for t in get_tests_meta() if t.get("test_id")}
    try:
        from utils import tg_db
        for m in tg_db.get_tests_meta():
            tid = m.get("test_id")
            if tid and tid not in ram_metas:
                ram_metas[tid] = m
    except Exception:
        pass
    return list(ram_metas.values())


def _get_test_meta(tid):
    t = get_test_by_id(tid)
    if t: return t
    try:
        from utils import tg_db
        return tg_db.get_test_meta(tid) or {}
    except Exception:
        return {}


@router.inline_query()
async def inline_handler(query: InlineQuery):
    text         = (query.query or "").strip().lower()
    bot_info     = await query.bot.me()
    bot_username = bot_info.username

    # Demo ulashish
    if text.startswith("demo_"):
        tid  = text[5:].upper().strip()
        test = _get_test_meta(tid)
        if test and test.get("test_id"):
            return await query.answer(
                [_make_result(test, bot_username, demo=True)],
                cache_time=0, is_personal=True
            )
        try:
            from utils.db import get_test_full
            full = await get_test_full(tid)
            if full and full.get("test_id"):
                return await query.answer(
                    [_make_result(full, bot_username, demo=True)],
                    cache_time=0, is_personal=True
                )
        except Exception:
            pass

    # Oddiy ulashish
    if text.startswith("test_"):
        tid  = text[5:].upper().strip()
        test = _get_test_meta(tid)
        if test and test.get("test_id"):
            return await query.answer(
                [_make_result(test, bot_username)],
                cache_time=0, is_personal=True
            )
        try:
            from utils.db import get_test_full
            full = await get_test_full(tid)
            if full and full.get("test_id"):
                return await query.answer(
                    [_make_result(full, bot_username)],
                    cache_time=0, is_personal=True
                )
        except Exception:
            pass

    all_metas = [
        t for t in _get_all_metas()
        if t.get("is_active", True)
        and t.get("visibility") in ("public", "link")
        and not t.get("is_paused", False)
        and not t.get("is_deleted", False)
    ]
    if text:
        all_metas = [
            t for t in all_metas
            if text in t.get("title", "").lower()
            or text in t.get("category", "").lower()
            or text in t.get("test_id", "").lower()
        ]
    results = [_make_result(t, bot_username) for t in all_metas[:20]]
    if not results:
        results = [InlineQueryResultArticle(
            id="empty", title="❌ Test topilmadi",
            description="Boshqa so'z bilan qidiring",
            input_message_content=InputTextMessageContent(message_text="❌ Test topilmadi.")
        )]
    await query.answer(results, cache_time=0, is_personal=True)


def _make_result(test: dict, bot_username: str, demo=False) -> InlineQueryResultArticle:
    tid   = test.get("test_id", "")
    title = test.get("title", "Nomsiz")
    cat   = test.get("category", "Boshqa")
    qc    = len(test.get("questions", [])) or test.get("question_count", 0)
    sc    = test.get("solve_count", 0)
    pt    = test.get("poll_time", 30)
    diff  = {
        "easy":   "🟢 Oson", "medium": "🟡 O'rtacha",
        "hard":   "🔴 Qiyin", "expert": "⚡ Ekspert"
    }.get(test.get("difficulty", ""), "🟡 O'rtacha")
    base = f"https://t.me/{bot_username}"

    if demo:
        demo_q = min(DEMO_MAX, max(DEMO_MIN, qc // 3))
        msg_text = (
            f"🔍 <b>[DEMO] {title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁 Fan: <b>{cat}</b>\n"
            f"📊 Qiyinlik: {diff}\n"
            f"📋 Jami savollar: <b>{qc} ta</b>\n"
            f"🔍 Demo: faqat <b>{demo_q} ta</b> savol\n"
            f"⏱ Poll vaqti: {pt}s/savol\n\n"
            f"⚠️ <b>Bu sinov (demo) rejimi!</b>\n"
            f"Faqat {demo_q} ta savol yechish mumkin.\n"
            f"To'liq test uchun adminga murojat qiling."
        )
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="🔍 Demo (Inline)", url=f"{base}?start=demo_{tid}"),
            InlineKeyboardButton(text="🔍 Demo (Poll)",   url=f"{base}?start=demopoll_{tid}"),
        )
        from config import ADMIN_USERNAME
        b.row(InlineKeyboardButton(
            text="📩 To'liq test olish",
            url=f"https://t.me/{ADMIN_USERNAME}"
        ))
        result_id = f"demo_{tid}"
        result_title = f"🔍 DEMO: {title}"
        result_desc  = f"Demo: {demo_q} savol | {cat}"
    else:
        msg_text = (
            f"📝 <b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁 Fan: <b>{cat}</b>\n"
            f"📊 Qiyinlik: {diff}\n"
            f"📋 Savollar: <b>{qc} ta</b>\n"
            f"⏱ Poll vaqti: {pt}s/savol\n"
            f"🎯 O'tish foizi: <b>{test.get('passing_score', 60)}%</b>\n"
            f"👥 Ishlaganlar: <b>{sc} marta</b>\n"
            f"🆔 Kod: <code>{tid}</code>\n\n"
            f"👇 <b>Qanday boshlash?</b>"
        )
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="▶️ Inline test", url=f"{base}?start={tid}"),
            InlineKeyboardButton(text="📊 Quiz Poll",   url=f"{base}?start=poll_{tid}"),
        )
        b.row(
            InlineKeyboardButton(text="👥 Guruhda Poll",
                url=f"https://t.me/{bot_username}?startgroup=gpoll_{tid}"),
            InlineKeyboardButton(text="👥 Guruhda Inline",
                url=f"https://t.me/{bot_username}?startgroup=ginline_{tid}"),
        )
        result_id    = tid if tid else "noid"
        result_title = f"📝 {title}"
        result_desc  = f"📁 {cat} | 📋 {qc} savol | 👥 {sc} marta"

    return InlineQueryResultArticle(
        id=result_id,
        title=result_title,
        description=result_desc,
        input_message_content=InputTextMessageContent(
            message_text=msg_text, parse_mode="HTML"
        ),
        reply_markup=b.as_markup(),
    )
