"""📚 TESTLAR — Katalog + Inline test (edit_message + auto-next)"""
import logging, re, time, asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from utils.db import get_all_tests, get_test_full, save_result
from utils.ram_cache import get_test_by_id, is_test_paused, get_test_meta
from utils.states import TestSolving
from keyboards.keyboards import main_kb, inline_pause_kb, CAT_ICONS, get_cat_icon

log    = logging.getLogger(__name__)
router = Router()

_inline_timers: dict = {}
ANSWER_SHOW_SEC = 30
QUESTION_SEC    = 30

_CIRCLE = {"A":"🅐","B":"🅑","C":"🅒","D":"🅓","E":"🅔","F":"🅕","G":"🅖","H":"🅗"}
def _cl(l): return _CIRCLE.get(str(l).upper(), f"[{str(l).upper()}]")


async def _send_no_access(callback: CallbackQuery, meta: dict):
    """Ruxsat yo'q xabari — to'liq xabar + admin bilan bog'lanish tugmasi"""
    from config import ADMIN_USERNAME
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="📩 Adminga murojat",
        url=f"https://t.me/{ADMIN_USERNAME}"
    ))
    b.row(InlineKeyboardButton(
        text="🤖 Bot orqali murojat",
        callback_data="contact_admin"
    ))
    title = meta.get("title", "Bu test")
    try:
        await callback.message.answer(
            f"🔐 <b>Kirish cheklangan</b>\n\n"
            f"<b>{title}</b> testiga kirishga ruxsatingiz yo'q.\n\n"
            f"Ruxsat olish uchun:\n"
            f"• Adminga murojat qiling: @{ADMIN_USERNAME}\n"
            f"• Yoki quyidagi tugmani bosing 👇",
            reply_markup=b.as_markup()
        )
    except Exception:
        pass
    await callback.answer("🔐 Kirish cheklangan!", show_alert=True)


def _check_attempts(uid: int, tid: str, meta: dict) -> tuple[bool, str]:
    """
    Urinishlar sonini tekshiradi.
    allowed_users ro'yxatida bo'lsa — cheksiz.
    Returns: (can_start, reason_text)
    """
    from utils.ram_cache import get_test_stats_for_user
    max_att = meta.get("max_attempts", 0)  # 0 = cheksiz

    # allowed_users da bo'lsa cheksiz
    allowed = meta.get("allowed_users", [])
    if allowed and uid in allowed:
        return True, ""

    if max_att == 0:
        return True, ""

    stats = get_test_stats_for_user(uid, tid)
    used  = stats.get("attempts", 0) if stats else 0

    if used >= max_att:
        return False, (
            f"⛔ <b>Urinishlar tugadi</b>\n\n"
            f"Bu test uchun {max_att} ta urinish berilgan edi.\n"
            f"Siz {used} marta yechdingiz.\n\n"
            f"Yangi urinish uchun test egasiga murojat qiling."
        )
    return True, ""


async def _save_partial_result(uid: int, tid: str, answers: list,
                               questions: list, state_data: dict):
    """
    Chala yechilgan test natijasini saqlaydi.
    answered_count / total_count ko'rsatiladi.
    """
    if not answers or not questions:
        return
    from utils.db import save_result as _sr
    answered = len(answers)
    total    = len(questions)
    correct  = sum(1 for a in answers if a.get("is_correct"))
    pct      = round(correct / answered * 100) if answered else 0
    result   = {
        "pct":          pct,
        "correct":      correct,
        "total":        total,
        "answered":     answered,
        "partial":      True,
        "time_spent":   state_data.get("time_spent", 0),
        "answers":      answers,
    }
    try:
        await _sr(uid, tid, result)
    except Exception as e:
        log.error(f"partial save error: {e}")


def _shuffle_options(qs):
    """Variantlarni aralashtiradi, label qayta tartiblanadi (A B C D o'z joyida)."""
    import re as _re
    LABELS = ["A","B","C","D","E","F","G","H"]
    def strip_lbl(o):
        return _re.sub(r"^[A-Ha-h]\s*[).:]\s*", "", str(o)).strip()
    for q in qs:
        if q.get("type") not in ("multiple_choice", "multiple", "multi_select"):
            continue
        opts = q.get("options", [])
        if len(opts) < 2:
            continue
        pure     = [strip_lbl(o) for o in opts]
        corr_val = q.get("correct")
        if isinstance(corr_val, int) and 0 <= corr_val < len(pure):
            corr_text = pure[corr_val]
        elif isinstance(corr_val, str):
            corr_text = strip_lbl(corr_val)
        else:
            corr_text = None
        import random
        random.shuffle(pure)
        q["options"] = [f"{LABELS[i]}) {t}" for i, t in enumerate(pure)]
        if corr_text is not None:
            new_idx = next((i for i,t in enumerate(pure) if t == corr_text), 0)
            q["correct"] = f"{LABELS[new_idx]}) {corr_text}"


def _timer_bar(remaining, total_sec, width=15):
    """●●●○○ — kamayib boradi"""
    if total_sec <= 0: return "○" * width
    filled = round(remaining * width / total_sec)
    filled = max(0, min(width, filled))
    return "●" * filled + "○" * (width - filled)




