"""
🗓 GROUP SCHEDULER — Guruh uchun avtomatik test rejalashtirish

BUYRUQLAR:
  /start_create <id1, id2, ...>  — ro'yxat yaratish
  /set_tests                     — ro'yxatni ko'rish/tahrirlash
  /start_set                     — testlarni boshlash
  /stop_set                      — to'xtatish
  /quiz_stop                     — joriy testni to'xtatib keyingi ovozga o'tish

OVOZ TARTIBI:
  - Har safar BARCHA testlar ovozda ko'rsatiladi (kamaymayin)
  - Ko'p ovoz → o'sha test boshlanadi
  - Hech kim ovoz bermasa → random (avval o'tkazilganlardan tashqari)
  - Agar random oldin o'tkazilganini tanlasa → yana random qayta
"""

import asyncio, logging, random, re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils.ram_cache import get_test_meta

log    = logging.getLogger(__name__)
router = Router()

_schedules: dict = {}
VOTE_SECONDS = 30


# ── Yordamchilar ──────────────────────────────────────────────

def _extract_ids(text: str) -> list:
    return list(dict.fromkeys(re.findall(r'\b[A-Z0-9]{6,10}\b', text.upper())))

async def _is_admin(bot, chat_id, uid):
    try:
        m = await bot.get_chat_member(chat_id, uid)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

def _get_qc(tid: str) -> int:
    """Savollar soni — meta dan yoki to'liq testdan."""
    meta = get_test_meta(tid) or {}
    qc   = meta.get("question_count", 0)
    if not qc:
        # RAM cache dan tekshiramiz
        from utils import ram_cache as ram
        cached = ram.get_cached_questions(tid)
        if cached:
            qc = len(cached.get("questions", []))
    return qc

def _tests_list_text(chat_id, title="📋 TESTLAR RO'YXATI") -> str:
    sched = _schedules.get(chat_id, {})
    tests = sched.get("tests", [])
    if not tests:
        return f"<b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nRo'yxat bo'sh."
    done    = set(sched.get("done", []))
    cur     = sched.get("current_tid")
    text    = f"<b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nJami: <b>{len(tests)} ta</b>\n\n"
    for i, tid in enumerate(tests, 1):
        meta  = get_test_meta(tid) or {}
        name  = meta.get("title", tid)[:25]
        qc    = _get_qc(tid)
        sc    = meta.get("solve_count", 0)
        icon  = "▶️" if tid == cur else ("✅" if tid in done else "📝")
        text += f"{icon} {i}. <b>{name}</b>"
        if qc:
            text += f" ({qc} savol)"
        if sc:
            text += f" | 👥{sc}"
        text += f"\n   <code>{tid}</code>\n\n"
    return text.strip()

def _list_kb(chat_id) -> object:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="▶️ Testlarni boshlash",
        callback_data=f"sch_start_{chat_id}"
    ))
    b.row(
        InlineKeyboardButton(text="➕ Test qo'shish", callback_data=f"sch_add_{chat_id}"),
        InlineKeyboardButton(text="🗑 Tozalash",       callback_data=f"sch_clear_{chat_id}"),
    )
    sched = _schedules.get(chat_id, {})
    for tid in sched.get("tests", []):
        meta = get_test_meta(tid) or {}
        name = meta.get("title", tid)[:22]
        b.row(InlineKeyboardButton(
            text=f"➖ {name}",
            callback_data=f"sch_del_{chat_id}_{tid}"
        ))
    b.row(InlineKeyboardButton(text="❌ Yopish", callback_data=f"sch_close_{chat_id}"))
    return b.as_markup()


# ══ /start_create ════════════════════════════════════════════

@router.message(Command("start_create", ignore_mention=True))
async def cmd_start_create(message: Message):
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda!")
    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    args = message.text.split(None, 1)
    raw  = args[1] if len(args) > 1 else ""
    tids = _extract_ids(raw)

    if not tids:
        return await message.answer(
            "❌ Test ID kiritilmadi.\n\nNamuna:\n"
            "<code>/start_create A36D37BE, 11D13889, 7D71EE2E</code>"
        )

    valid, invalid = [], []
    for tid in tids:
        meta = get_test_meta(tid)
        if meta and meta.get("is_active", True):
            if tid not in valid:
                valid.append(tid)
        else:
            invalid.append(tid)

    if not valid:
        return await message.answer("❌ Hech qanday to'g'ri test topilmadi!")

    _schedules[chat_id] = {
        "tests":       valid,
        "done":        [],
        "current_tid": None,
        "active":      False,
        "host_id":     uid,
        "task":        None,
    }

    text = _tests_list_text(chat_id, "✅ RO'YXAT YARATILDI")
    if invalid:
        text += f"\n\n⚠️ Topilmadi: {', '.join(f'<code>{t}</code>' for t in invalid)}"

    await message.answer(text, reply_markup=_list_kb(chat_id))


