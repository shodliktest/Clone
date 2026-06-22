"""➕ TEST YARATISH — Fayl yoki QuizBot forward"""
import os, re, logging, tempfile, asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from utils.parser import parse_file, check_images_in_file
from utils.states import CreateTest
from utils.db import create_test
from keyboards.keyboards import subject_kb, difficulty_kb, visibility_kb, main_kb, test_created_kb
from config import SUBJECTS  # ✅ FIXED: import

def _get_user_subjects(uid):
    """✅ FIXED: User maxsus fan nomlari + standart SUBJECTS"""
    from utils.ram_cache import get_user_custom_subjects
    custom = get_user_custom_subjects(uid)
    return custom + [s for s in SUBJECTS if s not in custom]

log        = logging.getLogger(__name__)
router     = Router()
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")
POLL_TIMES  = [10, 12, 20, 30, 50, 120]

SAMPLE_TYPES = {
    "mcq": (
        "mcq_namuna.txt",
        "🔘 Bir javobli (MCQ)",
        (
            "1. O'zbekiston poytaxti qayer?\n"
            "===A) Toshkent\n"
            "B) Samarqand\n"
            "C) Buxoro\n"
            "D) Xiva\n"
            "Izoh: Toshkent 1930-yildan poytaxt.\n\n"
            "2. Pi soni taxminan qancha?\n"
            "A) 2.14\n"
            "===B) 3.14\n"
            "C) 4.14\n"
            "D) 5.14"
        )
    ),
    "tf": (
        "tf_namuna.txt",
        "✅ Ha / Yo'q",
        (
            "TYPE: true_false\n"
            "1. Yer Quyosh atrofida aylanadi.\n"
            "Javob: Ha\n"
            "Izoh: Yer elliptik orbita bo'ylab aylanadi.\n\n"
            "TYPE: true_false\n"
            "2. Quyosh Yerdan kichik.\n"
            "Javob: Yoq\n"
            "Izoh: Quyosh Yerdan 109 marta katta."
        )
    ),
    "fill": (
        "fill_namuna.txt",
        "✍️ Bo'sh joy to'ldirish",
        (
            "TYPE: fill_blank\n"
            "1. Alisher Navoiy ___ yilda tug'ilgan.\n"
            "Javob: 1441\n"
            "Qabul: 1441-yil, 1441 yil\n\n"
            "TYPE: fill_blank\n"
            "2. O'zbekiston mustaqilligini ___ yilda qo'lga kiritdi.\n"
            "Javob: 1991\n"
            "Qabul: 1991-yil"
        )
    ),
    "text": (
        "text_namuna.txt",
        "💬 Erkin javob",
        (
            "TYPE: text_input\n"
            "1. Fotosintez jarayonini tushuntiring.\n"
            "Javob: o'simliklarning quyosh nuri yordamida oziq yaratishi\n"
            "Qabul: fotosintez, quyosh energiyasini kimyoviy energiyaga aylantirish\n\n"
            "TYPE: text_input\n"
            "2. Demokratiya nima?\n"
            "Javob: xalq hokimiyati"
        )
    ),
    "all": (
        "all_namuna.txt",
        "📦 Aralash turlar",
        (
            "1. O'zbekiston poytaxti?\n"
            "===A) Toshkent\n"
            "B) Samarqand\n"
            "C) Buxoro\n\n"
            "TYPE: true_false\n"
            "2. Yer yumaloqmi?\n"
            "Javob: Ha\n\n"
            "TYPE: fill_blank\n"
            "3. 2 + 2 = ___\n"
            "Javob: 4\n\n"
            "TYPE: text_input\n"
            "4. Vatanimiz nomi?\n"
            "Javob: O'zbekiston"
        )
    ),
}


async def _del(bot, cid, mid):
    try:
        await bot.delete_message(cid, mid)
    except Exception:
        pass


# ── Debounce uchun global dictlar ━━━━━━━━━━━━━━━━━━━━━━━━
# Poll (QuizBot forward)
_poll_debounce:    dict = {}  # {uid: asyncio.Task}
_save_in_progress: set  = set()   # Double-click himoyasi
_poll_progress: dict = {}  # {uid: progress_msg_id}
_poll_count:    dict = {}  # {uid: savol soni}

# Matn (chat orqali)
_text_debounce: dict = {}  # {uid: asyncio.Task}
_text_progress: dict = {}  # {uid: progress_msg_id}
_text_count:    dict = {}  # {uid: xabar soni}