async def _show_next_question(bot, cid, msg_id, qs, idx, state, uid):
    """Keyingi savolni edit orqali ko'rsatib, to'g'ri state o'rnatadi va timer ishlatadi"""
    # Rasm bo'lsa — savol oldidan yuborish
    q = qs[idx]
    photo_id = q.get("photo") or q.get("image") or None
    if not photo_id:
        qtxt_raw = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text", ""))).strip()
        pm_match = re.match(r'^\[rasm:\s*([^\]]+)\]\s*', qtxt_raw)
        if pm_match:
            photo_id = pm_match.group(1).strip()
    if photo_id:
        try:
            await bot.send_photo(cid, photo_id, protect_content=True)
        except Exception as e:
            log.error(f"Inline rasm xato: {e}")
    text, kb, is_text = _build_question_content(qs, idx, time_left=QUESTION_SEC)
    try:
        await bot.edit_message_text(chat_id=cid, message_id=msg_id, text=text, reply_markup=kb)
        new_msg_id = msg_id
    except TelegramBadRequest:
        msg = await bot.send_message(cid, text, reply_markup=kb,
        protect_content=True)
        new_msg_id = msg.message_id

    await state.update_data(q_msg_id=new_msg_id, answered_this=False)
    if is_text:
        await state.set_state(TestSolving.text_answer)
    else:
        await state.set_state(TestSolving.answering)

    _cancel_timer(uid)
    task = asyncio.create_task(
        _question_timeout(bot, cid, state, uid, idx, QUESTION_SEC)
    )
    _inline_timers[uid] = task

def _check_text_answer(user_ans: str, correct: str, accepted: list = None) -> bool:
    """Matn javobni tekshirish — katta-kichik harf farq qilmaydi, bo'sh joy kesadi"""
    u = user_ans.strip().lower()
    c = str(correct).strip().lower()
    if u == c:
        return True
    # Qabul qilinadigan alternativ javoblar
    for alt in (accepted or []):
        if u == str(alt).strip().lower():
            return True
    # Raqamli javoblar uchun (masalan "42" == "42.0")
    try:
        if float(u.replace(",", ".")) == float(c.replace(",", ".")):
            return True
    except Exception:
        pass
    return False

def _cancel_timer(uid):
    t = _inline_timers.pop(uid, None)
    if t:
        try: t.cancel()
        except: pass


# ══ TEST KODI BILAN QIDIRISH ═══════════════════════════════════
@router.message(F.text.regexp(r'^[A-Z0-9]{6,10}$'))
async def test_code_direct(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state,
               TestSolving.paused.state):
        return
    tid  = message.text.strip().upper()
    test = get_test_by_id(tid) or await get_test_full(tid)
    if not test: return
    from handlers.start import _send_test_card
    await _send_test_card(message, test, tid, viewer_uid=message.from_user.id)


# ══ TESTLAR — FANLAR BO'YICHA ══════════════════════════════════
@router.message(F.text == "📚 Testlar")
async def tests_by_category(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state):
        return
    await _show_categories(message, message.from_user.id)

@router.callback_query(F.data == "go_tests")
async def go_tests_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_categories(callback.message, callback.from_user.id, edit=True)

@router.callback_query(F.data == "back_to_cats")
async def back_to_cats(callback: CallbackQuery):
    await callback.answer()
    await _show_categories(callback.message, callback.from_user.id, edit=True)


async def _show_categories(msg, uid, edit=False):
    from utils.db import get_user_results
    all_tests    = get_all_tests()
    solved_tids  = {r.get("test_id") for r in get_user_results(uid)}

    visible = [
        t for t in all_tests
        if (t.get("visibility") == "public" or
            (t.get("visibility") == "link" and t.get("test_id") in solved_tids))
        and not t.get("is_paused")
    ]
    if not visible:
        text = "📭 <b>TESTLAR</b>\n\nHozircha ommaviy test yo'q."
        b    = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    cats = {}
    for t in visible:
        c = t.get("category") or "Boshqa"
        if c not in cats:
            cats[c] = {"count": 0, "solved": 0}
        cats[c]["count"] += 1
        if t.get("test_id") in solved_tids:
            cats[c]["solved"] += 1

    sorted_cats = sorted(cats.items(), key=lambda x: x[1]["count"], reverse=True)
    text = (
        f"📚 <b>TESTLAR — FANLAR BO'YICHA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(visible)} ta test | {len(cats)} ta fan</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for cat, info in sorted_cats:
        icon = get_cat_icon(cat)
        prog = f" ✅{info['solved']}/{info['count']}" if info['solved'] else f" — {info['count']} ta"
        text += f"{icon} <b>{cat}</b>{prog}\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {cat} — {info['count']} ta",
            callback_data=f"cat_{cat[:30]}"
        ))
    b.row(
        InlineKeyboardButton(text="🔍 Kod bilan", callback_data="search_by_code"),
        InlineKeyboardButton(text="🌟 Hammasi",   callback_data="cat_ALL"),
    )
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("cat_"))
async def show_cat_tests(callback: CallbackQuery):
    await callback.answer()
    await _show_cat_tests(callback.message, callback.from_user.id,
                          callback.data[4:], page=0, edit=True)