# ══ /set_tests ═══════════════════════════════════════════════

@router.message(Command("set_tests", ignore_mention=True))
async def cmd_set_tests(message: Message):
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda!")
    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    args = message.text.split(None, 1)
    if len(args) > 1:
        tids = _extract_ids(args[1])
        if tids:
            if chat_id not in _schedules:
                _schedules[chat_id] = {"tests": [], "done": [], "active": False}
            current = _schedules[chat_id].get("tests", [])
            for tid in tids:
                meta = get_test_meta(tid)
                if meta and meta.get("is_active", True) and tid not in current:
                    current.append(tid)
            _schedules[chat_id]["tests"] = current

    await message.answer(
        _tests_list_text(chat_id),
        reply_markup=_list_kb(chat_id)
    )


# ══ /start_set ═══════════════════════════════════════════════

@router.message(Command("start_set", "start_sets", ignore_mention=True))
async def cmd_start_set(message: Message):
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda!")
    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    sched = _schedules.get(chat_id, {})
    if not sched.get("tests"):
        return await message.answer(
            "❌ Ro'yxat yo'q!\n\n"
            "<code>/start_create ID1, ID2, ID3</code>"
        )
    if sched.get("active"):
        return await message.answer(
            "⚠️ Allaqachon boshlangan!\n<code>/stop_set</code>"
        )

    n = len(sched["tests"])
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Boshlash", callback_data=f"sch_start_{chat_id}"),
        InlineKeyboardButton(text="❌ Bekor",    callback_data=f"sch_close_{chat_id}"),
    )
    await message.answer(
        f"🎯 <b>BOSHLASHGA TAYYORMISIZ?</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Testlar: <b>{n} ta</b>\n"
        f"📊 Rejim: <b>Quiz Poll</b>\n"
        f"🗳 Har test oldidan {VOTE_SECONDS}s ovoz",
        reply_markup=b.as_markup()
    )


# ══ /stop_set ════════════════════════════════════════════════

@router.message(Command("stop_set", "stop_sets", ignore_mention=True))
async def cmd_stop_set(message: Message):
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda!")
    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    sched = _schedules.get(chat_id)
    if not sched:
        return await message.answer("ℹ️ Faol jarayon yo'q.")

    was_active  = sched.get("active", False)
    done        = list(sched.get("done", []))
    tests       = list(sched.get("tests", []))
    current_tid = sched.get("current_tid")

    await _kill_schedule(chat_id)
    _schedules.pop(chat_id, None)

    if not was_active:
        return await message.answer("✅ Ro'yxat o'chirildi.")

    # Natija matni
    lines = [
        "⏹ <b>TO'XTATILDI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"✅ O'tkazildi: <b>{len(done)} / {len(tests)} ta</b>",
    ]

    if current_tid:
        cur_meta = get_test_meta(current_tid) or {}
        lines.append(f"⚠️ To'xtatilgan test: <b>{cur_meta.get('title', current_tid)}</b>")

    # Fan bo'yicha statistika
    if done:
        cat_counts = {}
        for tid in done:
            meta = get_test_meta(tid) or {}
            cat  = meta.get("category") or meta.get("subject") or "Boshqa"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        lines.append("")
        lines.append("📊 <b>Fan bo'yicha natija:</b>")
        for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  • {cat}: <b>{cnt} ta</b>")

    lines.append("")
    lines.append("Qayta boshlash: <code>/start_set</code>")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def _kill_schedule(chat_id):
    """Scheduler va joriy testni to'xtatish."""
    sched = _schedules.get(chat_id, {})
    sched["active"] = False

    task = sched.get("task")
    if task and not task.done():
        task.cancel()

    from handlers.group import _group_sessions, _inline_sessions
    for sessions in (_group_sessions, _inline_sessions):
        if chat_id in sessions:
            t = sessions[chat_id].get("task")
            if t and not t.done():
                t.cancel()
            sessions.pop(chat_id, None)


# ══ Callback handlerlar ═══════════════════════════════════════

@router.callback_query(F.data.startswith("sch_start_"))
async def sch_start_cb(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data[10:])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    sched = _schedules.get(chat_id, {})
    if not sched.get("tests"):
        return await callback.answer("❌ Ro'yxat bo'sh!", show_alert=True)
    if sched.get("active"):
        return await callback.answer("⚠️ Allaqachon boshlangan!", show_alert=True)

    try: await callback.message.delete()
    except: pass

    await _start_schedule(callback.bot, chat_id, uid)


@router.callback_query(F.data.startswith("sch_add_"))
async def sch_add_cb(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data[8:])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    if chat_id not in _schedules:
        _schedules[chat_id] = {"tests": [], "done": [], "active": False}
    _schedules[chat_id]["waiting_input"] = uid

    await callback.message.answer(
        "➕ <b>TEST KODI YUBORING</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<code>AB12CD34</code>\n"
        "yoki: <code>AB12, CD34, EF56</code>"
    )