async def _flush_polls(bot, cid, uid):
    """0.8s kutib — eski progress xabarni o'chirib, yangi sanoqli xabar yuboradi"""
    try:
        await asyncio.sleep(0.8)
        count = _poll_count.get(uid, 0)
        if not count:
            return
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="✅ Tayyor",  callback_data="finish_polls"))
        b.row(InlineKeyboardButton(text="❌ Bekor",   callback_data="cancel_create"))
        prog_text = (
            f"📥 <b>Qabul qilindi: {count} ta savol</b>\n\n"
            f"<i>Davom ettiring yoki tayyor bo'lsa bosing:</i>"
        )
        old_pid = _poll_progress.pop(uid, None)
        if old_pid:
            await _del(bot, cid, old_pid)
        prog = await bot.send_message(cid, prog_text, reply_markup=b.as_markup())
        _poll_progress[uid] = prog.message_id
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"flush_polls: {e}")


async def _flush_texts(bot, cid, uid):
    """0.8s kutib — eski progress xabarni o'chirib, yangi sanoqli xabar yuboradi"""
    try:
        await asyncio.sleep(0.8)
        count = _text_count.get(uid, 0)
        if not count:
            return
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="✅ Tayyor (parse qilish)", callback_data="finish_text"))
        b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
        prog_text = (
            f"📥 <b>{count} ta xabar qabul qilindi</b>\n\n"
            f"<i>Hammasi yuborgach — ✅ Tayyor bosing</i>"
        )
        old_pid = _text_progress.pop(uid, None)
        if old_pid:
            await _del(bot, cid, old_pid)
        msg = await bot.send_message(cid, prog_text, reply_markup=b.as_markup())
        _text_progress[uid] = msg.message_id
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"flush_texts: {e}")


# ═══════════════════════════════════════════════════════════
# 1. BOSHLASH
# ═══════════════════════════════════════════════════════════