@router.callback_query(F.data.startswith("catp_"))
async def cat_page_cb(callback: CallbackQuery):
    await callback.answer()
    parts    = callback.data[5:].rsplit("_", 1)
    cat_name = parts[0]
    page     = int(parts[1]) if len(parts) > 1 else 0
    await _show_cat_tests(callback.message, callback.from_user.id, cat_name, page, edit=True)


async def _show_cat_tests(msg, uid, cat_name, page=0, edit=False):
    from utils.db import get_user_results
    solved_map  = {r.get("test_id"): r for r in get_user_results(uid)}
    solved_tids = set(solved_map)
    all_tests   = get_all_tests()

    tests = [
        t for t in all_tests
        if (cat_name == "ALL" or t.get("category") == cat_name)
        and (t.get("visibility") == "public" or
             (t.get("visibility") == "link" and t.get("test_id") in solved_tids))
        and not t.get("is_paused")
    ]
    if not tests:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_cats"))
        try: await msg.edit_text("📭 Bu fanda test yo'q.", reply_markup=b.as_markup())
        except TelegramBadRequest: pass
        return

    PG    = 6
    total = (len(tests)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = tests[page*PG:(page+1)*PG]
    diff_m = {"easy": "🟢", "medium": "🟡", "hard": "🔴", "expert": "⚡"}
    title  = "🌟 BARCHA TESTLAR" if cat_name == "ALL" else f"📚 {cat_name.upper()}"

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta test | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in chunk:
        tid   = t.get("test_id", "")
        t_t   = t.get("title", "Nomsiz")
        d_ico = diff_m.get(t.get("difficulty", ""), "🟡")
        qc    = t.get("question_count", len(t.get("questions", [])))
        sc    = t.get("solve_count", 0)
        vis   = "🔗" if t.get("visibility") == "link" else ""
        if tid in solved_tids:
            r      = solved_map[tid]
            status = f"✅{r.get('best_pct', r.get('last_pct',0))}%×{r.get('attempts',1)}"
        else:
            status = "▶️"
        text += f"{vis}{d_ico} <b>{t_t}</b>\n   📋{qc} | 👥{sc} | {status}\n\n"
        b.row(InlineKeyboardButton(
            text=f"{'✅' if tid in solved_tids else '▶️'} {t_t[:25]}",
            callback_data=f"view_test_{tid}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"catp_{cat_name}_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"catp_{cat_name}_{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_cats"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",   callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("view_test_"))
async def view_test(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[10:]
    test = get_test_by_id(tid) or await get_test_full(tid)
    if not test:
        try: await callback.message.edit_text("❌ Test topilmadi.")
        except: pass
        return
    from handlers.start import _send_test_card
    await _send_test_card(callback, test, tid, viewer_uid=callback.from_user.id, edit=True)

@router.callback_query(F.data == "search_by_code")
async def search_by_code_cb(callback: CallbackQuery):
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_cats"))
    try:
        await callback.message.edit_text(
            "🔍 <b>TEST KODI BILAN QIDIRISH</b>\n\n"
            "Test kodini yuboring (masalan: <code>AB12CD34</code>)",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest: pass


# ══════════════════════════════════════════════════════════════
#  INLINE TEST — edit_message asosida
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("start_test_") | F.data.startswith("start_demo_"))
async def start_inline_test(callback: CallbackQuery, state: FSMContext):
    tid = callback.data[11:]
    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)
    await callback.answer()
    uid  = callback.from_user.id
    meta = get_test_meta(tid) or {}

    # Demo rejim tekshiruvi
    is_demo = tid.startswith("DEMO_") or callback.data.startswith("start_demo_")
    if is_demo:
        tid = tid.replace("DEMO_", "", 1)
        meta = get_test_meta(tid) or {}

    # Ruxsat tekshiruvi
    allowed = meta.get("allowed_users", [])
    if allowed and uid not in allowed:
        return await _send_no_access(callback, meta)

    # Urinishlar cheklovi
    can_start, reason = _check_attempts(uid, tid, meta)
    if not can_start:
        from config import ADMIN_USERNAME
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="📩 Adminga murojat",
                                   url=f"https://t.me/{ADMIN_USERNAME}"))
        try:
            await callback.message.answer(reason, reply_markup=b.as_markup())
        except Exception:
            pass
        return await callback.answer("⛔ Urinishlar tugadi!", show_alert=True)
    cid = callback.message.chat.id if callback.message else uid

    # Avvalgi testni to'xtatish
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state,
               TestSolving.paused.state):
        _cancel_timer(uid)
        await state.clear()

    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        test = await get_test_full(tid)
    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions", [])
    if not qs:
        return await callback.answer("❌ Savollar yo'q.", show_alert=True)

    import random, copy
    qs = copy.deepcopy(qs)

    # Demo rejimda savollar sonini cheklaymiz
    if is_demo:
        from handlers.inline_mode import DEMO_MIN, DEMO_MAX
        demo_count = min(DEMO_MAX, max(DEMO_MIN, len(qs) // 3))
        random.shuffle(qs)
        qs = qs[:demo_count]

    # Savollarni aralashtirish (test sozlamasiga qarab)
    if test.get("shuffle_questions", True):
        random.shuffle(qs)

    _shuffle_options(qs)

    await state.set_state(TestSolving.answering)
    await state.set_data({
        "test": test, "qs": qs, "idx": 0, "ans": {},
        "cid": cid, "t0": time.time(), "uid": uid,
        "via_link": test.get("visibility") == "link",
        "no_ans_streak": 0, "q_msg_id": None,
    })

    # Test kartochkasini o'chirmasdan, YANGI xabar sifatida birinchi savol
    await _send_question_new(callback.bot, cid, state, uid)


async def _send_question_new(bot, cid, state, uid):
    """Yangi xabar yuboradi — faqat birinchi savolda yoki pauza qaytganda"""
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)

    # State buzilgan bo'lsa (reboot dan keyin) — tozalash
    if not qs:
        await state.clear()
        from keyboards.keyboards import main_kb
        try:
            await bot.send_message(cid, "⚠️ Test ma'lumoti topilmadi. Qayta boshlang.",
                                   reply_markup=main_kb(uid, "private"))
        except Exception:
            pass
        return

    if idx >= len(qs):
        await _finish_inline(bot, cid, state, d)
        return

    # Rasm bo'lsa — savol oldidan yuborish
    q_first = qs[idx]
    photo_id_first = q_first.get("photo") or q_first.get("image") or None
    if not photo_id_first:
        qtxt_f = re.sub(r'^\[\d+/\d+\]\s*', '', q_first.get("question", q_first.get("text", ""))).strip()
        pm_f = re.match(r'^\[rasm:\s*([^\]]+)\]\s*', qtxt_f)
        if pm_f:
            photo_id_first = pm_f.group(1).strip()
    if photo_id_first:
        try:
            await bot.send_photo(cid, photo_id_first, protect_content=True)
        except Exception as e:
            log.error(f"Inline rasm xato: {e}")
    text, kb, is_text = _build_question_content(qs, idx, time_left=QUESTION_SEC)
    msg = await bot.send_message(cid, text, reply_markup=kb,
        protect_content=True)
    await state.update_data(q_msg_id=msg.message_id, answered_this=False)

    if is_text:
        await state.set_state(TestSolving.text_answer)
    else:
        await state.set_state(TestSolving.answering)

    _cancel_timer(uid)
    task = asyncio.create_task(
        _question_timeout(bot, cid, state, uid, idx, QUESTION_SEC)
    )
    _inline_timers[uid] = task


async def _edit_question(bot, cid, msg_id, state, uid):
    """Mavjud xabarni edit qiladi — keyingi savol"""
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)
    if idx >= len(qs):
        await _finish_inline(bot, cid, state, d)
        return

    text, kb, is_text = _build_question_content(qs, idx, time_left=QUESTION_SEC)
    try:
        await bot.edit_message_text(
            chat_id=cid, message_id=msg_id, text=text, reply_markup=kb
        )
    except TelegramBadRequest:
        # Edit imkoni bo'lmasa yangi yuborish
        msg = await bot.send_message(cid, text, reply_markup=kb,
        protect_content=True)
        msg_id = msg.message_id
        await state.update_data(q_msg_id=msg_id)

    await state.update_data(answered_this=False)
    _cancel_timer(uid)
    task = asyncio.create_task(
        _question_timeout(bot, cid, state, uid, idx, QUESTION_SEC)
    )
    _inline_timers[uid] = task


