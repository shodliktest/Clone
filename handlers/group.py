"""👥 GURUH REJIMI — Quiz Poll + Inline (tugmalar + countdown)
================================================================
POLL USULI:   group_start_<tid>  → Telegram native poll
INLINE USULI: group_inline_<tid> → Inline tugmalar + countdown timer

Qaysi usul:
  - "📊 Quiz Poll"        → start_poll_ (private) yoki group_start_ (guruh)
  - "👥 Guruhda (Inline)" → group_inline_<tid>

Natijalar:
  - Poll usuli: PollAnswer orqali kim qaysi variantni bosganini bilamiz
  - Inline usuli: callback_query orqali
  - Ikkalasida ham: calculate_score → save_result → rasm leaderboard
"""
import asyncio
import logging
import re
from typing import Dict, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, PollAnswer,
    InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from utils.ram_cache import get_test_by_id, is_test_paused
from utils.db import get_test_full, save_result
from utils.scoring import calculate_score

log    = logging.getLogger(__name__)

def _shuffle_options(qs):
    """Variantlarni aralashtiradi, label qayta tartiblanadi (A B C D o'z joyida)."""
    import re as _re, random
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
        random.shuffle(pure)
        q["options"] = [f"{LABELS[i]}) {t}" for i, t in enumerate(pure)]
        if corr_text is not None:
            new_idx = next((i for i,t in enumerate(pure) if t == corr_text), 0)
            q["correct"] = f"{LABELS[new_idx]}) {corr_text}"



router = Router()

LETTERS      = ["A","B","C","D","E","F","G","H","I","J"]
COUNT_EMOJIS = ["3️⃣", "2️⃣", "1️⃣", "🎯"]

# ─── Sessiyalar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━────
# Poll sessiyasi: {chat_id: {...}}
_group_sessions: Dict[int, dict] = {}

# Inline sessiyasi: {chat_id: {...}}
_inline_sessions: Dict[int, dict] = {}


# ══════════════════════════════════════════════════════════════
# POLL ANSWER ROUTING (poll_router.py dan chaqiriladi)
# ══════════════════════════════════════════════════════════════

async def route_poll_answer(poll_answer: PollAnswer) -> bool:
    poll_id     = poll_answer.poll_id
    target_chat = None
    for chat_id, session in _group_sessions.items():
        if poll_id in session.get("poll_map", {}):
            target_chat = chat_id
            break
    if target_chat is None:
        return False
    if not poll_answer.option_ids:
        return True
    session = _group_sessions[target_chat]
    uid_str = str(poll_answer.user.id)
    q_idx   = session["poll_map"][poll_id]
    if uid_str not in session["answers"]:
        session["answers"][uid_str] = {}
    session["names"][uid_str] = poll_answer.user.full_name
    opt_idx = poll_answer.option_ids[0]
    q = session["questions"][q_idx] if q_idx < len(session["questions"]) else {}
    if q.get("type") == "true_false":
        letter = "Ha" if opt_idx == 0 else "Yo'q"
    else:
        letter = LETTERS[opt_idx] if opt_idx < len(LETTERS) else str(opt_idx)
    session["answers"][uid_str][str(q_idx)] = letter
    return True


# ══════════════════════════════════════════════════════════════
# YORDAMCHI: TEST YUKLASH
# ══════════════════════════════════════════════════════════════

async def _load_test(bot, chat_id: int, tid: str) -> Optional[dict]:
    """Test RAMdan yoki TGdan yuklanadi."""
    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        try:
            wm = await bot.send_message(chat_id, "⏳ <b>Test yuklanmoqda...</b>", protect_content=True)
        except Exception:
            wm = None
        test = await get_test_full(tid)
        if wm:
            try: await wm.delete()
            except: pass
    return test or None


# ══════════════════════════════════════════════════════════════
# POLL USULI
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("group_start_"))
async def group_start_poll(callback: CallbackQuery):
    await callback.answer()
    tid = callback.data[12:]
    uid = callback.from_user.id

    # Inline message dan kelganda callback.message = None
    if callback.message is None:
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va o'sha yerda bosing.",
            show_alert=True
        )

    chat    = callback.message.chat
    chat_id = chat.id

    if chat.type not in ("group","supergroup"):
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va u yerda bosing.",
            show_alert=True
        )
    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)
    if chat_id in _group_sessions:
        return await callback.answer(
            "⚠️ Guruhda allaqachon test ketmoqda!\n"
            "Avval uni tugating.", show_alert=True
        )
    if chat_id in _inline_sessions:
        return await callback.answer(
            "⚠️ Guruhda inline test ketmoqda!\n"
            "Avval uni tugating.", show_alert=True
        )

    test = await _load_test(callback.bot, chat_id, tid)
    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = [q for q in test.get("questions",[])
          if q.get("type","multiple_choice") in ("multiple_choice","true_false")]
    if not qs:
        return await callback.answer(
            "⚠️ Bu testda quiz poll uchun savollar yo'q!", show_alert=True
        )

    poll_time = test.get("poll_time", 30) or 30

    import random, copy
    qs = copy.deepcopy(qs)
    if test.get("shuffle_questions", True):
        random.shuffle(qs)
    _shuffle_options(qs)

    _group_sessions[chat_id] = {
        "tid": tid, "test": test, "questions": qs,
        "answers": {}, "names": {}, "poll_map": {},
        "host_id": uid, "poll_time": poll_time, "task": None,
    }

    try: await callback.message.delete()
    except: pass

    cdown = await callback.bot.send_message(chat_id, f"📝 <b>{test.get('title')}</b>", protect_content=True)
    for emoji in COUNT_EMOJIS:
        await asyncio.sleep(0.8)
        try: await cdown.edit_text(emoji)
        except: pass
    await asyncio.sleep(0.5)
    try: await cdown.delete()
    except: pass

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ Testni to'xtatish", callback_data=f"gstop_{uid}"))
    skipped  = len(test.get("questions",[])) - len(qs)
    skip_txt = f"\n⚠️ <i>{skipped} ta matn savol o'tkazildi</i>" if skipped else ""
    await callback.bot.send_message(
        chat_id,
        f"🚀 <b>TEST BOSHLANDI!</b> | {len(qs)} savol | ⏱{poll_time}s{skip_txt}\n"
        f"📢 Hamma qatnashing!",
        reply_markup=b.as_markup()
    ,
        protect_content=True)

    task = asyncio.create_task(
        _run_group_polls(callback.bot, chat_id, tid, qs, poll_time)
    )
    _group_sessions[chat_id]["task"] = task