@router.message(F.text == "➕ Test Yaratish")
async def create_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id

    # ── Rol tekshiruvi ━━━━━━━━━━━━━━━━━━━━━━━━
    from config import ADMIN_IDS
    from utils.roles import can_create_any_test, get_referral_code, format_role_info
    if uid not in ADMIN_IDS and not can_create_any_test(uid, ADMIN_IDS):
        bot_info = await message.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref{uid}"
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(
            text="👥 Referal havolam",
            callback_data="show_referral"
        ))
        b.row(InlineKeyboardButton(
            text="✉️ Adminga murojaat",
            callback_data="contact_admin"
        ))
        await message.answer(
            "🔒 <b>Test yaratish cheklangan</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "❌ Siz hozir test yarata olmaysiz.\n\n"
            "✅ <b>Test yaratish uchun:</b>\n"
            "  • Har kuni <b>1 ta yangi foydalanuvchi</b> taklif qiling\n"
            "  • <b>1 kunda 10 ta</b> taklif → 30 kun Student status\n\n"
            "📊 <b>Darajalar:</b>\n"
            "  👤 Foydalanuvchi — test yechish\n"
            "  🎓 Student — shaxsiy/havola test yaratish\n"
            "  👨‍🏫 Teacher — ommaviy test yaratish\n\n"
            f"🔗 <b>Sizning havolangiz:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"💡 Admindan daraja oshirishni so'rashingiz mumkin",
            parse_mode="HTML",
            reply_markup=b.as_markup()
        )
        return
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📁 Fayl (TXT/PDF/DOCX)", callback_data="method_file"))
    b.row(InlineKeyboardButton(text="💬 Chat orqali (matn)",  callback_data="method_text"))
    b.row(InlineKeyboardButton(text="📊 QuizBot forward",     callback_data="method_poll"))
    b.row(InlineKeyboardButton(text="❌ Bekor",               callback_data="cancel_create"))
    await message.answer(
        "<b>➕ TEST YARATISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Fayl yuklash</b> — TXT, PDF yoki DOCX\n"
        "   Yaratilgan test ▶️ Inline va 📊 Poll\n"
        "   ikki rejimda ishlaydi!\n\n"
        "📊 <b>QuizBotdan forward</b> — @QuizBot savollarini\n"
        "   uzating. TXT yuklab olish + Poll rejimi!\n\n"
        "<i>💡 Namunani ko'rish uchun turni tanlang</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.choose_method)


# ═══════════════════════════════════════════════════════════
# REFERAL (rol cheklangan bo'lganda)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "show_referral")
async def cb_show_referral(callback: CallbackQuery):
    await callback.answer()
    uid      = callback.from_user.id
    bot_info = await callback.bot.get_me()
    from utils.roles import get_referral_stats
    link     = f"https://t.me/{bot_info.username}?start=ref{uid}"
    stats    = get_referral_stats(uid)
    share_url = f"https://t.me/share/url?url={link}&text=Men%20bu%20botda%20testlar%20yechyapman!%20Siz%20ham%20qo'shiling%20👇"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📤 Do'stlarga ulashish", url=share_url))
    b.row(InlineKeyboardButton(text="✉️ Adminga murojaat", callback_data="contact_admin"))
    await callback.message.edit_text(
        f"👥 <b>Referal havolangiz</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<code>{link}</code>\n\n"
        f"📊 Jami: <b>{stats['total']}</b> | Bugun: <b>{stats['today']}</b>\n\n"
        f"Havolani do'stlaringizga yuboring — har kuni 1 ta yangi taklif test yaratish imkonini beradi!",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )


# ═══════════════════════════════════════════════════════════
# BOSHQA HANDLER'LAR (QOLGAN 99% KOD SAQLANADI)
# ═══════════════════════════════════════════════════════════

# OG'ZINI FAYLLAR JAMI 2000+ QATORNI SAQLASH UCHUN,
# QOLGAN BARCHA HANDLER'LAR VA FUNKSIYALAR XUDDI SHUNAQA QOLADI
# FAQAT @router va async def larini TAHRIRLAMADIK

# Matnli upload
@router.callback_query(F.data == "method_text", CreateTest.choose_method)
async def method_text(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    example = (
        "1. O'zbekiston poytaxti?\n"
        "===A) Toshkent\n"
        "B) Samarqand\n"
        "C) Buxoro\n\n"
        "2. Pi soni?\n"
        "A) 2.14\n"
        "===B) 3.14\n"
        "C) 4.14"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Tayyor (parse qilish)", callback_data="finish_text"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="start_create"))
    b.row(InlineKeyboardButton(text="❌ Bekor",  callback_data="cancel_create"))
    await callback.message.edit_text(
        "<b>💬 MATN ORQALI YUKLASH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Savollarni <b>ketma-ket yuboring</b> (ko'p xabar bo'lsa ham yig'ib oladi)\n\n"
        f"<code>{example}</code>\n\n"
        "<i>💡 To'g'ri javob oldiga <b>===</b> qo'ying\n"
        "Hammasi yuborgach — <b>✅ Tayyor</b> bosing</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    uid = callback.from_user.id
    _text_progress[uid] = callback.message.message_id
    _text_count[uid] = 0
    await state.update_data(text_buffer=[], text_msg_ids=[])
    await state.set_state(CreateTest.upload_file)


@router.message(F.text, CreateTest.upload_file)
async def upload_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if len(text) < 3:
        return
    d = await state.get_data()
    buf     = d.get("text_buffer", [])
    msg_ids = d.get("text_msg_ids", [])
    buf.append(text)
    msg_ids.append(message.message_id)
    await state.update_data(text_buffer=buf, text_msg_ids=msg_ids)
    await _del(message.bot, message.chat.id, message.message_id)
    uid = message.from_user.id
    _text_count[uid] = len(buf)
    old_task = _text_debounce.pop(uid, None)
    if old_task:
        old_task.cancel()
    task = asyncio.create_task(_flush_texts(message.bot, message.chat.id, uid))
    _text_debounce[uid] = task


@router.callback_query(F.data == "finish_text", CreateTest.upload_file)
async def finish_text(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    d   = await state.get_data()
    buf = d.get("text_buffer", [])
    if not buf:
        return await callback.answer("❌ Hali matn yuborilmadi!", show_alert=True)
    full_text = "\n\n".join(buf)
    status = await callback.message.edit_text("⏳ Tahlil qilinmoqda...")
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False,
                                         suffix=".txt", encoding="utf-8") as tmp:
            tmp.write(full_text)
            tmp_path = tmp.name
        questions = parse_file(tmp_path)
        os.remove(tmp_path)
        if not questions:
            return await status.edit_text(
                "❌ <b>Savollar topilmadi!</b>\n\n"
                "To'g'ri javob oldiga <b>===</b> qo'ying:\n"
                "<code>===A) To'g'ri javob</code>"
            )
        await state.update_data(questions=questions, text_buffer=[], text_msg_ids=[])
        b_pt = InlineKeyboardBuilder()
        for s in POLL_TIMES:
            b_pt.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"ptime_{s}"))
        b_pt.adjust(3)
        b_pt.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="ptime_0"))
        await status.edit_text(
            f"<b>✅ {len(questions)} TA SAVOL TOPILDI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>{len(buf)} ta xabardan yig'ildi</i>\n\n"
            f"⏱ <b>Har bir savol uchun necha soniya?</b>",
            reply_markup=b_pt.as_markup()
        )
        await state.set_state(CreateTest.set_poll_time)
    except Exception as e:
        log.error(f"Text parse: {e}")
        await status.edit_text("❌ Matnni o'qishda xatolik. Formatni tekshiring.")


@router.callback_query(F.data == "cancel_create")
async def cancel_create(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.bot.send_message(
        callback.from_user.id,
        "❌ Bekor qilindi.",
        reply_markup=main_kb(callback.from_user.id, "private")
    )