def _build_question_content(qs, idx, time_left=None):
    """Savol matni va klaviaturasini qurish"""
    total    = len(qs)
    q        = qs[idx]
    qtype    = q.get("type", "multiple_choice")
    qtxt     = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text", "Savol"))).strip()
    rem      = time_left if time_left is not None else QUESTION_SEC
    tbar     = _timer_bar(rem, QUESTION_SEC)

    pause_btn = InlineKeyboardButton(text="⏸ Pauza", callback_data="inline_pause_menu")
    b = InlineKeyboardBuilder()

    if qtype in ("multiple_choice", "multi_select"):
        opts      = q.get("options", [])
        letters   = []
        opt_lines = ""
        for i, opt in enumerate(opts):
            raw = str(opt)
            m   = re.match(r"^([A-Za-z])\s*[).]\s*", raw)
            l   = m.group(1).upper() if m else chr(65+i)
            ot  = raw[m.end():].strip() if m else raw.strip()
            letters.append(l)
            opt_lines += f"{_cl(l)}  {ot}\n"
        text = (
            f"<b>[{idx+1}/{total}]</b>\n"
            f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n\n"
            f"{qtxt}\n\n"
            f"{opt_lines}\n"
            f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            f"   {tbar}⌛"
        )
        for l in letters:
            b.add(InlineKeyboardButton(text=_cl(l), callback_data=f"ans_{l}"))
        b.adjust(len(letters))
        b.row(pause_btn)

    elif qtype == "true_false":
        text = (
            f"<b>[{idx+1}/{total}]</b>\n"
            f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n\n"
            f"{qtxt}\n\n"
            f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            f"   {tbar}⌛"
        )
        b.row(
            InlineKeyboardButton(text="✅ Ha",   callback_data="ans_Ha"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data="ans_Yoq"),
        )
        b.row(pause_btn)

    else:
        text = (
            f"<b>[{idx+1}/{total}]</b>\n"
            f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n\n"
            f"{qtxt}\n\n"
            f"<i>✍️ Javobingizni yozing (xabaringiz avtomatik o'chiriladi)</i>\n\n"
            f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            f"   {tbar}⌛"
        )
        b.row(InlineKeyboardButton(text="⏭ O'tkazish", callback_data="skip_q"))
        b.row(pause_btn)
        return text, b.as_markup(), True

    return text, b.as_markup(), False