async def _run_group_polls(bot, chat_id: int, tid: str, qs: list, poll_time: int):
    for i, q in enumerate(qs):
        if chat_id not in _group_sessions:
            return
        session = _group_sessions[chat_id]
        qtype   = q.get("type","multiple_choice")
        opts    = q.get("options",[])
        if qtype == "true_false":
            opts = ["Ha","Yo'q"]
        clean_opts = []
        for opt in opts:
            ot = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
            clean_opts.append(ot[:100])
        if not clean_opts:
            continue

        corr = q.get("correct","")
        if qtype == "true_false":
            ci = 0 if "ha" in str(corr).lower() else 1
        elif isinstance(corr, int):
            ci = corr
        else:
            m  = re.match(r"^([A-Za-z])", str(corr).strip())
            ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
        ci = max(0, min(ci, len(clean_opts)-1))

        expl = q.get("explanation") or None
        if expl and expl in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"):
            expl = None
        if expl and len(expl) > 195:
            expl = expl[:195] + "..."

        qtxt = q.get("question", q.get("text","Savol"))
        qtxt = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt).strip()

        # Savol ichidan [rasm: file_id] ni ajratib olish
        photo_id = q.get("photo") or q.get("image") or None
        if not photo_id:
            pm_match = re.match(r'^\[rasm:\s*([^\]]+)\]\s*', qtxt)
            if pm_match:
                photo_id = pm_match.group(1).strip()
                qtxt     = qtxt[pm_match.end():].strip()

        total    = len(qs)
        current  = i + 1
        hdr_poll = f"【{current}/{total}】"
        if len(hdr_poll + qtxt) > 295:
            qtxt = qtxt[:295 - len(hdr_poll)] + "..."

        prog_msg = None

        # Rasm bo'lsa — poll oldidan yuborish
        if photo_id:
            try:
                await bot.send_photo(chat_id, photo_id, protect_content=True)
                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"Rasm yuborishda xato (savol {current}): {e}")

        try:
            pm = await bot.send_poll(
                chat_id=chat_id,
                question=hdr_poll + qtxt,
                options=clean_opts,
                type="quiz",
                correct_option_id=ci,
                explanation=expl,
                open_period=poll_time if poll_time > 0 else None,
                is_anonymous=False,
                allows_multiple_answers=False,
                protect_content=True,
            )
            if chat_id in _group_sessions:
                _group_sessions[chat_id]["poll_map"][pm.poll.id] = i
            wait = (poll_time + 2) if poll_time > 0 else 10
            await asyncio.sleep(wait)
            # Progress xabarni o'chir
            if prog_msg:
                try: await bot.delete_message(chat_id, prog_msg.message_id)
                except: pass
        except TelegramBadRequest as e:
            log.error(f"Guruh poll xato (savol {i+1}): {e}")
            if "not enough rights" in str(e).lower():
                try:
                    await bot.send_message(
                        chat_id,
                        "❌ <b>Bot poll yubora olmadi!</b>\n"
                        "Botga guruhda admin yoki poll yuborish huquqi bering."
                    ,
                        protect_content=True)
                except: pass
                _group_sessions.pop(chat_id, None)
                return
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Poll xato: {e}")
            await asyncio.sleep(2)

    if chat_id in _group_sessions:
        await asyncio.sleep(3)
        await _show_group_leaderboard(bot, chat_id, tid)
        _group_sessions.pop(chat_id, None)


# ══════════════════════════════════════════════════════════════
# INLINE USULI (tugmalar + countdown timer)
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("group_inline_"))
async def group_start_inline(callback: CallbackQuery):
    await callback.answer()
    tid = callback.data[13:]
    uid = callback.from_user.id

    # Inline message dan kelganda callback.message = None
    if callback.message is None:
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va o'sha yerda bosing.",
            show_alert=True
        )

    chat    = callback.message.chat
    chat_id = chat.id

    if chat.type not in ("group","supergroup"):
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va u yerda bosing.",
            show_alert=True
        )
    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)
    if chat_id in _group_sessions:
        return await callback.answer(
            "⚠️ Guruhda poll testi ketmoqda!\nAvval uni tugating.", show_alert=True
        )
    if chat_id in _inline_sessions:
        return await callback.answer(
            "⚠️ Guruhda allaqachon test ketmoqda!\nAvval uni tugating.", show_alert=True
        )

    test = await _load_test(callback.bot, chat_id, tid)
    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions", [])
    if not qs:
        return await callback.answer("⚠️ Bu testda savollar yo'q!", show_alert=True)

    import random, copy
    qs = copy.deepcopy(qs)
    if test.get("shuffle_questions", True):
        random.shuffle(qs)
    _shuffle_options(qs)

    poll_time     = test.get("poll_time", 30) or 30
    passing_score = float(test.get("passing_score", 60))

    _inline_sessions[chat_id] = {
        "tid":           tid,
        "test":          test,
        "questions":     qs,
        "answers":       {},          # {uid_str: {q_idx_str: answer_letter}}
        "names":         {},          # {uid_str: full_name}
        "host_id":       uid,
        "poll_time":     poll_time,
        "passing_score": passing_score,
        "cur_q":         0,
        "q_msg_id":      None,
        "task":          None,
        "locked":        False,
    }

    try: await callback.message.delete()
    except: pass

    # Countdown
    cdown = await callback.bot.send_message(chat_id, f"📝 <b>{test.get('title')}</b>", protect_content=True)
    for emoji in COUNT_EMOJIS:
        await asyncio.sleep(0.8)
        try: await cdown.edit_text(emoji)
        except: pass
    await asyncio.sleep(0.5)
    try: await cdown.delete()
    except: pass

    # Boshlanish xabari
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ To'xtatish", callback_data=f"gi_stop_{uid}"))
    await callback.bot.send_message(
        chat_id,
        f"🚀 <b>INLINE TEST BOSHLANDI!</b>\n"
        f"📝 {test.get('title')} | {len(qs)} savol | ⏱{poll_time}s\n"
        f"📢 Tugmalar orqali javob bering!",
        reply_markup=b.as_markup()
    ,
        protect_content=True)

    task = asyncio.create_task(
        _run_inline_session(callback.bot, chat_id, tid, qs, poll_time, passing_score)
    )
    _inline_sessions[chat_id]["task"] = task


