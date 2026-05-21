"""🚀 START — Xush kelibsiz, test kartochkasi"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from config import ADMIN_IDS
from utils.db import get_or_create_user
from utils.ram_cache import get_test_by_id, get_test_meta
from keyboards.keyboards import main_kb, test_info_kb
from utils.states import ContactAdmin

log    = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid       = message.from_user.id
    uname     = message.from_user.username
    name      = message.from_user.full_name or (f"@{uname}" if uname else f"User{uid}")
    chat_type = message.chat.type   # "private" | "group" | "supergroup" | "channel"

    # ── GURUHDA /start — parametrsiz bo'lsa ma'lumot, parametrli bo'lsa davom ──
    if chat_type in ("group", "supergroup"):
        args = message.text.split()
        if len(args) == 1:
            bot_info = await message.bot.get_me()
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(text="🤖 Botni ochish", url=f"https://t.me/{bot_info.username}"))
            b.row(InlineKeyboardButton(text="📚 Test tanlash", switch_inline_query_current_chat=""))
            await message.answer(
                f"👋 Salom, <b>{name}</b>!\n\n"
                f"📌 <b>Guruhda test o'tkazish:</b>\n\n"
                f"1️⃣ Botni inline rejimda ishlating:\n"
                f"   Xabar maydoniga <code>@{bot_info.username} </code> yozing → test tanlang → yuboring\n\n"
                f"2️⃣ Yoki test havolasini guruhga yuboring — barcha ishlay oladi\n\n"
                f"✏️ <b>Test yaratish uchun</b> botga <b>private</b> xabar yozing 👇",
                reply_markup=b.as_markup()
            )
            return
        # Parametr bor (gpoll_, ginline_, test ID) — davom etsin
    # ━━━━━━━━━━━━━━━━━━━━━━━━

    user   = await get_or_create_user(uid, name, uname)
    is_new = user.pop("_just_created", False)

    if user.get("is_blocked"):
        return await message.answer("🚫 Siz bloklangansiz.")

    if is_new:
        from datetime import datetime
        at = f"@{uname}" if uname else "Mavjud emas"
        vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for aid in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    aid,
                    f"🆕 <b>YANGI FOYDALANUVCHI:</b>\n\n"
                    f"👤 Ism: {name}\n"
                    f"🆔 ID: <code>{uid}</code>\n"
                    f"🔗 Username: {at}\n"
                    f"⏰ Vaqt: {vaqt}",
                    parse_mode="HTML",
                    protect_content=False
                )
            except Exception: pass
        welcome = (
            f"👋 Salom, <b>{name}</b>!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <b>QuizMaker Bot</b> ga xush kelibsiz!\n\n"
            f"📌 <b>Bot imkoniyatlari:</b>\n\n"
            f"▶️ <b>Inline Test</b> — har savoldan keyin to'g'ri/noto'g'ri ko'rsatadi, 30s avtomatik o'tadi\n\n"
            f"📊 <b>Quiz Poll</b> — Telegram native quiz rejimi, vaqt bilan\n\n"
            f"➕ <b>Test Yaratish</b> — TXT, PDF, DOCX fayl yoki matn orqali, @QuizBot forward\n\n"
            f"📤 <b>Ulashish</b> — testni inline orqali do'stlarga yuborish\n\n"
            f"📈 <b>Natijalarim</b> — barcha testlar bo'yicha foiz va tahlil\n\n"
            f"🏆 <b>Reyting</b> — eng yaxshi natijalar\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👇 Pastdagi menyudan boshlang!"
        )
    else:
        welcome = f"🏠 Xush kelibsiz, <b>{name}</b>!"

    args = message.text.split()
    if len(args) > 1:
        param = args[1].strip()
        from utils.db import get_test_full as _gtf

        # ── REFERAL DEEP LINK ━━━━━━━━━━━━━━━━━━━━━━━━
        if param.lower().startswith("ref") and param[3:].isdigit():
            referrer_uid = int(param[3:])
            if referrer_uid != uid:
                from utils.roles import process_referral
                result = process_referral(uid, referrer_uid, ADMIN_IDS)
                if result.get("ok"):
                    # Referentga xabar yuborish
                    try:
                        await message.bot.send_message(
                            referrer_uid,
                            f"🎉 <b>Yangi taklif!</b>\n\n"
                            f"👤 <b>{name}</b> sizning havolangiz orqali keldi.\n"
                            f"📊 {result['msg']}\n\n"
                            f"{'✅ Bugun test yaratish imkoningiz bor!' if result.get('today_count', 0) >= 1 else ''}"
                        )
                    except Exception:
                        pass
            await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
            return
        # ━━━━━━━━━━━━━━━━━━━━━━━━

        if param.lower() == "create":
            await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
            return

        # ── DEMO DEEP LINK ━━━━━━━━━━━━━━━━━━━━━━━━
        if param.lower().startswith("demo_"):
            tid  = param[5:].upper()
            test = get_test_by_id(tid) or await _gtf(tid)
            if test:
                await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
                b = InlineKeyboardBuilder()
                b.row(InlineKeyboardButton(
                    text="🔍 Demo (Inline)",
                    callback_data=f"start_demo_{tid}"
                ))
                b.row(InlineKeyboardButton(
                    text="🔍 Demo (Poll)",
                    callback_data=f"start_demopoll_{tid}"
                ))
                from config import ADMIN_USERNAME
                b.row(InlineKeyboardButton(
                    text="📩 To'liq test olish",
                    url=f"https://t.me/{ADMIN_USERNAME}"
                ))
                qc = len(test.get("questions",[])) or test.get("question_count",0)
                from handlers.inline_mode import DEMO_MIN, DEMO_MAX
                demo_q = min(DEMO_MAX, max(DEMO_MIN, qc // 3))
                await message.answer(
                    f"🔍 <b>[DEMO] {test.get('title')}</b>\n\n"
                    f"Bu sinov rejimi — faqat <b>{demo_q} ta</b> savol yechish mumkin.\n"
                    f"To'liq test uchun adminga murojat qiling.",
                    reply_markup=b.as_markup()
                )
            return

        if param.lower().startswith("demopoll_"):
            tid  = param[9:].upper()
            test = get_test_by_id(tid) or await _gtf(tid)
            if test:
                await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
                b = InlineKeyboardBuilder()
                b.row(InlineKeyboardButton(
                    text="🔍 Demo Poll boshlash",
                    callback_data=f"start_demopoll_{tid}"
                ))
                await message.answer(
                    f"🔍 <b>[DEMO] {test.get('title')}</b>",
                    reply_markup=b.as_markup()
                )
            return
        # ━━━━━━━━━━━━━━━━━━━━━━━━

        if param.lower().startswith("poll_"):
            tid  = param[5:].upper()
            test = get_test_by_id(tid) or await _gtf(tid)
            if test:
                await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
                # To'g'ridan poll boshlaymiz — foydalanuvchi allaqachon tanlagan
                b = InlineKeyboardBuilder()
                b.row(InlineKeyboardButton(
                    text="📊 Quiz Poll boshlash",
                    callback_data=f"start_poll_{tid}"
                ))
                title = test.get("title", "?")
                await message.answer(
                    f"📝 <b>{title}</b>\n\n"
                    f"📊 Quiz Poll rejimi tanlandi.\n"
                    f"Boshlash uchun tugmani bosing 👇",
                    reply_markup=b.as_markup()
                )
            return

        # ── GURUHDA ISHLASH — startgroup deep link ━━━━━━━━━━━━━━━━━━━━━━━━
        if param.lower().startswith("gpoll_"):
            tid  = param[6:].upper()
            chat = message.chat
            if chat.type in ("group", "supergroup"):
                from handlers.group import _start_group_test
                await _start_group_test(message.bot, chat.id, uid, tid, "poll")
            else:
                test = get_test_by_id(tid) or await _gtf(tid)
                if test:
                    await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
                    await _send_test_card(message, test, tid,
                                          viewer_uid=uid, poll_only=True)
            return

        if param.lower().startswith("ginline_"):
            tid  = param[8:].upper()
            chat = message.chat
            if chat.type in ("group", "supergroup"):
                from handlers.group import _start_group_test
                await _start_group_test(message.bot, chat.id, uid, tid, "inline")
            else:
                test = get_test_by_id(tid) or await _gtf(tid)
                if test:
                    await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
                    await _send_test_card(message, test, tid, viewer_uid=uid)
            return

        tid  = param.upper()
        test = get_test_by_id(tid) or await _gtf(tid)
        if test:
            await message.answer(welcome, reply_markup=main_kb(uid, chat_type))
            await _send_test_card(message, test, tid, viewer_uid=uid)
            return

    await message.answer(
        f"{welcome}\n\nPastdagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=main_kb(uid, chat_type)
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Yordam")
async def help_msg(message: Message):
    await _send_help(message)

@router.callback_query(F.data == "help")
async def help_cb(callback: CallbackQuery):
    await callback.answer()
    await _send_help(callback.message, edit=True)

async def _send_help(msg, edit=False):
    text = (
        "❓ <b>BOTDAN FOYDALANISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>▶️ Inline test</b> — har savoldan keyin\n"
        "   to'g'ri/noto'g'ri ko'rsatadi\n"
        "   30s avtomatik keyingi savolga o'tadi\n\n"
        "2️⃣ <b>📊 Quiz Poll</b> — Telegram native quiz\n"
        "   vaqt bilan, pauza/to'xtatish bor\n\n"
        "3️⃣ <b>📤 Ulashish</b> — inline orqali yuborish\n"
        "   2 ta rejimdan birini tanlab boshlash\n\n"
        "4️⃣ <b>Test kodi</b> — to'g'ridan yuboring\n\n"
        "5️⃣ <b>📊 Natijalarim</b> — barcha foizlar\n"
        "   faqat oxirgi test uchun tahlil\n\n"
        "💬 <i>Muammo bo'lsa adminga murojaat:</i>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✉️ Adminga murojaat", callback_data="contact_admin"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu",     callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except Exception:
        await msg.answer(text, reply_markup=b.as_markup())


async def _send_test_card(event, test, tid, viewer_uid=None, edit=False, poll_only=False):
    from keyboards.keyboards import get_cat_icon
    meta     = get_test_meta(tid) or test
    qc       = len(test.get("questions",[])) or meta.get("question_count",0)
    diff     = {"easy":"🟢 Oson","medium":"🟡 O'rtacha",
                "hard":"🔴 Qiyin","expert":"⚡ Ekspert"}.get(meta.get("difficulty",""),"")
    att_t    = f"{meta.get('max_attempts',0)} marta" if meta.get("max_attempts",0) else "Cheksiz"
    vis      = {"public":"🌍 Ommaviy","link":"🔗 Link orqali",
                "private":"🔒 Shaxsiy"}.get(meta.get("visibility",""),"")
    pause_t  = "⚠️ <b>Vaqtincha to'xtatilgan!</b>\n\n" if meta.get("is_paused") else ""

    cat      = meta.get("category","")
    cat_icon = get_cat_icon(cat)

    text = (
        f"📋 <b>TEST MA'LUMOTI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{pause_t}"
        f"📝 <b>{meta.get('title','Nomsiz')}</b>\n"
        f"{cat_icon} Fan: {cat}\n"
        f"📊 Qiyinlik: {diff}\n"
        f"🔒 Ko'rinish: {vis}\n"
        f"📋 Savollar: <b>{qc} ta</b>\n"
        f"⏱ Poll vaqti: {meta.get('poll_time',30)}s/savol\n"
        f"🎯 O'tish foizi: <b>{meta.get('passing_score',60)}%</b>\n"
        f"🔄 Urinishlar: {att_t}\n"
        f"👥 Ishlagan: <b>{meta.get('solve_count',0)} marta</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶️ Inline — savoldan keyin javob, 30s avto-o'tish\n"
        f"📊 Poll — Telegram quiz, vaqt bilan"
    )
    creator_id = meta.get("creator_id")
    kb = test_info_kb(tid, creator_id=creator_id, viewer_uid=viewer_uid, poll_only=poll_only)
    target = event if isinstance(event, Message) else event.message
    try:
        if edit and not isinstance(event, Message):
            await target.edit_text(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)
    except TelegramBadRequest:
        await target.answer(text, reply_markup=kb)


# ── Pause/Resume (creator/admin) ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data.startswith("test_pause_"))
async def test_pause_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[11:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    from utils.db import pause_test
    pause_test(tid, paused=True)
    await callback.answer("⏸ To'xtatildi", show_alert=True)
    from utils.db import get_test_full
    test = get_test_by_id(tid) or await get_test_full(tid)
    if test:
        await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)

@router.callback_query(F.data.startswith("test_resume_"))
async def test_resume_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[12:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    from utils.db import pause_test
    pause_test(tid, paused=False)
    await callback.answer("▶️ Qayta boshlandi!", show_alert=True)
    from utils.db import get_test_full
    test = get_test_by_id(tid) or await get_test_full(tid)
    if test:
        await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)


# ── Asosiy menyu ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data == "main_menu")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    uid = callback.from_user.id
    # Faqat inline keyboard ni tozalaymiz — xabarni O'CHIRMAYMIZ
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # Keyboard doim pastda turishi uchun qayta yuboramiz
    from utils import ram_cache as ram
    msg = await callback.bot.send_message(
        uid,
        "🏠 <b>Asosiy menyu</b> 👇",
        reply_markup=main_kb(uid, "private")
    )
    ram.set_menu_msg(uid, uid, msg.message_id)

@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


# ── Adminga murojaat ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data == "contact_admin")
async def contact_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_contact"))
    try:
        await callback.message.edit_text(
            "<b>✉️ ADMINGA MUROJAAT</b>\n\nXabaringizni yozing:",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "<b>✉️ ADMINGA MUROJAAT</b>\n\nXabaringizni yozing:",
            reply_markup=b.as_markup()
        )
    await state.set_state(ContactAdmin.waiting_message)

@router.callback_query(F.data == "cancel_contact")
async def cancel_contact(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Bekor qilindi")
    try: await callback.message.delete()
    except: pass
    uid = callback.from_user.id
    await callback.bot.send_message(uid, "✅ Bekor qilindi.", reply_markup=main_kb(uid, "private"))

@router.message(ContactAdmin.waiting_message)
async def contact_admin_send(message: Message, state: FSMContext):
    uid   = message.from_user.id
    name  = message.from_user.full_name
    uname = f"@{message.from_user.username}" if message.from_user.username else "Yo'q"
    sent  = 0
    for aid in ADMIN_IDS:
        try:
            await message.bot.send_message(
                aid, f"📩 <b>MUROJAAT</b>\n👤 <b>{name}</b> | {uname} | <code>{uid}</code>"
            )
            await message.forward(aid)
            sent += 1
        except Exception as e: log.error(f"Admin {aid}: {e}")
    await state.clear()
    txt = "✅ Xabaringiz adminga yuborildi! 🙏" if sent else "⚠️ Yuborishda muammo."
    await message.answer(txt, reply_markup=main_kb(uid, "private"))

@router.message(F.text.startswith("/reply "))
async def admin_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        return await message.answer("Format: <code>/reply USER_ID Matn</code>")
    try:
        await message.bot.send_message(
            int(parts[1]),
            f"📬 <b>ADMINDAN JAVOB:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{parts[2]}"
        )
        await message.answer(f"✅ <code>{parts[1]}</code> ga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")


@router.message(F.reply_to_message)
async def admin_reply_to_forward(message: Message):
    """
    Admin forward qilingan xabarga reply qilsa — userga javob yuboradi.
    Murojaat xabaridagi caption dan user_id olinadi.
    """
    if message.from_user.id not in ADMIN_IDS:
        return
    reply = message.reply_to_message
    if not reply:
        return
    # Caption yoki text dan user_id qidirish
    # Format: "MUROJAAT: Name | @uname | 123456789"
    caption = reply.caption or reply.text or ""
    uid_str = None
    import re
    # ID ni oxirgi <code> tagidan yoki so'nggi raqamlar ketma-ketligidan olamiz
    m = re.search(r"<code>(\d+)</code>", caption)
    if m:
        uid_str = m.group(1)
    else:
        # Fallback: caption da oxirgi raqamlar
        m2 = re.search(r"\b(\d{5,12})\b", caption)
        if m2:
            uid_str = m2.group(1)
    if not uid_str:
        return  # Bu murojaat xabari emas, e'tibor bermaymiz
    try:
        text = message.text or message.caption or ""
        await message.bot.send_message(
            int(uid_str),
            f"📬 <b>ADMINDAN JAVOB:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{text}"
        )
        await message.answer(f"✅ <code>{uid_str}</code> ga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