async def _question_timeout(bot, cid, state, uid, expected_idx, wait_sec):
    """Flood-safe smart timer.
    Har 5s yangilaydi, oxirida: ...5s, 2s, 1s ko'rsatadi.
    Misol: 12s → update @ 12, 5, 2, 1 (boshlanganda + 3 ta edit)
           30s → update @ 25, 20, 15, 10, 5, 2, 1
    """
    try:
        async def _try_update(remaining):
            d = await state.get_data()
            if d.get("idx") != expected_idx: return False
            if d.get("answered_this"): return False
            msg_id_t = d.get("q_msg_id")
            qs_t     = d.get("qs", [])
            if msg_id_t:
                try:
                    t2, kb2, _ = _build_question_content(qs_t, expected_idx, time_left=remaining)
                    await bot.edit_message_text(chat_id=cid, message_id=msg_id_t,
                                                text=t2, reply_markup=kb2)
                except TelegramBadRequest:
                    pass
                except Exception:
                    pass
            return True

        async def _check_alive():
            cur = await state.get_state()
            if cur not in (TestSolving.answering.state, TestSolving.text_answer.state):
                return False
            d = await state.get_data()
            return d.get("idx") == expected_idx and not d.get("answered_this")

        # Update nuqtalarini dinamik hisoblash:
        # wait_sec boshida ko'rsatiladi, keyin faqat 5, 2, 1
        # Misol: 12 → [12, 5, 2, 1], 30 → [30, 25, 20, 15, 10, 5, 2, 1]
        # Checkpointlar: wait_sec, keyin har 5s, oxirida 5→2→1
        # 12s → [12, 5, 2, 1]  |  30s → [30, 25, 20, 15, 10, 5, 2, 1]
        five_steps = list(range(wait_sec - 5, 10 - 1, -5))  # faqat >5 bo'lgan nuqtalar
        checkpoints = [wait_sec] + five_steps + [5, 2, 1]
        # Tozalash: takror, <=0, wait_sec dan katta olib tashlanadi
        seen = set()
        clean = []
        for c in checkpoints:
            if 0 < c <= wait_sec and c not in seen:
                seen.add(c)
                clean.append(c)
        checkpoints = sorted(clean, reverse=True)

        # Birinchi nuqta — wait_sec o'zi (savol chiqqanda ko'rsatiladi)
        # Shuning uchun birinchi checkpointni skip qilamiz (allaqachon ko'rsatilgan)
        prev = wait_sec
        for target in checkpoints[1:]:  # wait_sec ni o'tkazib yuboramiz
            sleep_for = prev - target
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            if not await _check_alive(): return
            await _try_update(target)
            prev = target

        # Oxirgi 1 soniya kutib, timeout
        await asyncio.sleep(1)

        cur = await state.get_state()
        if cur not in (TestSolving.answering.state, TestSolving.text_answer.state): return
        d = await state.get_data()
        if d.get("idx") != expected_idx: return
        if d.get("answered_this"): return

        # Javob berilmadi — streakni oshir
        streak  = d.get("no_ans_streak", 0) + 1
        ans     = d.get("ans", {})
        ans[str(expected_idx)] = None
        new_idx = expected_idx + 1
        qs      = d.get("qs", [])
        msg_id  = d.get("q_msg_id")

        if streak >= 2:
            # 2 marta ketma-ket javobsiz → pauza
            await state.update_data(ans=ans, idx=new_idx, no_ans_streak=0)
            await state.set_state(TestSolving.paused)
            try:
                await bot.edit_message_text(
                    chat_id=cid, message_id=msg_id,
                    text=(
                        f"⏸ <b>TEST PAUZALAND</b>\n\n"
                        f"Ketma-ket 2 ta savolga javob berilmadi.\n"
                        f"<i>Davom etish yoki to'xtatishni tanlang:</i>"
                    ),
                    reply_markup=inline_pause_kb()
                )
            except TelegramBadRequest:
                await bot.send_message(
                    cid,
                    "⏸ <b>TEST PAUZALAND</b>\n\nDavom etish yoki to'xtatish:",
                    reply_markup=inline_pause_kb()
                ,
        protect_content=True)
        else:
            # Xato deb belgilab, izoh bilan edit qil, 30s keyingi
            q    = qs[expected_idx] if expected_idx < len(qs) else {}
            corr = q.get("correct", "?")
            expl = q.get("explanation", "")
            if expl in ("Izoh kiritilmagan.", "Izoh yo'q", ""): expl = ""
            expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
            qtxt = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text",""))).strip()

            next_kb = InlineKeyboardBuilder()
            next_kb.row(InlineKeyboardButton(text="➡️ Keyingi", callback_data="next_q_now"))

            # Timeout — strikethrough variantlar
            opts_t = ""
            m_ct   = re.match(r"^([A-Za-z])", str(corr).strip())
            c_lt   = m_ct.group(1).upper() if m_ct else ""
            for i3, opt3 in enumerate(q.get("options", [])):
                raw3 = str(opt3)
                mo3  = re.match(r"^([A-Za-z])\s*[).]\s*", raw3)
                l3   = mo3.group(1).upper() if mo3 else chr(65+i3)
                ot3  = raw3[mo3.end():].strip() if mo3 else raw3.strip()
                if l3 == c_lt:
                    opts_t += f"✅ <b>{_cl(l3)}  {ot3}</b>\n"
                else:
                    opts_t += f"<s>{_cl(l3)}  {ot3}</s>\n"
            expl_block_t = f"\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n💡 {expl}" if expl else ""
            text = (
                f"<b>[{expected_idx+1}/{len(qs)}]</b>  ⏰ <b>Vaqt tugadi!</b>\n"
                f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n\n"
                f"{qtxt[:120]}\n\n"
                f"{opts_t}"
                f"{expl_block_t}\n\n"
                f"<i>⏩ {ANSWER_SHOW_SEC}s • yoki keyingiga o'tish:</i>"
            )
            await state.update_data(ans=ans, idx=new_idx, no_ans_streak=streak)
            try:
                await bot.edit_message_text(
                    chat_id=cid, message_id=msg_id, text=text,
                    reply_markup=next_kb.as_markup()
                )
            except TelegramBadRequest: pass

            # ANSWER_SHOW_SEC soniya keyingi savol
            _cancel_timer(uid)
            task = asyncio.create_task(
                _auto_next(bot, cid, state, uid, new_idx, ANSWER_SHOW_SEC)
            )
            _inline_timers[uid] = task

    except asyncio.CancelledError: pass
    except Exception as e: log.error(f"Timeout: {e}")