async def _flood_safe_send(bot, chat_id: int, text: str,
                            reply_markup=None, max_retries: int = 4):
    """Flood control ni hisobga olgan holda xabar yuboradi."""
    for attempt in range(max_retries):
        try:
            return await bot.send_message(
                chat_id, text,
                parse_mode="HTML", reply_markup=reply_markup
            ,
                protect_content=True)
        except TelegramBadRequest as e:
            log.error(f"Bad request: {e}")
            return None
        except Exception as e:
            err = str(e).lower()
            if "retry after" in err or "flood" in err or "too many" in err:
                m    = re.search(r"retry after (\d+)", err)
                wait = int(m.group(1)) + 2 if m else 25
                log.warning(f"⏳ Flood control — {wait}s (urinish {attempt+1}/{max_retries})")
                await asyncio.sleep(wait)
            else:
                log.error(f"SendMessage xato: {e}")
                return None
    log.error(f"Flood: {max_retries} urinishdan keyin ham yuborilmadi")
    return None


async def _run_inline_session(
    bot, chat_id: int, tid: str,
    qs: list, poll_time: int, passing_score: float
):
    """Inline sessiya: har savol uchun tugmalar + countdown."""
    for i, q in enumerate(qs):
        # Sessiya hali ham aktiv ekanligini tekshirish
        if chat_id not in _inline_sessions:
            return

        session = _inline_sessions[chat_id]
        session["cur_q"]  = i
        session["locked"] = False

        opts  = q.get("options", [])
        qtype = q.get("type","multiple_choice")
        if qtype == "true_false":
            opts = ["Ha","Yo'q"]
        qtxt = q.get("question", q.get("text","Savol"))
        qtxt = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt).strip()

        # ── Rasm bo'lsa — savol oldidan yuborish ──
        photo_id = q.get("photo") or q.get("image") or None
        if not photo_id:
            pm_match = re.match(r'^\[rasm:\s*([^\]]+)\]\s*', qtxt)
            if pm_match:
                photo_id = pm_match.group(1).strip()
                qtxt     = qtxt[pm_match.end():].strip()
        if photo_id:
            try:
                await bot.send_photo(chat_id, photo_id, protect_content=True)
                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"Inline rasm yuborishda xato (savol {i+1}): {e}")

        # ── Savol xabarini yasash ──
        def _q_text(remaining: int) -> str:
            filled = int((poll_time - remaining) / poll_time * 10) if poll_time else 0
            bar    = "■" * filled + "□" * (10 - filled)
            pct    = int((poll_time - remaining) / poll_time * 100) if poll_time else 0
            opt_labels = ["🅐","🅑","🅒","🅓","🅔","🅕"]
            opts_disp  = "\n".join(
                f"  {opt_labels[j]}  {str(o).split(')',1)[-1].strip() if ')' in str(o) else str(o)}"
                for j, o in enumerate(opts[:6])
            )
            return (
                f"❓ <b>{i+1}/{len(qs)}. Savol</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{qtxt}\n\n"
                f"{opts_disp}\n\n"
                f"{bar} {pct}%  ⏱ <b>{remaining}s</b>"
            )

        # ── Klaviatura ──
        def _build_kb():
            labels = ["🅐","🅑","🅒","🅓","🅔","🅕"]
            btns   = []
            for j, opt in enumerate(opts[:6]):
                opt_clean = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
                btns.append([InlineKeyboardButton(
                    text=f"{labels[j]}  {opt_clean[:40]}",
                    callback_data=f"gi_ans:{chat_id}:{i}:{j}"
                )])
            return InlineKeyboardMarkup(inline_keyboard=btns)

        kb  = _build_kb()
        msg = await _flood_safe_send(bot, chat_id, _q_text(poll_time), reply_markup=kb)

        if not msg:
            # Yuborib bo'lmadi — sessiyani tugatish
            log.error(f"Savol {i+1} yuborilmadi — sessiya tugatilmoqda")
            _inline_sessions.pop(chat_id, None)
            return

        session["q_msg_id"] = msg.message_id

        # ── Countdown timer (flood-safe) ──
        # Checkpointlar: poll_time, ..., 10, 5, 2, 1
        # Misol: 12s → [12, 5, 2, 1] | 30s → [30, 25, 20, 15, 10, 5, 2, 1]
        five_steps = list(range(poll_time - 5, 10 - 1, -5))
        checkpoints = [poll_time] + five_steps + [5, 2, 1]
        seen = set(); clean = []
        for c in checkpoints:
            if 0 < c <= poll_time and c not in seen:
                seen.add(c); clean.append(c)
        checkpoints = sorted(clean, reverse=True)
        # Birinchi nuqta (poll_time) allaqachon ko'rsatilgan — skip
        prev = poll_time
        for target in checkpoints[1:]:
            sleep_for = prev - target
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            if chat_id not in _inline_sessions:
                return
            if _inline_sessions[chat_id].get("locked"):
                break
            try:
                await bot.edit_message_text(
                    text=_q_text(target),
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    parse_mode="HTML",
                    reply_markup=kb
                )
            except TelegramBadRequest:
                pass
            except Exception as e:
                err = str(e).lower()
                if "retry after" in err or "flood" in err or "too many" in err:
                    m    = re.search(r"retry after (\d+)", err)
                    wait = int(m.group(1)) + 1 if m else 10
                    log.warning(f"⏳ Timer flood — {wait}s")
                    await asyncio.sleep(wait)
            prev = target
        # Oxirgi 1 soniya kutib, vaqt tugadi
        await asyncio.sleep(1)

        if chat_id not in _inline_sessions:
            return

        # ── Vaqt tugadi → to'g'ri javobni ko'rsat ──
        session["locked"] = True
        await _reveal_inline_answer(bot, chat_id, i, q, opts, msg.message_id)
        await asyncio.sleep(3)

    # ── Test tugadi ──
    if chat_id in _inline_sessions:
        session = _inline_sessions[chat_id]
        await asyncio.sleep(1)
        await _show_group_leaderboard(
            bot, chat_id, session["tid"],
            session=session, mode="inline"
        )
        _inline_sessions.pop(chat_id, None)