@router.callback_query(F.data.startswith("sch_del_"))
async def sch_del_cb(callback: CallbackQuery):
    await callback.answer()
    parts   = callback.data.split("_")
    chat_id = int(parts[2])
    tid     = parts[3]
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    sched = _schedules.get(chat_id, {})
    tests = sched.get("tests", [])
    if tid in tests:
        tests.remove(tid)
        sched["tests"] = tests

    try:
        await callback.message.edit_text(
            _tests_list_text(chat_id), reply_markup=_list_kb(chat_id)
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("sch_clear_"))
async def sch_clear_cb(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data[10:])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    if chat_id in _schedules:
        _schedules[chat_id].update({"tests": [], "done": [], "current_tid": None})

    try:
        await callback.message.edit_text(
            _tests_list_text(chat_id), reply_markup=_list_kb(chat_id)
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("sch_close_"))
async def sch_close_cb(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass


# ══ Matn orqali test ID qo'shish ═════════════════════════════

@router.message(F.text & F.chat.type.in_({"group", "supergroup"}))
async def handle_test_ids_input(message: Message):
    chat_id = message.chat.id
    uid     = message.from_user.id
    sched   = _schedules.get(chat_id, {})

    # Command xabarlarini o'tkazib yuborish
    if message.text and message.text.startswith("/"):
        return

    if sched.get("waiting_input") != uid:
        return

    tids = _extract_ids(message.text or "")
    if not tids:
        await message.answer("❌ Test ID topilmadi. Masalan: <code>AB12CD34</code>")
        return

    _schedules[chat_id].pop("waiting_input", None)
    current = _schedules[chat_id].get("tests", [])
    added   = []
    for tid in tids:
        meta = get_test_meta(tid)
        if meta and meta.get("is_active", True) and tid not in current:
            current.append(tid)
            added.append(tid)
    _schedules[chat_id]["tests"] = current

    text = _tests_list_text(chat_id)
    if added:
        text = f"✅ {len(added)} ta qo'shildi!\n\n" + text
    await message.answer(text, reply_markup=_list_kb(chat_id))


# ══ Scheduler ════════════════════════════════════════════════

async def _start_schedule(bot, chat_id, uid):
    sched = _schedules.setdefault(chat_id, {})
    sched.update({
        "active":      True,
        "host_id":     uid,
        "done":        sched.get("done") or [],
        "current_tid": None,
    })

    tests = sched.get("tests", [])
    await bot.send_message(
        chat_id,
        f"🚀 <b>TEST SERIYASI BOSHLANDI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 {len(tests)} ta test | 📊 Quiz Poll rejimi\n"
        f"🗳 Har test oldidan {VOTE_SECONDS}s ovoz\n\n"
        f"⏸ Joriy testni to'xtatish: <code>/quiz_stop</code>\n"
        f"⏹ Hammani to'xtatish: <code>/stop_set</code>",
    )

    task = asyncio.create_task(_scheduler_loop(bot, chat_id))
    sched["task"] = task


async def _scheduler_loop(bot, chat_id):
    try:
        while True:
            sched = _schedules.get(chat_id)
            if not sched or not sched.get("active"):
                break

            tests = sched.get("tests", [])
            if not tests:
                break

            # Ovoz — BARCHA testlar ko'rsatiladi
            tid = await _run_vote(bot, chat_id, tests, sched.get("done", []))
            if tid is None:
                break

            sched["current_tid"] = tid
            if tid not in sched.get("done", []):
                sched["done"].append(tid)

            # Test boshlash xabari (o'zi o'chadi)
            info_msg = await bot.send_message(
                chat_id,
                f"▶️ <b>{(get_test_meta(tid) or {}).get('title', tid)}</b> boshlanmoqda..."
            )

            await asyncio.sleep(2)

            # Testni boshlash
            from handlers.group import _start_group_test
            await _start_group_test(bot, chat_id, sched["host_id"], tid, "poll")

            # Info xabarni o'chirish
            try: await bot.delete_message(chat_id, info_msg.message_id)
            except: pass

            # Test tugashini kutish
            await _wait_for_test(bot, chat_id)

            sched = _schedules.get(chat_id)
            if not sched or not sched.get("active"):
                break

            sched["current_tid"] = None
            await asyncio.sleep(2)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"Scheduler xato ({chat_id}): {e}")
        import traceback; traceback.print_exc()