# ── Javob handler ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data.startswith("ans_"), StateFilter(TestSolving.answering))
async def answer_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    ans_val= callback.data[4:]
    msg_id = callback.message.message_id

    _cancel_timer(uid)
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)
    ans = d.get("ans", {})

    if idx >= len(qs):
        await _finish_inline(callback.bot, cid, state, d)
        return

    q      = qs[idx]
    corr   = q.get("correct", "")
    qtype  = q.get("type", "multiple_choice")

    if qtype == "true_false":
        is_c = (ans_val.lower() == str(corr).strip().lower())
    else:
        m1 = re.match(r"^([A-Za-z])", ans_val)
        m2 = re.match(r"^([A-Za-z])", str(corr).strip())
        is_c = bool(m1 and m2 and m1.group(1).lower() == m2.group(1).lower())

    # To'g'ri javob matni
    opts      = q.get("options", [])
    corr_text = str(corr)
    if qtype == "multiple_choice" and opts:
        m = re.match(r"^([A-Za-z])", str(corr).strip())
        if m:
            ci = ord(m.group(1).upper()) - ord("A")
            if 0 <= ci < len(opts):
                raw  = str(opts[ci])
                mopt = re.match(r"^([A-Za-z])\s*[).]\s*", raw)
                corr_text = f"{m.group(1).upper()}) {raw[mopt.end():].strip() if mopt else raw}"

    expl = q.get("explanation", "") or ""
    if expl in ("Izoh kiritilmagan.", "Izoh yo'q", "Izoh kiritilmagan"): expl = ""
    expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
    qtxt     = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text",""))).strip()

    ans[str(idx)] = ans_val
    new_idx       = idx + 1
    await state.update_data(ans=ans, idx=new_idx, answered_this=True, no_ans_streak=0)

    # Javob natijasini edit qilib ko'rsatish + "Keyingi" tugma
    next_kb = InlineKeyboardBuilder()
    next_kb.row(InlineKeyboardButton(text="➡️ Keyingi savol", callback_data="next_q_now"))

    # Variantlarni strikethrough/bold ko'rsatish
    opts_show = ""
    m_corr = re.match(r"^([A-Za-z])", str(corr).strip())
    c_let  = m_corr.group(1).upper() if m_corr else ""
    m_ans  = re.match(r"^([A-Za-z])", str(ans_val).strip())
    a_let  = m_ans.group(1).upper() if m_ans else ""
    for i2, opt2 in enumerate(q.get("options", [])):
        raw2 = str(opt2)
        mo2  = re.match(r"^([A-Za-z])\s*[).]\s*", raw2)
        l2   = mo2.group(1).upper() if mo2 else chr(65+i2)
        ot2  = raw2[mo2.end():].strip() if mo2 else raw2.strip()
        if l2 == c_let:
            opts_show += f"✅ <b>{_cl(l2)}  {ot2}</b>\n"
        elif l2 == a_let and not is_c:
            opts_show += f"❌ <s>{_cl(l2)}  {ot2}</s>\n"
        else:
            opts_show += f"<s>{_cl(l2)}  {ot2}</s>\n"

    icon   = "✅" if is_c else "❌"
    label  = "To'g'ri!" if is_c else "Noto'g'ri!"
    qtxt_s = qtxt[:120] + ("..." if len(qtxt) > 120 else "")
    expl_block = f"\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n💡 {expl}" if expl else ""
    result_text = (
        f"<b>[{idx+1}/{len(qs)}]</b>\n"
        f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n\n"
        f"{qtxt_s}\n\n"
        f"{opts_show}"
        f"{expl_block}\n\n"
        f"<i>⏩ {ANSWER_SHOW_SEC}s • yoki keyingiga o'tish:</i>"
    )
    try:
        await callback.message.edit_text(result_text, reply_markup=next_kb.as_markup())
    except TelegramBadRequest: pass

    # ANSWER_SHOW_SEC soniyadan keyin keyingi savol — xuddi shu xabarni edit qilamiz
    _cancel_timer(uid)
    task = asyncio.create_task(
        _auto_next(bot=callback.bot, cid=cid, state=state, uid=uid,
                   expected_new_idx=new_idx, wait_sec=ANSWER_SHOW_SEC,
                   msg_id=msg_id)
    )
    _inline_timers[uid] = task