async def _reveal_inline_answer(
    bot, chat_id: int, q_idx: int, q: dict, opts: list, msg_id: int
):
    """Savol vaqti tugagach to'g'ri javobni ko'rsatadi."""
    session     = _inline_sessions.get(chat_id, {})
    answers_map = session.get("answers", {})
    corr        = q.get("correct","")
    qtype       = q.get("type","multiple_choice")

    if qtype == "true_false":
        ci = 0 if "ha" in str(corr).lower() else 1
    elif isinstance(corr, int):
        ci = corr
    else:
        m  = re.match(r"^([A-Za-z])", str(corr).strip())
        ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
    ci = max(0, min(ci, len(opts)-1))

    # Ovozlar soni
    vote_counts = [0] * len(opts)
    total_ans   = 0
    for uid_str, uanswers in answers_map.items():
        ans = uanswers.get(str(q_idx))
        if ans is not None:
            total_ans += 1
            # ans — harf (A,B...) yoki "Ha"/"Yo'q"
            if qtype == "true_false":
                ai = 0 if ans == "Ha" else 1
            else:
                m = re.match(r"^([A-Za-z])", str(ans))
                ai = ord(m.group(1).upper()) - ord("A") if m else -1
            if 0 <= ai < len(vote_counts):
                vote_counts[ai] += 1

    labels     = ["🅐","🅑","🅒","🅓","🅔","🅕"]
    opt_lines  = []
    for j, opt in enumerate(opts[:6]):
        cnt   = vote_counts[j] if j < len(vote_counts) else 0
        pct   = round(cnt / total_ans * 100) if total_ans else 0
        bar_n = int(pct / 10)
        bar   = "🟩" * bar_n + "⬜" * (10 - bar_n)
        lbl   = labels[j] if j < len(labels) else str(j+1)
        mark  = "✅ " if j == ci else "    "
        opt_clean = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
        opt_lines.append(
            f"{mark}{lbl}  {opt_clean}\n"
            f"        {bar}  {pct}%  ({cnt} kishi)"
        )

    qtxt = q.get("question", q.get("text","Savol"))
    qtxt = re.sub(r'^\[\d+/\d+\]\s*','',qtxt).strip()
    expl = q.get("explanation","").strip()

    revealed = (
        f"🏁 <b>Savol {q_idx+1}</b>  —  Vaqt tugadi!\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{qtxt}\n\n"
        f"{chr(10).join(opt_lines)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Javob berdi: <b>{total_ans}</b>"
    )

    try:
        await bot.edit_message_text(
            text=revealed, chat_id=chat_id, message_id=msg_id,
            parse_mode="HTML", reply_markup=None
        )
    except Exception:
        try:
            await bot.send_message(chat_id, revealed, parse_mode="HTML", protect_content=True)
        except Exception: pass

    # Izoh
    if expl and expl not in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"):
        try:
            await bot.send_message(
                chat_id,
                f"<blockquote>💡 {expl}</blockquote>",
                parse_mode="HTML"
            ,
                protect_content=True)
        except Exception: pass


# ── Inline javob callback ━━━━━━━━━━━━━━━━━━━━━━━━────────────────

@router.callback_query(F.data.startswith("gi_ans:"))
async def handle_inline_answer(callback: CallbackQuery):
    """Guruh inline testida foydalanuvchi javob bosadi."""
    parts = callback.data.split(":")
    if len(parts) != 4:
        return await callback.answer("❌", show_alert=False)

    _, chat_id_str, q_idx_str, ans_idx_str = parts
    chat_id  = int(chat_id_str)
    q_idx    = int(q_idx_str)
    ans_idx  = int(ans_idx_str)
    user     = callback.from_user
    uid_str  = str(user.id)

    session = _inline_sessions.get(chat_id)
    if not session:
        return await callback.answer("❌ Faol test sessiyasi yo'q.", show_alert=False)
    if session.get("locked"):
        return await callback.answer("🔒 Vaqt tugadi!", show_alert=True)
    if session.get("cur_q") != q_idx:
        return await callback.answer("⏰ Bu savol o'tib ketdi.", show_alert=True)

    # Allaqachon javob berganmi?
    if uid_str in session["answers"] and str(q_idx) in session["answers"][uid_str]:
        return await callback.answer("✋ Siz allaqachon javob bergansiz!", show_alert=False)

    # Javobni saqlash
    if uid_str not in session["answers"]:
        session["answers"][uid_str] = {}
    session["names"][uid_str] = user.full_name or user.first_name or "O'quvchi"

    qs    = session["questions"]
    q     = qs[q_idx] if q_idx < len(qs) else {}
    qtype = q.get("type","multiple_choice")
    opts  = q.get("options",[])
    if qtype == "true_false":
        opts = ["Ha","Yo'q"]

    # ans_idx → harf yoki "Ha"/"Yo'q"
    if qtype == "true_false":
        letter = "Ha" if ans_idx == 0 else "Yo'q"
    else:
        letter = LETTERS[ans_idx] if ans_idx < len(LETTERS) else str(ans_idx)
    session["answers"][uid_str][str(q_idx)] = letter

    # To'g'ri yoki yo'q?
    corr = q.get("correct","")
    if qtype == "true_false":
        ci = 0 if "ha" in str(corr).lower() else 1
        is_correct = ans_idx == ci
    elif isinstance(corr, int):
        is_correct = ans_idx == corr
    else:
        m  = re.match(r"^([A-Za-z])", str(corr).strip())
        ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
        is_correct = ans_idx == ci

    if is_correct:
        await callback.answer("✅ To'g'ri! Ajoyib!", show_alert=False)
    else:
        corr_opt = opts[ci] if 0 <= ci < len(opts) else "?"
        corr_clean = str(corr_opt).split(")",1)[-1].strip() if ")" in str(corr_opt) else str(corr_opt)
        await callback.answer(
            f"❌ Noto'g'ri!\n✅ To'g'ri javob: {corr_clean}",
            show_alert=True
        )


# ── Inline to'xtatish ━━━━━━━━━━━━━━━━━━━━━━━━───────────────────

@router.callback_query(F.data.startswith("gi_stop_"))
async def group_inline_stop(callback: CallbackQuery):
    host_id = int(callback.data[8:])
    chat_id = callback.message.chat.id
    uid     = callback.from_user.id

    if uid != host_id:
        try:
            member = await callback.bot.get_chat_member(chat_id, uid)
            if member.status not in ("administrator","creator"):
                return await callback.answer("⚠️ Faqat boshlovchi yoki admin!", show_alert=True)
        except Exception:
            return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    await callback.answer("⏹ To'xtatilmoqda...")
    session = _inline_sessions.get(chat_id)
    if session:
        task = session.get("task")
        if task and not task.done():
            task.cancel()
        tid = session.get("tid","")
        await _show_group_leaderboard(
            callback.bot, chat_id, tid,
            session=session, mode="inline", stopped_early=True
        )
        _inline_sessions.pop(chat_id, None)
    else:
        await callback.bot.send_message(chat_id, "⏹ Test to'xtatildi.", protect_content=True)