def _timer_text(remaining: int) -> str:
    """Timer xabari matni — progress bar bilan."""
    total  = VOTE_SECONDS
    filled = round((total - remaining) / total * 10)
    bar    = "▓" * filled + "░" * (10 - filled)
    if remaining <= 5:
        return f"⏱ <b>{remaining}s</b> qoldi [{bar}] 🔴"
    elif remaining <= 15:
        return f"⏱ <b>{remaining}s</b> qoldi [{bar}] 🟡"
    else:
        return f"⏱ <b>{remaining}s</b> qoldi [{bar}] 🟢"


def _vote_option(tid: str) -> str:
    """Ovoz uchun variant matni — fan emojisi + test nomi."""
    from keyboards.keyboards import get_cat_icon
    meta  = get_test_meta(tid) or {}
    name  = meta.get("title", tid)[:25]
    cat   = meta.get("category", "")
    qc    = _get_qc(tid)
    icon  = get_cat_icon(cat) if cat else "📝"
    opt   = f"{icon} {name}"
    if qc:
        opt += f" ({qc}❓)"
    return opt


async def _run_vote(bot, chat_id, tests, done):
    """
    Ovoz — BARCHA testlar ko'rsatiladi.
    Ko'p ovoz → o'sha test.
    Hech kim ovoz bermasa → random (avval o'tkazilmagan birinchi, aks holda istalgan).
    """
    sched = _schedules.get(chat_id)
    if not sched or not sched.get("active"):
        return None

    # Max 8 ta variant (Telegram chegarasi)
    vote_tids = tests[:8]
    options   = []
    for tid in vote_tids:
        meta = get_test_meta(tid) or {}
        name = meta.get("title", tid)[:25]
        qc   = _get_qc(tid)
        opt  = f"📝 {name}"
        if qc:
            opt += f" ({qc}❓)"
        options.append(opt)

    vote_msg = None
    try:
        vote_msg = await bot.send_poll(
            chat_id,
            question=f"🗳 Keyingi test? ({VOTE_SECONDS}s)",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=VOTE_SECONDS,
            protect_content=True,
        )
        sched["vote_msg_id"]  = vote_msg.message_id
        sched["vote_poll_id"] = vote_msg.poll.id
        sched["vote_tids"]    = vote_tids
    except Exception as e:
        log.error(f"Ovoz ochishda xato: {e}")
        not_done = [t for t in tests if t not in done]
        return random.choice(not_done) if not_done else random.choice(tests)

    # Vaqt tugashini kutish — poll o'zi yopiladi (open_period)
    await asyncio.sleep(VOTE_SECONDS + 1)

    sched = _schedules.get(chat_id)
    if not sched or not sched.get("active"):
        return None

    # Natijalar hisoblanmoqda xabari
    calc_msg = None
    try:
        calc_msg = await bot.send_message(
            chat_id,
            "🗳 Ovoz berish vaqti tugadi\n⏳ Natijalar hisoblanmoqda...",
            parse_mode="HTML",
        )
    except: pass

    await asyncio.sleep(2)

    # vote_counts dan g'olibni aniqlaymiz
    vote_counts = sched.get("vote_counts", {})
    chosen = None

    if vote_counts:
        # Eng ko'p ovoz olgan variant
        best_idx = max(vote_counts, key=lambda k: vote_counts[k])
        idx = int(best_idx)
        if 0 <= idx < len(vote_tids):
            chosen = vote_tids[idx]

    # Hech kim ovoz bermasa — random
    if not chosen:
        not_done = [t for t in tests if t not in done]
        chosen   = random.choice(not_done) if not_done else random.choice(tests)

    # Natija xabarini o'chir
    if calc_msg:
        try: await bot.delete_message(chat_id, calc_msg.message_id)
        except: pass

    # vote_counts ni tozalash — keyingi ovoz uchun
    sched["vote_counts"] = {}

    return chosen


async def _wait_for_test(bot, chat_id):
    """Test tugashini kutish."""
    from handlers.group import _group_sessions, _inline_sessions
    # Birinchi test sessiyasi boshlanguncha kichik kutish
    await asyncio.sleep(3)
    for _ in range(7200):  # max 2 soat
        await asyncio.sleep(1)
        sched = _schedules.get(chat_id)
        if not sched or not sched.get("active"):
            return
        if chat_id not in _group_sessions and chat_id not in _inline_sessions:
            return


# ══ Poll answer ═══════════════════════════════════════════════

@router.poll_answer()
async def scheduler_poll_answer(poll_answer):
    """Ovoz javoblarini qayd etish."""
    poll_id = poll_answer.poll_id
    for sched in _schedules.values():
        if sched.get("vote_poll_id") == poll_id:
            # Ovozni vote_counts da saqlab boramiz
            opt_ids = poll_answer.option_ids
            if opt_ids:
                if "vote_counts" not in sched:
                    sched["vote_counts"] = {}
                idx = str(opt_ids[0])
                sched["vote_counts"][idx] = sched["vote_counts"].get(idx, 0) + 1
            break