async def _auto_next(bot, cid, state, uid, expected_new_idx, wait_sec, msg_id=None):
    """Javob ko'rsatilgandan keyin ANSWER_SHOW_SEC soniyada keyingi savolga o'tish"""
    try:
        await asyncio.sleep(wait_sec)
        cur = await state.get_state()
        if cur not in (TestSolving.answering.state, TestSolving.text_answer.state): return
        d = await state.get_data()
        if d.get("idx") != expected_new_idx: return

        qs      = d.get("qs", [])
        q_msg_id = msg_id or d.get("q_msg_id")

        if expected_new_idx < len(qs):
            await _show_next_question(bot, cid, q_msg_id, qs, expected_new_idx, state, uid)
        else:
            d_fresh = await state.get_data()
            await _finish_inline(bot, cid, state, d_fresh)

    except asyncio.CancelledError: pass
    except Exception as e: log.error(f"Auto next: {e}")


@router.callback_query(F.data == "next_q_now", StateFilter(TestSolving.answering))
async def next_q_now_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    msg_id = callback.message.message_id
    _cancel_timer(uid)
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)

    if idx < len(qs):
        await _show_next_question(callback.bot, cid, msg_id, qs, idx, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


# ── Matn javob ━━━━━━━━━━━━━━━━━━━━━━━━
@router.message(StateFilter(TestSolving.text_answer))
async def text_answer_handler(message: Message, state: FSMContext):
    uid      = message.from_user.id
    user_ans = message.text.strip()
    _cancel_timer(uid)

    # Foydalanuvchi xabarini o'chirish
    try: await message.delete()
    except: pass

    d     = await state.get_data()
    idx   = d.get("idx", 0)
    qs    = d.get("qs", [])
    if idx >= len(qs): return
    ans   = d.get("ans", {})
    q     = qs[idx]
    cid   = message.chat.id
    q_msg = d.get("q_msg_id")

    # Javobni tekshirish
    corr      = q.get("correct", "")
    accepted  = q.get("accepted_answers", [])
    is_c      = _check_text_answer(user_ans, corr, accepted)

    ans[str(idx)] = user_ans
    new_idx       = idx + 1
    await state.update_data(ans=ans, idx=new_idx, answered_this=True, no_ans_streak=0)
    await state.set_state(TestSolving.answering)

    # Natija xabarini ko'rsatish (edit)
    expl = q.get("explanation", "") or ""
    if expl in ("Izoh kiritilmagan.", "Izoh yo'q", "Izoh kiritilmagan"): expl = ""
    expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
    qtxt     = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text",""))).strip()

    next_kb = InlineKeyboardBuilder()
    next_kb.row(InlineKeyboardButton(text="➡️ Keyingi savol", callback_data="next_q_now"))

    icon_ok  = "✅" if is_c else "❌"
    label_ok = "To'g'ri!" if is_c else "Noto'g'ri!"
    qtxt_s   = qtxt[:80] + ("..." if len(qtxt) > 80 else "")
    result_text = (
        f"{icon_ok} <b>{idx+1}/{len(qs)} — {label_ok}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{qtxt_s}</i>\n\n"
        f"✍️ Sizning: <code>{user_ans[:60]}</code>\n"
        f"✔️ To'g'ri: <b>{str(corr)[:80]}</b>{expl_txt}\n\n"
        f"<i>{ANSWER_SHOW_SEC}s da avtomatik keyingiga o'tadi</i>"
    )
    try:
        if q_msg:
            await message.bot.edit_message_text(
                chat_id=cid, message_id=q_msg,
                text=result_text, reply_markup=next_kb.as_markup()
            )
        else:
            msg = await message.bot.send_message(
                cid, result_text, reply_markup=next_kb.as_markup()
            ,
        protect_content=True)
            await state.update_data(q_msg_id=msg.message_id)
    except TelegramBadRequest:
        msg = await message.bot.send_message(
            cid, result_text, reply_markup=next_kb.as_markup()
        ,
        protect_content=True)
        await state.update_data(q_msg_id=msg.message_id)

    # 30s keyingi savol
    _cancel_timer(uid)
    task = asyncio.create_task(
        _auto_next(bot=message.bot, cid=cid, state=state, uid=uid,
                   expected_new_idx=new_idx, wait_sec=ANSWER_SHOW_SEC,
                   msg_id=q_msg)
    )
    _inline_timers[uid] = task


# ── Skip ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data == "skip_q", StateFilter(TestSolving))
async def skip_q_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    msg_id = callback.message.message_id
    _cancel_timer(uid)
    d   = await state.get_data()
    idx = d.get("idx", 0)
    ans = d.get("ans", {})
    ans[str(idx)] = None
    new_idx = idx + 1
    await state.update_data(ans=ans, idx=new_idx)
    await state.set_state(TestSolving.answering)
    qs = d.get("qs", [])
    if new_idx < len(qs):
        await _show_next_question(callback.bot, cid, msg_id, qs, new_idx, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


# ── Pauza ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data == "inline_pause_menu")
async def inline_pause_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    _cancel_timer(uid)
    await state.set_state(TestSolving.paused)
    d   = await state.get_data()
    tot = len(d.get("qs", []))
    idx = d.get("idx", 0)
    try:
        await callback.message.edit_text(
            f"⏸ <b>PAUZA</b>\n\nSavol {idx}/{tot}\nDavom etish yoki to'xtatish:",
            reply_markup=inline_pause_kb()
        )
    except TelegramBadRequest: pass

@router.callback_query(F.data == "resume_inline", StateFilter(TestSolving.paused))
async def resume_inline(callback: CallbackQuery, state: FSMContext):
    await callback.answer("▶️")
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    msg_id = callback.message.message_id
    await state.set_state(TestSolving.answering)
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)
    if idx < len(qs):
        await _show_next_question(callback.bot, cid, msg_id, qs, idx, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


@router.callback_query(F.data == "cancel_test")
async def cancel_test_cb(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    _cancel_timer(uid)
    await state.clear()
    await callback.answer("❌ To'xtatildi")
    try:
        await callback.message.edit_text("❌ <b>Test to'xtatildi.</b>")
    except TelegramBadRequest: pass
    await callback.bot.send_message(uid, "🏠 Asosiy menyu:", reply_markup=main_kb(uid),
        protect_content=True)


# ── Yakunlash ━━━━━━━━━━━━━━━━━━━━━━━━
async def _finish_inline(bot, cid, state, d):
    from utils.scoring import calculate_score, format_result
    from keyboards.keyboards import result_kb

    test       = d.get("test", {})
    qs         = d.get("qs", [])
    ans        = d.get("ans", {})
    elapsed    = int(time.time() - d.get("t0", time.time()))
    uid        = d.get("uid", cid)
    via_link   = d.get("via_link", False)
    msg_id     = d.get("q_msg_id")
    is_demo    = d.get("is_demo", False)
    is_partial = d.get("is_partial", False)
    _cancel_timer(uid)

    scored = calculate_score(qs, ans)
    scored.update({
        "time_spent":    elapsed,
        "passing_score": test.get("passing_score", 60),
        "mode":          "inline",
        "partial":       is_partial,
        "demo":          is_demo,
    })
    tid = test.get("test_id", "")
    rid = save_result(uid, tid, scored, via_link=via_link)
    await state.clear()

    result_text = format_result(scored, test)
    if is_partial:
        result_text = "⚠️ <b>Test yarim qoldirildi</b>\n\n" + result_text
    kb = result_kb(tid, rid)

    if is_demo:
        from config import ADMIN_USERNAME
        from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
        from aiogram.types import InlineKeyboardButton as _IKBtn
        b = _IKB()
        b.row(_IKBtn(text="📩 To'liq test olish", url=f"https://t.me/{ADMIN_USERNAME}"))
        b.row(_IKBtn(text="🤖 Bot orqali murojat", callback_data="contact_admin"))
        demo_text = (
            f"{result_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 <b>Bu sinov (demo) rejimi edi!</b>\n\n"
            f"To'liq testni olish uchun:\n"
            f"• @{ADMIN_USERNAME} ga yozing\n"
            f"• Yoki quyidagi tugmani bosing 👇"
        )
        if msg_id:
            try:
                await bot.edit_message_text(chat_id=cid, message_id=msg_id,
                    text=demo_text, reply_markup=b.as_markup())
                return
            except TelegramBadRequest: pass
        await bot.send_message(cid, demo_text, reply_markup=b.as_markup(), protect_content=True)
        return

    if msg_id:
        try:
            await bot.edit_message_text(chat_id=cid, message_id=msg_id,
                text=result_text, reply_markup=kb)
            return
        except TelegramBadRequest: pass

    await bot.send_message(cid, result_text, reply_markup=kb, protect_content=True)