# ══════════════════════════════════════════════════════════════
# POLL TO'XTATISH
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gstop_"))
async def group_stop(callback: CallbackQuery):
    host_id = int(callback.data[6:])
    chat_id = callback.message.chat.id
    uid     = callback.from_user.id
    if uid != host_id:
        try:
            member = await callback.bot.get_chat_member(chat_id, uid)
            if member.status not in ("administrator","creator"):
                return await callback.answer("⚠️ Faqat boshlovchi yoki admin!", show_alert=True)
        except Exception:
            return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    await callback.answer("⏹ To'xtatilmoqda...")
    if chat_id in _group_sessions:
        session = _group_sessions[chat_id]
        task    = session.get("task")
        if task and not task.done():
            task.cancel()
        tid = session.get("tid","")
        await _show_group_leaderboard(callback.bot, chat_id, tid, stopped_early=True)
        _group_sessions.pop(chat_id, None)
    else:
        try: await callback.message.delete()
        except: pass
        await callback.bot.send_message(chat_id, "⏹ Test to'xtatildi.", protect_content=True)


# ══════════════════════════════════════════════════════════════
# LEADERBOARD — RASM + MATN FALLBACK
# ══════════════════════════════════════════════════════════════

async def _show_group_leaderboard(
    bot, chat_id: int, tid: str,
    session: dict = None, mode: str = "poll",
    stopped_early: bool = False
):
    """
    Test natijalari: avval rasm leaderboard, fallback — matn.
    mode: "poll" yoki "inline"
    """
    if session is None:
        # Poll sessiyasi
        session = _group_sessions.get(chat_id, {})

    names   = session.get("names", {})
    answers = session.get("answers", {})
    test    = session.get("test", {})
    qs      = session.get("questions", [])
    passing = float(session.get("passing_score", test.get("passing_score", 60)))

    bot_info  = await bot.me()
    bot_uname = bot_info.username

    if not answers:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(
            text="▶️ Boshlash",
            url=f"https://t.me/{bot_uname}?start={tid}"
        ))
        stop_txt = "⛔ Test to'xtatildi!\n\n" if stopped_early else ""
        await bot.send_message(
            chat_id,
            f"🏁 <b>TEST YAKUNLANDI!</b>\n📝 {test.get('title','Test')}\n\n{stop_txt}😔 Hech kim javob bermadi.",
            reply_markup=b.as_markup()
        ,
            protect_content=True)
        return

    # ── Natijalarni hisoblash ──
    results_for_card = []
    for uid_str, user_answers in answers.items():
        scored = calculate_score(qs, user_answers)
        results_for_card.append({
            "first_name": names.get(uid_str, f"User {uid_str}"),
            "username":   names.get(uid_str, f"User {uid_str}"),
            "score":      scored.get("percentage", 0),
            "correct":    scored.get("correct_count", 0),
            "total":      len(qs),
            "uid":        int(uid_str),
            "scored":     scored,
        })
        try:
            import inspect as _ins
            _sr = save_result(int(uid_str), tid, {**scored, "mode": f"group_{mode}"})
            if _ins.isawaitable(_sr):
                await _sr
        except Exception as e:
            import traceback
            log.error(f"Natija saqlash: {e}\n{traceback.format_exc()}")

    results_for_card.sort(key=lambda x: x["score"], reverse=True)

    # ── Natijalarni tayyorlaymiz ──
    caption_txt = _build_text_leaderboard(
        tid, results_for_card, test, qs, bot_uname, stopped_early, passing, mode
    )
    # Caption 1024 belgidan oshsa — sig'gan odamlarni to'liq ko'rsatamiz
    caption_txt = _trim_caption(caption_txt, limit=1024)

    # ── Qayta boshlash + Ulashish tugmalari ──
    btn_kb = InlineKeyboardBuilder()
    if mode == "poll":
        btn_kb.row(InlineKeyboardButton(
            text="🔄 Qayta boshlash (Poll)",
            url=f"https://t.me/{bot_uname}?startgroup=gpoll_{tid}"
        ))
    else:
        btn_kb.row(InlineKeyboardButton(
            text="🔄 Qayta boshlash (Inline)",
            url=f"https://t.me/{bot_uname}?startgroup=ginline_{tid}"
        ))
    btn_kb.row(InlineKeyboardButton(
        text="📤 Ulashish",
        switch_inline_query=f"test_{tid}"
    ))

    # ── Guruh natijalarini RAMdan o'chirish + guruh lb yangilash ──
    from utils import ram_cache as ram
    for uid_str, user_answers in answers.items():
        # Tahlilni RAMdan o'chirish
        with ram._lck:
            ram._RAM.pop(f"analysis_{uid_str}", None)
            ram._RAM.pop(f"ana_access_{uid_str}", None)
        # Guruh leaderboard yangilash
        scored_entry = results_for_card[0] if results_for_card else {}
        for r in results_for_card:
            if r.get("uid") == int(uid_str):
                scored_entry = r
                break
        user = ram.get_user(uid_str) or {}
        ram.update_group_leaderboard(
            uid_str,
            user.get("name", f"User {uid_str}"),
            scored_entry.get("score", 0),
            scored_entry.get("correct", 0),
            scored_entry.get("total", len(qs)),
        )

    # ── Rasm + caption + tugmalar ──
    try:
        from utils.leaderboard_card import send_leaderboard_card
        await send_leaderboard_card(
            bot=bot,
            chat_id=chat_id,
            quiz_title=test.get("title","Test"),
            results=results_for_card,
            passing_score=passing,
            total_questions=len(qs),
            caption=caption_txt,
            delete_after=0,
            reply_markup=btn_kb.as_markup(),
        )
    except Exception as e:
        log.warning(f"Rasm leaderboard xato: {e}")
        # Rasm ishlamasa — faqat matn + tugmalar
        await _send_text_leaderboard(
            bot, chat_id, tid, results_for_card,
            test, qs, bot_uname, stopped_early, passing,
            mode=mode, reply_to=None
        )
        try:
            await bot.send_message(chat_id, "👇", reply_markup=btn_kb.as_markup())
        except Exception:
            pass


def _trim_caption(text: str, limit: int = 1024) -> str:
    """
    Caption limitga sig'masa — to'liq qatorlarni qoldiradi.
    Yarim qolgan qator chiqmaydi, oxirgi to'liq qator bilan tugaydi.
    """
    if len(text) <= limit:
        return text
    lines  = text.split("\n")
    result = []
    total  = 0
    for line in lines:
        needed = len(line) + (1 if result else 0)  # \n uchun +1
        if total + needed > limit:
            break
        result.append(line)
        total += needed
    return "\n".join(result)


def _clean_name(name: str, max_len: int) -> str:
    """Emoji, maxsus Unicode (𒐫 kabi), nazorat belgilarini olib tashlaydi va qisqartiradi."""
    import unicodedata
    result = []
    for ch in name:
        cat = unicodedata.category(ch)
        if cat.startswith(('L', 'N', 'P', 'Z')) and ord(ch) < 0x10000:
            result.append(ch)
    cleaned = ''.join(result).strip()
    if not cleaned:
        cleaned = "NoName"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "…"
    return cleaned


def _build_caption(results, title, passing, stopped_early):
    if not results:
        return f"🏁 <b>{title}</b>"
    passed   = sum(1 for r in results if r["score"] >= passing)
    avg      = sum(r["score"] for r in results) / len(results)
    top      = results[0]
    top_name = top.get("username") or top.get("first_name","?")
    stop_txt = "\n⛔ <i>Test to'xtatildi</i>" if stopped_early else ""
    return (
        f"🏁 <b>{title}</b>\n\n"
        f"🥇 <b>{top_name}</b> — {top['score']:.0f}%\n"
        f"👥 {len(results)} ishtirokchi  •  ✅ {passed} o'tdi  •  📊 {avg:.0f}% o'rtacha"
        f"{stop_txt}"
    )


def _build_text_leaderboard(tid, results, test, qs, bot_uname, stopped_early, passing, mode):
    """Rasm caption uchun matn natijalar."""
    medals  = ["🥇","🥈","🥉"]
    avg     = sum(r["score"] for r in results) / len(results) if results else 0
    passed  = sum(1 for r in results if r["score"] >= passing)

    stop_h  = "⛔️ <b>Test to'xtatildi!</b>" if stopped_early else "🏁 <b>Test tugadi!</b>"
    text    = (
        f"{stop_h}\n"
        f"📚 <b>{test.get('title','Test')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>Natijalar jadvali:</b>\n\n"
    )

    show = results[:15]
    for i, r in enumerate(show):
        medal   = medals[i] if i < 3 else f"{i+1}."
        pct     = r["score"]
        correct = r["correct"]
        total   = r["total"]
        filled  = round(pct / 10)
        bar     = "🟩" * filled + "⬜️" * (10 - filled)
        raw     = r.get("first_name") or r.get("username") or "O'quvchi"
        name    = _clean_name(raw, 20)
        text   += (
            f"{medal} <b>{name}</b>\n"
            f"    {bar}  {pct:.0f}%  ({correct}/{total} ✅)\n\n"
        )

    if len(results) > 15:
        text += f"<i>...va yana {len(results)-15} ta qatnashchi</i>\n\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Ishtirokchilar: <b>{len(results)} kishi</b>\n"
        f"📊 O'rtacha natija: <b>{avg:.1f}%</b>\n\n"
        f"🎉 Barcha ishtirokchilarga rahmat!"
    )
    return text


async def _send_text_leaderboard(
    bot, chat_id, tid, results, test, qs,
    bot_uname, stopped_early, passing, mode="poll", reply_to=None
):
    medals = ["🥇","🥈","🥉"]
    avg    = sum(r["score"] for r in results) / len(results) if results else 0
    passed = sum(1 for r in results if r["score"] >= passing)

    stop_h = "⛔️ <b>Test to'xtatildi!</b>" if stopped_early else "🏁 <b>Test tugadi!</b>"

    text = (
        f"{stop_h}\n"
        f"📚 <b>{test.get('title','Test')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>Natijalar jadvali:</b>\n\n"
    )

    show = results[:15]
    for i, r in enumerate(show):
        medal   = medals[i] if i < 3 else f"{i+1}."
        pct     = r["score"]
        correct = r["correct"]
        total   = r["total"]
        filled  = round(pct / 10)
        bar     = "🟩" * filled + "⬜️" * (10 - filled)
        raw     = r.get("first_name") or r.get("username") or "O'quvchi"
        name    = _clean_name(raw, 20)
        text   += (
            f"{medal} <b>{name}</b>\n"
            f"    {bar}  {pct:.0f}%  ({correct}/{total} ✅)\n\n"
        )

    if len(results) > 15:
        text += f"<i>...va yana {len(results)-15} ta qatnashchi</i>\n\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Ishtirokchilar: <b>{len(results)} kishi</b>\n"
        f"📊 O'rtacha natija: <b>{avg:.1f}%</b>\n\n"
        f"🎉 Barcha ishtirokchilarga rahmat!"
    )

    mode_suffix = "inline" if mode == "inline" else "poll"
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="🔄 Yana bir marta",
            callback_data=f"grestart_{tid}_{mode_suffix}"
        ),
        InlineKeyboardButton(
            text="📤 Ulashish",
            switch_inline_query=f"test_{tid}"
        ),
    )

    from aiogram.types import ReplyParameters
    try:
        await bot.send_message(
            chat_id, text,
            reply_markup=b.as_markup(),
            reply_parameters=ReplyParameters(message_id=reply_to) if reply_to else None
        ,
            protect_content=True)
    except Exception:
        await bot.send_message(chat_id, text, reply_markup=b.as_markup(), protect_content=True)



# ══════════════════════════════════════════════════════════════
# GURUHDA ISHLASH TUGMASI — bot o'zi /quiz_start yozadi
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("grestart_"))
async def grestart(callback: CallbackQuery):
    """Test tugagach 'Yana bir marta' — o'sha guruhga avto-buyruq."""
    await callback.answer()
    parts = callback.data[9:].rsplit("_", 1)  # grestart_TID_mode
    if len(parts) != 2:
        return
    tid, mode_sfx = parts
    chat_id = callback.message.chat.id if callback.message else None
    if not chat_id:
        return
    await callback.bot.send_message(
        chat_id,
        f"/quiz_start {tid} {mode_sfx}"
    ,
        protect_content=True)


@router.callback_query(F.data.startswith("gsend_poll_"))
async def gsend_poll(callback: CallbackQuery):
    tid = callback.data[11:]
    await callback.answer()
    uid = callback.from_user.id
    # Guruhga nusxa-paste usuli: <code> tag — bir teginishda nusxa olinadi
    try:
        await callback.bot.send_message(
            uid,
            f"👇 Quyidagi buyruqni <b>nusxa oling</b> va guruhga yuboring:\n\n"
            f"<code>/quiz_start {tid} poll</code>\n\n"
            f"💡 Matnni bosing — avtomatik nusxa olinadi",
            parse_mode="HTML"
        ,
            protect_content=True)
    except Exception:
        await callback.answer(
            f"/quiz_start {tid} poll",
            show_alert=True
        )


@router.callback_query(F.data.startswith("gsend_inline_"))
async def gsend_inline(callback: CallbackQuery):
    tid = callback.data[13:]
    await callback.answer()
    uid = callback.from_user.id
    try:
        await callback.bot.send_message(
            uid,
            f"👇 Quyidagi buyruqni <b>nusxa oling</b> va guruhga yuboring:\n\n"
            f"<code>/quiz_start {tid} inline</code>\n\n"
            f"💡 Matnni bosing — avtomatik nusxa olinadi",
            parse_mode="HTML"
        ,
            protect_content=True)
    except Exception:
        await callback.answer(
            f"/quiz_start {tid} inline",
            show_alert=True
        )


# ══════════════════════════════════════════════════════════════
# /quiz_start — GURUHDA BUYRUQ ORQALI TEST BOSHLASH
# ══════════════════════════════════════════════════════════════

@router.message(Command("quiz_start_poll"))
async def cmd_quiz_start_poll(message: Message):
    """Guruhda: /quiz_start_poll KOD — poll usuli"""
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("❌ Foydalanish: <code>/quiz_start_poll KOD</code>")
    # /quiz_start KOD poll ga yo'naltirish
    message.text = f"/quiz_start {args[1]} poll"
    await cmd_quiz_start(message)


@router.message(Command("quiz_start_inline"))
async def cmd_quiz_start_inline(message: Message):
    """Guruhda: /quiz_start_inline KOD — inline usuli"""
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("❌ Foydalanish: <code>/quiz_start_inline KOD</code>")
    message.text = f"/quiz_start {args[1]} inline"
    await cmd_quiz_start(message)


async def _start_group_test(bot, chat_id: int, uid: int, tid: str, mode: str):
    """Guruhda test boshlash — asosiy logika. start.py va cmd_quiz_start ishlatadi."""
    if is_test_paused(tid):
        return await bot.send_message(chat_id, "⚠️ Bu test vaqtincha to\'xtatilgan!", protect_content=True)

    if chat_id in _group_sessions:
        return await bot.send_message(chat_id, "⚠️ Guruhda allaqachon poll testi ketmoqda!\nAvval uni tugating: /quiz_stop", protect_content=True)
    if chat_id in _inline_sessions:
        return await bot.send_message(chat_id, "⚠️ Guruhda allaqachon inline test ketmoqda!\nAvval uni tugating: /quiz_stop", protect_content=True)

    test = await _load_test(bot, chat_id, tid)
    if not test:
        return await bot.send_message(chat_id, f"❌ <code>{tid}</code> kodli test topilmadi.", protect_content=True)

    # ── Kirish nazorati ───────────────────────────────────────
    from utils.ram_cache import get_test_meta as _gtm
    from config import ADMIN_USERNAME
    _meta_g  = _gtm(tid) or {}
    _allowed = _meta_g.get("allowed_users", [])
    if _allowed and uid not in _allowed:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(
            text="📩 Adminga murojat",
            url=f"https://t.me/{ADMIN_USERNAME}"
        ))
        return await bot.send_message(
            chat_id,
            f"🔐 <b>Kirish cheklangan</b>\n\n"
            f"Bu testga kirishga ruxsatingiz yo'q.\n"
            f"Ruxsat olish uchun @{ADMIN_USERNAME} ga yozing.",
            reply_markup=b.as_markup(),
            protect_content=True
        )

    if mode == "inline":
        qs            = test.get("questions", [])
        poll_time     = test.get("poll_time", 30) or 30
        passing_score = float(test.get("passing_score", 60))
        if not qs:
            return await bot.send_message(chat_id, "⚠️ Bu testda savollar yo\'q!", protect_content=True)

        import random, copy
        qs = copy.deepcopy(qs)
        if test.get("shuffle_questions", True):
            random.shuffle(qs)
        _shuffle_options(qs)

        _inline_sessions[chat_id] = {
            "tid": tid, "test": test, "questions": qs,
            "answers": {}, "names": {}, "host_id": uid,
            "poll_time": poll_time, "passing_score": passing_score,
            "cur_q": 0, "q_msg_id": None, "task": None, "locked": False,
        }
        cdown = await bot.send_message(chat_id, f"📝 <b>{test.get('title')}</b>", parse_mode="HTML", protect_content=True)
        for emoji in COUNT_EMOJIS:
            await asyncio.sleep(0.8)
            try: await bot.edit_message_text(emoji, chat_id, cdown.message_id)
            except: pass
        await asyncio.sleep(0.5)
        try: await bot.delete_message(chat_id, cdown.message_id)
        except: pass

        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⏹ To\'xtatish", callback_data=f"gi_stop_{uid}"))
        diff_m  = {"easy":"🟢 Oson","medium":"🟡 O'rtacha","hard":"🔴 Qiyin","expert":"⚡ Ekspert"}
        diff_t  = diff_m.get(test.get("difficulty",""), "")
        ps      = test.get("passing_score", 60)
        cat     = test.get("category", "")
        sc      = test.get("solve_count", 0)
        await bot.send_message(
            chat_id,
            f"🚀 <b>INLINE TEST BOSHLANDI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 <b>{test.get('title')}</b>\n"
            f"📁 {cat}  {diff_t}\n"
            f"📋 {len(qs)} ta savol | ⏱ {poll_time}s/savol\n"
            f"🎯 O'tish: {ps}% | 👥 {sc} marta yechilgan\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Hamma qatnashing! Tugmalar orqali javob bering!</b>",
            parse_mode="HTML", reply_markup=b.as_markup(),
            protect_content=True)
        task = asyncio.create_task(
            _run_inline_session(bot, chat_id, tid, qs, poll_time, passing_score)
        )
        _inline_sessions[chat_id]["task"] = task

    else:
        qs = [q for q in test.get("questions", [])
              if q.get("type", "multiple_choice") in ("multiple_choice", "true_false")]
        if not qs:
            return await bot.send_message(chat_id, "⚠️ Bu testda poll uchun savollar yo\'q!", protect_content=True)

        poll_time = test.get("poll_time", 30) or 30

        import random, copy
        qs = copy.deepcopy(qs)
        if test.get("shuffle_questions", True):
            random.shuffle(qs)
        _shuffle_options(qs)

        _group_sessions[chat_id] = {
            "tid": tid, "test": test, "questions": qs,
            "answers": {}, "names": {}, "poll_map": {},
            "host_id": uid, "poll_time": poll_time, "task": None,
        }
        cdown = await bot.send_message(chat_id, f"📝 <b>{test.get('title')}</b>", parse_mode="HTML", protect_content=True)
        for emoji in COUNT_EMOJIS:
            await asyncio.sleep(0.8)
            try: await bot.edit_message_text(emoji, chat_id, cdown.message_id)
            except: pass
        await asyncio.sleep(0.5)
        try: await bot.delete_message(chat_id, cdown.message_id)
        except: pass

        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⏹ To\'xtatish", callback_data=f"gstop_{uid}"))
        skipped  = len(test.get("questions", [])) - len(qs)
        skip_txt = f"\n⚠️ {skipped} ta matn savol o\'tkazildi" if skipped else ""
        diff_m  = {"easy":"🟢 Oson","medium":"🟡 O'rtacha","hard":"🔴 Qiyin","expert":"⚡ Ekspert"}
        diff_t  = diff_m.get(test.get("difficulty",""), "")
        ps      = test.get("passing_score", 60)
        cat     = test.get("category", "")
        sc      = test.get("solve_count", 0)
        await bot.send_message(
            chat_id,
            f"🚀 <b>QUIZ POLL BOSHLANDI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 <b>{test.get('title')}</b>\n"
            f"📁 {cat}  {diff_t}\n"
            f"📋 {len(qs)} ta savol | ⏱ {poll_time}s/savol\n"
            f"🎯 O'tish: {ps}% | 👥 {sc} marta yechilgan\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Hamma qatnashing!</b>{skip_txt}",
            parse_mode="HTML", reply_markup=b.as_markup(),
            protect_content=True)
        task = asyncio.create_task(
            _run_group_polls(bot, chat_id, tid, qs, poll_time)
        )
        _group_sessions[chat_id]["task"] = task


@router.message(Command("quiz_start"))
async def cmd_quiz_start(message: Message):
    """
    Guruhda: /quiz_start <test_kodi>
    Misol:   /quiz_start 3D46D269
    Misol:   /quiz_start 3D46D269 poll   (poll usuli)
    Misol:   /quiz_start 3D46D269 inline (inline usuli)
    """
    chat    = message.chat
    chat_id = chat.id
    uid     = message.from_user.id

    if chat.type not in ("group", "supergroup"):
        return await message.answer(
            "⚠️ Bu buyruq faqat guruhlarda ishlaydi!\n"
            "Guruhda yozing: <code>/quiz_start &lt;test_kodi&gt;</code>"
        )

    args = message.text.split()
    if len(args) < 2:
        return await message.answer(
            "❌ <b>Foydalanish:</b>\n"
            "<code>/quiz_start &lt;test_kodi&gt;</code>\n"
            "<code>/quiz_start &lt;test_kodi&gt; poll</code>\n"
            "<code>/quiz_start &lt;test_kodi&gt; inline</code>\n\n"
            "Misol: <code>/quiz_start 3D46D269</code>"
        )

    tid  = args[1].strip().upper()
    mode = args[2].strip().lower() if len(args) > 2 else "poll"

    await _start_group_test(message.bot, chat_id, uid, tid, mode)

@router.message(Command("quiz_stop"))
async def cmd_quiz_stop(message: Message):
    """Guruhda: /quiz_stop — joriy testni to\'xtatish"""
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Bu buyruq faqat guruhlarda ishlaydi!")

    # Admin yoki host tekshiruvi
    stopped = False

    if chat_id in _inline_sessions:
        session = _inline_sessions[chat_id]
        if uid == session.get("host_id") or await _is_admin(message.bot, chat_id, uid):
            task = session.get("task")
            if task and not task.done():
                task.cancel()
            await _show_group_leaderboard(
                message.bot, chat_id, session["tid"],
                session=session, mode="inline", stopped_early=True
            )
            _inline_sessions.pop(chat_id, None)
            stopped = True
        else:
            return await message.answer("⚠️ Faqat test boshlovchi yoki admin to\'xtatishi mumkin!")

    if chat_id in _group_sessions:
        session = _group_sessions[chat_id]
        if uid == session.get("host_id") or await _is_admin(message.bot, chat_id, uid):
            task = session.get("task")
            if task and not task.done():
                task.cancel()
            await _show_group_leaderboard(
                message.bot, chat_id, session["tid"],
                stopped_early=True
            )
            _group_sessions.pop(chat_id, None)
            stopped = True
        else:
            return await message.answer("⚠️ Faqat test boshlovchi yoki admin to\'xtatishi mumkin!")

    if not stopped:
        await message.answer("ℹ️ Hozir guruhda faol test yo\'q.")


async def _is_admin(bot, chat_id: int, uid: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, uid)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# BOT GURUHGA QO'SHILDI
# ══════════════════════════════════════════════════════════════

@router.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    from utils import ram_cache as ram
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    chat       = event.chat

    if chat.type not in ("group", "supergroup"):
        return

    # Bot chiqarildi yoki kicked
    if new_status in ("left", "kicked", "restricted"):
        ram.remove_known_group(chat.id)
        log.info(f"Guruhdan chiqarildi: {chat.title} ({chat.id})")
        from utils import tg_db
        asyncio.create_task(tg_db.save_known_groups())
        return

    # Bot qo'shildi yoki admin bo'ldi
    if new_status in ("member", "administrator"):
        try:
            member_count = await event.bot.get_chat_member_count(chat.id)
        except:
            member_count = 0
        ram.add_known_group(
            chat_id=chat.id,
            title=chat.title or "Nomsiz guruh",
            username=getattr(chat, "username", "") or "",
            chat_type=chat.type,
            member_count=member_count,
        )
        log.info(f"Guruhga qo'shildi: {chat.title} ({chat.id}), a'zolar: {member_count}")
        from utils import tg_db
        asyncio.create_task(tg_db.save_known_groups())

        if old_status in ("left", "kicked"):
            # Faqat yangi qo'shilganda xabar yuborish
            bot_info = await event.bot.me()
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(
                text="📚 Testlarni ko'rish",
                url=f"https://t.me/{bot_info.username}"
            ))
            try:
                await event.bot.send_message(
                    chat.id,
                    f"👋 <b>Quiz Bot</b> guruhga qo'shildi! 🎉\n\n"
                    f"📊 <b>Poll usuli:</b> Telegram native poll savollar\n"
                    f"👥 <b>Inline usuli:</b> Tugmalar + countdown timer\n\n"
                    f"Botga yuborilgan testda:\n"
                    f"  • <b>\"📊 Quiz Poll\"</b> — poll usuli\n"
                    f"  • <b>\"👥 Guruhda (Inline)\"</b> — inline usuli\n\n"
                    f"<i>💡 Poll uchun botga admin huquqi kerak.</i>",
                    reply_markup=b.as_markup(),
                    protect_content=True
                )
            except Exception as e:
                log.warning(f"Guruh xabar: {e}")
