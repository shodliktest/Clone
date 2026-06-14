"""➕ TEST YARATISH — Fayl yoki QuizBot forward"""
import os, re, logging, tempfile, asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from utils.parser import parse_file
from utils.states import CreateTest
from utils.db import create_test
from keyboards.keyboards import subject_kb, difficulty_kb, visibility_kb, main_kb, test_created_kb

def _get_user_subjects(uid):
    from utils.ram_cache import get_user_custom_subjects
    return get_user_custom_subjects(uid)

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
# 2. MATN ORQALI YUKLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "method_text", CreateTest.choose_method)
async def method_text(callback: CallbackQuery, state: FSMContext):
    """Chat orqali matn — ko'p xabar bo'lsa ham hammasi yig'iladi"""
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
    # Yo'riqnoma xabarini progress sifatida saqlash (birinchi matn kelganda o'chiriladi)
    uid = callback.from_user.id
    _text_progress[uid] = callback.message.message_id
    _text_count[uid] = 0
    await state.update_data(text_buffer=[], text_msg_ids=[])
    await state.set_state(CreateTest.upload_file)


@router.message(F.text, CreateTest.upload_file)
async def upload_text(message: Message, state: FSMContext):
    """Kelgan matn xabarlarini bufferga yig'ish"""
    text = message.text.strip()
    if len(text) < 3:
        return

    d = await state.get_data()
    buf     = d.get("text_buffer", [])
    msg_ids = d.get("text_msg_ids", [])

    buf.append(text)
    msg_ids.append(message.message_id)
    await state.update_data(text_buffer=buf, text_msg_ids=msg_ids)

    # Foydalanuvchi xabarini o'chirish
    await _del(message.bot, message.chat.id, message.message_id)

    # Debounce: 0.8s kutib, oxirgi sanoq bilan bitta progress xabar yuboradi
    uid = message.from_user.id
    _text_count[uid] = len(buf)
    old_task = _text_debounce.pop(uid, None)
    if old_task:
        old_task.cancel()
    task = asyncio.create_task(_flush_texts(message.bot, message.chat.id, uid))
    _text_debounce[uid] = task


@router.callback_query(F.data == "finish_text", CreateTest.upload_file)
async def finish_text(callback: CallbackQuery, state: FSMContext):
    """Buffer to'plangan matnlarni birga parse qilish"""
    await callback.answer()
    d   = await state.get_data()
    buf = d.get("text_buffer", [])

    if not buf:
        return await callback.answer("❌ Hali matn yuborilmadi!", show_alert=True)

    # Hammasini birlashtirish
    full_text = "\n\n".join(buf)

    status = await callback.message.edit_text("⏳ Tahlil qilinmoqda...")
    try:
        import tempfile, os
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

        await state.update_data(
            questions=questions,
            text_buffer=[],
            text_msg_ids=[],
            upload_status_id=status.message_id
        )
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


@router.callback_query(F.data == "method_file", CreateTest.choose_method)
async def method_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    b = InlineKeyboardBuilder()
    for key, (_, type_name, _) in SAMPLE_TYPES.items():
        b.add(InlineKeyboardButton(text=type_name, callback_data=f"sample_{key}"))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
    await callback.message.edit_text(
        "<b>📁 TEST TURINI TANLANG</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Turni bosing → namuna ko'rasiz\n"
        "Shu formatda fayl yuborasiz:\n\n"
        "<i>💡 Yaratilgan test ▶️ Inline va 📊 Poll\n"
        "ikki rejimda ishlaydi!</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.upload_file)


@router.callback_query(F.data.startswith("sample_"), CreateTest.upload_file)
async def send_sample(callback: CallbackQuery):
    await callback.answer()
    key = callback.data[7:]
    fname, type_name, mono_text = SAMPLE_TYPES.get(key, SAMPLE_TYPES["mcq"])
    fpath = os.path.join(SAMPLES_DIR, fname)

    if os.path.exists(fpath):
        await callback.message.answer_document(
            FSInputFile(fpath, filename=fname),
            caption=f"📄 <b>{type_name}</b> — namuna fayli"
        )

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Boshqa tur",  callback_data="method_file"))
    b.row(InlineKeyboardButton(text="❌ Bekor",        callback_data="cancel_create"))
    await callback.message.edit_text(
        f"<b>📄 {type_name.upper()} FORMATI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Namuna:\n\n"
        f"<code>{mono_text}</code>\n\n"
        f"⏳ <b>Faylingizni yuboring...</b>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )


@router.message(F.document, CreateTest.upload_file)
async def upload_file(message: Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.lower().endswith((".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm")):
        return await message.answer("❌ Faqat TXT, PDF yoki DOCX fayllar qabul qilinadi!")

    status = await message.answer("⏳ Fayl tahlil qilinmoqda...")
    try:
        file   = await message.bot.get_file(doc.file_id)
        suffix = os.path.splitext(doc.file_name)[1].lower()

        # Avval fayl yaratamiz, keyin yuklaymiz (lock muammosini oldini oladi)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
        await message.bot.download_file(file.file_path, tmp_path)

        questions = parse_file(tmp_path)
        # Rasmli savollar uchun tmp_path ni state da saqlaymiz
        has_img_qs = any(q.get("_has_image") for q in questions)
        if has_img_qs:
            await state.update_data(_tmp_path=tmp_path)  # O'chirilmaydi
        else:
            try: os.remove(tmp_path)
            except Exception: pass
        await _del(message.bot, message.chat.id, message.message_id)

        if not questions:
            return await status.edit_text(
                "❌ <b>Savollar topilmadi!</b>\n\n"
                "Quyidagi formatlar qo\'llab-quvvatlanadi:\n"
                "• <b>Standart:</b> <code>===A) To\'g\'ri javob</code>\n"
                "• <b>==== + #:</b> Savol → ==== → #To\'g\'ri → ====\n"
                "• <b>Jadval:</b> Savol | To\'g\'ri | Muqobil...\n"
                "• <b>PDF:</b> ? savol → =Javob\n\n"
                "Namunani ko\'rish uchun turni qaytadan tanlang."
            )

        total    = len(questions)
        unmarked = sum(1 for q in questions if not q.get("_marked"))

        await state.update_data(questions=questions, _file_id=doc.file_id)
        await state.set_state(CreateTest.upload_file)  # state saqlanadi

        if unmarked > 0:
            b = InlineKeyboardBuilder()
            b.button(text="🔡 Seryalik javob",    callback_data="uj_serial")
            b.button(text="🤖 AI bilan yechish",   callback_data="uj_ai")
            b.button(text="📨 Adminga murojaat",   callback_data="uj_admin")
            b.button(text="▶️ Shundayicha davom",  callback_data="uj_skip")
            b.adjust(1)
            await status.edit_text(
                f"📋 <b>{total} TA SAVOL TOPILDI</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Belgilangan: <b>{total - unmarked}</b> ta\n"
                f"❓ Belgilanmagan: <b>{unmarked}</b> ta\n\n"
                f"<i>To\'g\'ri javob aniqlanmagan. Nima qilamiz?</i>",
                parse_mode="HTML",
                reply_markup=b.as_markup()
            )
        else:
            await _ask_poll_time(status, state, total)

    except Exception as e:
        log.error(f"upload_file xato: {e}", exc_info=True)
        await status.edit_text("❌ Faylni o\'qishda xatolik. Boshqa fayl yoki formatni sinab ko\'ring.")


async def _ask_poll_time(msg, state, q_count: int):
    b = InlineKeyboardBuilder()
    for s in POLL_TIMES:
        b.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"ptime_{s}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="ptime_0"))
    await msg.edit_text(
        f"<b>✅ {q_count} TA SAVOL TOPILDI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ <b>Har bir savol uchun necha soniya?</b>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_poll_time)


# ═══════════════════════════════════════════════════════════
# BELGILANMAGAN SAVOLLAR — Seryalik / AI / Admin
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "uj_serial", CreateTest.upload_file)
async def uj_serial(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    b = InlineKeyboardBuilder()
    for ltr in ["A", "B", "C", "D", "E"]:
        b.button(text=f"✅ {ltr}", callback_data=f"serial_{ltr}")
    b.button(text="⬅️ Orqaga", callback_data="uj_back")
    b.adjust(5, 1)
    await cb.message.edit_text(
        "🔡 <b>SERYALIK JAVOB</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Barcha belgilanmagan savollarda\n"
        "qaysi variant to\'g\'ri bo\'ladi?\n\n"
        "<i>Masalan: barcha javoblar B bo\'lsa → B ni tanlang</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("serial_"), CreateTest.upload_file)
async def apply_serial(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    letter = cb.data.split("_")[1]
    idx    = ord(letter.upper()) - ord("A")
    d      = await state.get_data()
    questions = d.get("questions", [])
    changed = 0
    for q in questions:
        if q.get("_marked"):
            continue
        opts = q.get("options", [])
        if opts and idx < len(opts):
            q["correct"] = opts[idx]
            changed += 1
    await state.update_data(questions=questions)
    await cb.message.edit_text(
        f"✅ <b>{letter} seryalik qo\'llandi!</b>\n"
        f"📝 {changed} ta savol yangilandi.\n\n"
        f"<i>Davom etamiz...</i>"
    )
    await asyncio.sleep(0.8)
    await _ask_poll_time(cb.message, state, len(questions))


@router.callback_query(F.data == "uj_ai", CreateTest.upload_file)
async def uj_ai(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d         = await state.get_data()
    questions = d.get("questions", [])
    file_id   = d.get("_file_id", "")
    docx_path = d.get("_tmp_path", "")
    unmarked  = [q for q in questions if not q.get("_marked")]
    img_qs    = [q for q in unmarked if q.get("_has_image")]
    txt_qs    = [q for q in unmarked if not q.get("_has_image")]
    has_images = len(img_qs) > 0
    has_texts  = len(txt_qs) > 0

    await cb.message.edit_text(
        "🤖 <b>AI BILAN YECHISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Belgilanmagan: {len(unmarked)} ta\n"
        + (f"🖼️ Rasmli: {len(img_qs)} ta (Gemini Vision)\n" if has_images else "")
        + (f"📝 Matnli: {len(txt_qs)} ta (Groq/OpenAI)\n" if has_texts else "")
        + "\n<i>AI ishlamoqda...</i>",
        parse_mode="HTML"
    )
    try:
        # Matnli savollar — oddiy AI
        if has_texts:
            questions = await _ai_solve(questions,
                                        cb.message if not has_images else None)

        # Rasmli savollar — Gemini Vision
        if has_images:
            path = docx_path
            if not path or not os.path.exists(path):
                if file_id:
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                        path = tmp.name
                    fi = await cb.message.bot.get_file(file_id)
                    await cb.message.bot.download_file(fi.file_path, path)
            if path and os.path.exists(path):
                questions = await _solve_image_questions(questions, path, cb.message)

        await state.update_data(questions=questions)
        solved     = sum(1 for q in questions if q.get("_ai_solved"))
        total_un   = sum(1 for q in questions if not q.get("_marked") or q.get("_ai_solved"))
        img_solved = sum(1 for q in questions if q.get("_ai_solved") and q.get("_has_image"))
        txt_solved = solved - img_solved
        total_q    = len(questions)
        await cb.message.edit_text(
            f"✅ <b>AI tugatdi!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Jami: <b>{total_q}</b> ta savol\n"
            + (f"📝 Matnli: <b>{txt_solved}</b> ta yechildi\n" if has_texts else "")
            + (f"🖼️ Rasmli: <b>{img_solved}</b> ta yechildi\n" if has_images else "")
            + f"✅ Yechildi: <b>{solved}</b> / <b>{len(unmarked)}</b> ta\n"
            + ("\n⚠️ <i>Ayrimlari yechilmadi — seryalik qo\'llanildi</i>\n" if solved < len(unmarked) else "")
            + "\n<i>Davom etamiz...</i>",
            parse_mode="HTML"
        )
        await asyncio.sleep(1)
        await _ask_poll_time(cb.message, state, len(questions))
    except Exception as e:
        log.error(f"AI solve xato: {e}", exc_info=True)
        b = InlineKeyboardBuilder()
        b.button(text="🔡 Seryalik javob",    callback_data="uj_serial")
        b.button(text="📨 Adminga murojaat",  callback_data="uj_admin")
        b.button(text="▶️ Shundayicha davom", callback_data="uj_skip")
        b.adjust(1)
        await cb.message.edit_text(
            f"❌ <b>AI xatolik berdi</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{str(e)[:200]}</code>\n\n"
            "Boshqa usulni tanlang:",
            reply_markup=b.as_markup()
        )


@router.callback_query(F.data == "uj_admin", CreateTest.upload_file)
async def uj_admin(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    from config import ADMIN_IDS
    d         = await state.get_data()
    questions = d.get("questions", [])
    unmarked  = sum(1 for q in questions if not q.get("_marked"))
    uid       = cb.from_user.id
    uname     = cb.from_user.full_name or str(uid)
    for aid in ADMIN_IDS:
        try:
            await cb.bot.send_message(
                aid,
                f"📨 <b>Yordam so\'rovi</b>\n"
                f"👤 {uname} (<code>{uid}</code>)\n"
                f"📋 {len(questions)} savol, {unmarked} belgilanmagan"
            )
        except Exception:
            pass
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Orqaga", callback_data="uj_back")
    await cb.message.edit_text(
        "📨 <b>Admin xabardor qilindi!</b>\n\n"
        "Tez orada javob olasiz.",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data == "uj_skip", CreateTest.upload_file)
async def uj_skip(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d = await state.get_data()
    await _ask_poll_time(cb.message, state, len(d.get("questions", [])))


@router.callback_query(F.data == "uj_back", CreateTest.upload_file)
async def uj_back(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d         = await state.get_data()
    questions = d.get("questions", [])
    total     = len(questions)
    unmarked  = sum(1 for q in questions if not q.get("_marked"))
    b = InlineKeyboardBuilder()
    b.button(text="🔡 Seryalik javob",   callback_data="uj_serial")
    b.button(text="🤖 AI bilan yechish",  callback_data="uj_ai")
    b.button(text="📨 Adminga murojaat", callback_data="uj_admin")
    b.button(text="▶️ Shundayicha davom", callback_data="uj_skip")
    b.adjust(1)
    await cb.message.edit_text(
        f"📋 <b>{total} TA SAVOL</b>\n"
        f"✅ Belgilangan: <b>{total - unmarked}</b>\n"
        f"❓ Belgilanmagan: <b>{unmarked}</b>\n\n"
        f"<i>Qanday davom etamiz?</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )


# ═══════════════════════════════════════════════════════════
# AI PROVIDER KONFIGURATSIYA
# ═══════════════════════════════════════════════════════════
# Secrets ga quyidagilardan BIRINI yoki BARCHASINI yozing:
#
# Groq (bepul, tez):
#   GROQ_API_KEY = "gsk_xxx"
#   GROQ_API_KEY1 = "gsk_yyy"   ← ko'p kalit rotatsiya uchun
#
# OpenAI:
#   OPENAI_API_KEY = "sk-xxx"
#
# Together AI (bepul modellari bor):
#   TOGETHER_API_KEY = "xxx"
#
# OpenRouter (100+ model, ko'plari bepul):
#   OPENROUTER_API_KEY = "sk-or-xxx"
#
# Har qanday OpenAI-compatible API:
#   CUSTOM_AI_API_KEY = "xxx"
#   CUSTOM_AI_API_URL = "https://your-api.com/v1/chat/completions"
#   CUSTOM_AI_MODEL   = "your-model-name"
#
# Bir vaqtda bir nechta provider yozilsa — hammasi ishlatiladi,
# limit tugasa avtomatik keyingisiga o'tadi.
# ═══════════════════════════════════════════════════════════

_AI_PROVIDERS = [
    # 1. Groq — tez, bepul (birinchi)
    {
        "name":      "Groq",
        "url":       "https://api.groq.com/openai/v1/chat/completions",
        "model":     "llama-3.3-70b-versatile",
        "key_names": ["GROQ_API_KEY"] + [f"GROQ_API_KEY{i}" for i in range(1, 21)],
    },
    # 2. Gemini — ko'p limit, aniq (ikkinchi)
    {
        "name":      "Gemini",
        "url":       "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model":     "gemini-2.0-flash",
        "key_names": ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY{i}" for i in range(1, 11)],
    },
    # 3. Together AI
    {
        "name":      "Together AI",
        "url":       "https://api.together.xyz/v1/chat/completions",
        "model":     "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "key_names": ["TOGETHER_API_KEY"] + [f"TOGETHER_API_KEY{i}" for i in range(1, 11)],
    },
    # 4. OpenRouter
    {
        "name":      "OpenRouter",
        "url":       "https://openrouter.ai/api/v1/chat/completions",
        "model":     "meta-llama/llama-3.3-70b-instruct:free",
        "key_names": ["OPENROUTER_API_KEY"] + [f"OPENROUTER_API_KEY{i}" for i in range(1, 11)],
    },
    # 5. OpenAI
    {
        "name":      "OpenAI",
        "url":       "https://api.openai.com/v1/chat/completions",
        "model":     "gpt-4o-mini",
        "key_names": ["OPENAI_API_KEY"] + [f"OPENAI_API_KEY{i}" for i in range(1, 11)],
    },
]


def _load_ai_clients():
    """
    Secrets dan barcha mavjud AI kalitlarini yuklaydi.
    Qaytaradi: [(name, url, model, key), ...]
    """
    clients = []
    try:
        import streamlit as st
        sec = st.secrets
    except Exception:
        class _E:
            def get(self, k, d=""): return os.environ.get(k, d)
        sec = _E()

    # Custom provider
    c_url   = sec.get("CUSTOM_AI_API_URL", "")
    c_model = sec.get("CUSTOM_AI_MODEL", "gpt-3.5-turbo")
    for name in ["CUSTOM_AI_API_KEY"] + [f"CUSTOM_AI_API_KEY{i}" for i in range(1, 11)]:
        k = sec.get(name, "")
        if k and c_url:
            clients.append({"name": "Custom", "url": c_url, "model": c_model, "key": k})

    # Standart providerlar
    for p in _AI_PROVIDERS:
        for name in p["key_names"]:
            k = sec.get(name, "")
            if k:
                clients.append({"name": p["name"], "url": p["url"], "model": p["model"], "key": k})

    return clients



# ═══════════════════════════════════════════════════════════════
# GEMINI VISION — Rasmli savollar (daqiqada max 15 ta)
# ═══════════════════════════════════════════════════════════════

def _get_gemini_keys() -> list:
    keys = []
    try:
        import streamlit as st
        for n in ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY{i}" for i in range(1, 11)]:
            k = st.secrets.get(n, "")
            if k: keys.append(k)
    except Exception:
        pass
    if not keys:
        for n in ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY{i}" for i in range(1, 11)]:
            k = os.environ.get(n, "")
            if k: keys.append(k)
    return keys


async def _solve_image_questions(questions: list, docx_path: str, msg) -> list:
    """
    Rasmli savollarni Gemini Vision bilan yechadi.
    Qoidalar:
      - Faqat Gemini API (boshqa API lar yo'q)
      - Daqiqada max 15 ta * kalit_soni
      - Har so'rov orasida 5 soniya
      - 429 kelsa: kutib qayta urinish
    """
    import aiohttp, json, base64, zipfile, time

    gemini_keys = _get_gemini_keys()
    if not gemini_keys:
        log.warning("GEMINI_API_KEY topilmadi - rasmli savollar o'tkazib yuborildi")
        return questions

    img_unmarked = [
        (i, q) for i, q in enumerate(questions)
        if q.get("_has_image") and not q.get("_marked")
    ]
    if not img_unmarked:
        return questions

    log.info(f"Gemini Vision: {len(img_unmarked)} savol, {len(gemini_keys)} kalit")

    # DOCX ZIP dan rasmlarni olish
    img_cache = {}
    try:
        with zipfile.ZipFile(docx_path) as z:
            for name in z.namelist():
                if "word/media/" in name:
                    fname = os.path.basename(name)
                    img_cache[fname] = base64.b64encode(z.read(name)).decode()
    except Exception as e:
        log.error(f"Rasm ajratish: {e}")
        return questions

    key_idx = 0
    req_in_minute = 0
    minute_start = time.time()
    max_per_minute = 15 * len(gemini_keys)

    PROMPT = (
        "Medical/anatomy test image question. "
        "Identify the correct answer based on the image and options. "
        "Return ONLY JSON: {\"correct_idx\": N, \"explanation\": \"brief\"}"
    )

    def _bar(d, t, w=8):
        f = int(w * d / max(t, 1))
        return "█" * f + "░" * (w - f)

    solved = 0
    t0 = time.time()

    for n, (orig_idx, q) in enumerate(img_unmarked, 1):
        img_b64 = img_cache.get(q.get("_img_file", ""), "")
        if not img_b64:
            continue

        # Daqiqada limit nazorat
        now = time.time()
        if now - minute_start >= 60:
            req_in_minute = 0
            minute_start = now

        if req_in_minute >= max_per_minute:
            wait = 62 - (now - minute_start)
            if wait > 0:
                log.info(f"Gemini limit: {wait:.0f}s kutamiz")
                if msg:
                    try:
                        await msg.edit_text(
                            f"🖼️ <b>Gemini Vision...</b>\n"
                            f"[{_bar(n-1, len(img_unmarked))}] {n-1}/{len(img_unmarked)}\n"
                            f"⏳ Limit: {wait:.0f}s kutilmoqda...",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                await asyncio.sleep(wait)
                req_in_minute = 0
                minute_start = time.time()

        # Progress
        elapsed = time.time() - t0
        eta = int(elapsed / max(n-1,1) * (len(img_unmarked)-n+1)) if n>1 else len(img_unmarked)*7
        m2, s2 = divmod(eta, 60)
        if msg:
            try:
                await msg.edit_text(
                    f"🖼️ <b>Gemini Vision rasmlarni tahlil qilmoqda...</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"[{_bar(n-1, len(img_unmarked))}] {n-1}/{len(img_unmarked)} rasm\n"
                    f"📊 {solved} ta yechildi\n"
                    f"⏱ Qoldi: ~{m2}:{s2:02d}\n"
                    f"🔑 Gemini kalit {key_idx%len(gemini_keys)+1}/{len(gemini_keys)}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        opts_clean = [re.sub(r"^[A-Ha-h]\s*[).]\s*", "", o) for o in q.get("options", [])]
        question_text = (
            f"{PROMPT}\n\n"
            f"Question: {q.get('question', '')}\n"
            f"Options:\n" + "\n".join(f"{j}. {o}" for j, o in enumerate(opts_clean))
        )

        answered = False
        for attempt in range(len(gemini_keys) * 2):
            key = gemini_keys[key_idx % len(gemini_keys)]
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.0-flash:generateContent?key={key}"
            )
            payload = {
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                        {"text": question_text}
                    ]
                }],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 150}
            }

            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.post(
                        url, json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        rdata = await resp.json()

                if resp.status == 429:
                    key_idx += 1
                    wait_t = 62 if attempt >= len(gemini_keys)-1 else 10
                    log.warning(f"Gemini 429 ({wait_t}s kutamiz)")
                    await asyncio.sleep(wait_t)
                    if attempt >= len(gemini_keys)-1:
                        req_in_minute = 0
                        minute_start = time.time()
                    continue

                if resp.status != 200:
                    key_idx += 1
                    await asyncio.sleep(3)
                    continue

                raw = (
                    rdata.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "").strip()
                )
                raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
                result = json.loads(raw)
                ci = int(result.get("correct_idx", 0))
                ex = result.get("explanation", "")
                opts = q.get("options", [])
                if 0 <= ci < len(opts):
                    questions[orig_idx]["correct"]    = opts[ci]
                    questions[orig_idx]["explanation"] = f"🤖🖼️ {ex}" if ex else ""
                    questions[orig_idx]["_ai_solved"]  = True
                    questions[orig_idx]["_marked"]     = True
                    solved += 1
                req_in_minute += 1
                answered = True
                break

            except aiohttp.ClientError as e:
                log.warning(f"Gemini network: {e}")
                key_idx += 1
                await asyncio.sleep(3)
            except Exception as e:
                log.warning(f"Gemini parse: {e}")
                answered = True
                break

        if answered:
            await asyncio.sleep(5)  # Har so'rov orasida 5 soniya

    total_t = int(time.time() - t0)
    m3, s3 = divmod(total_t, 60)
    log.info(f"Gemini Vision: {solved}/{len(img_unmarked)} yechildi, {m3}:{s3:02d}")
    if msg:
        try:
            await msg.edit_text(
                f"✅ <b>Gemini Vision tugatdi!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🖼️ {solved}/{len(img_unmarked)} rasm yechildi\n"
                f"⏱ {m3}:{s3:02d}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    return questions


async def _ai_solve(questions: list, msg) -> list:
    """
    Universal AI yechish — Groq / OpenAI / Together / OpenRouter / Custom.
    Limit tugasa avtomatik keyingi kalit yoki providerga o'tadi.
    """
    import aiohttp, json, time

    clients = _load_ai_clients()
    if not clients:
        raise ValueError(
            "AI API kaliti topilmadi!\n"
            "Secrets ga qo'shing: GROQ_API_KEY = \"gsk_xxx\""
        )

    names = list(dict.fromkeys(c["name"] for c in clients))
    log.info(f"AI: {len(clients)} kalit, {names}")
    cli_idx = 0

    async def _post(payload):
        nonlocal cli_idx
        for _ in range(len(clients)):
            cli = clients[cli_idx % len(clients)]
            p   = dict(payload)
            p["model"] = cli["model"]
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        cli["url"],
                        headers={"Authorization": f"Bearer {cli['key']}",
                                 "Content-Type": "application/json"},
                        json=p, timeout=aiohttp.ClientTimeout(total=90),
                    ) as r:
                        data = await r.json()
                err = data.get("error", {})
                if err:
                    code = str(err.get("type","")) + str(err.get("code",""))
                    if any(w in code for w in ["rate_limit","quota","tokens","capacity"]):
                        cli_idx += 1
                        tried = attempt + 1
                        log.warning(
                            f"[{cli['name']}] kalit "
                            f"{cli_idx % len(clients) + 1}/{len(clients)} limit "
                            f"({tried}/{len(clients)} sinab ko'rildi)"
                        )
                        if tried >= len(clients):
                            # Barcha kalitlar limitda — 62s kutamiz (Groq: 1 daqiqa)
                            log.warning(
                                f"Barcha {len(clients)} kalit limitda. 62s kutamiz..."
                            )
                            await asyncio.sleep(62)
                            cli_idx = 0  # Qayta boshidan
                        else:
                            await asyncio.sleep(2)
                        continue
                    raise ValueError(f"[{cli['name']}] {err.get('message', str(err))}")
                return data
            except aiohttp.ClientError as e:
                log.warning(f"[{cli['name']}] xato: {e}")
                cli_idx += 1
        raise ValueError(f"Barcha {len(clients)} ta kalit/provider ishlamadi! ({names})")

    SYSTEM = (
        "You are an academic test expert. "
        "Answer each question correctly. "
        "Return ONLY JSON, no other text. "
        "Keep explanations under 10 words."
    )

    def _bar(done, total, w=10):
        f = int(w * done / max(total, 1))
        return "█" * f + "░" * (w - f)

    unmarked      = [(i, q) for i, q in enumerate(questions) if not q.get("_marked")]
    total_q       = len(unmarked)
    if not total_q:
        return questions

    batch_size    = 40
    total_batches = (total_q + batch_size - 1) // batch_size
    solved        = 0
    t0            = time.time()
    failed_batches = []  # Xato bo'lgan batchlar

    for bn, bs in enumerate(range(0, total_q, batch_size), 1):
        batch  = unmarked[bs:bs+batch_size]
        q_data = [
            {"idx": oi, "q": q.get("question",""),
             "opts": [re.sub(r"^[A-Ha-h]\s*[).]\s*","",o) for o in q.get("options",[])]}
            for oi, q in batch
        ]

        done_q  = (bn-1) * batch_size
        elapsed = time.time() - t0
        eta_sec = int(elapsed / max(bn-1,1) * (total_batches-bn+1)) if bn > 1 else total_batches * 8
        mins, secs = divmod(eta_sec, 60)
        eta_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        cur_provider = clients[cli_idx % len(clients)]["name"]

        if msg:
            try:
                await msg.edit_text(
                    f"🤖 <b>AI yechmoqda...</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"[{_bar(bn-1, total_batches)}] {bn-1}/{total_batches} batch\n"
                    f"📊 {done_q}/{total_q} savol\n"
                    f"⏱ Qoldi: ~{eta_str}\n"
                    f"🔑 {len(clients)} kalit | {cur_provider}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        USER = (
            "Solve and return JSON:\n"
            "[{\"idx\": N, \"correct_idx\": 0, \"explanation\": \"short\"}]\n\n"
            f"{json.dumps(q_data, ensure_ascii=False)}"
        )
        try:
            data = await _post({
                "messages":    [{"role":"system","content":SYSTEM},
                                {"role":"user","content":USER}],
                "max_tokens":  4000,
                "temperature": 0.05,
            })
            txt = data["choices"][0]["message"]["content"].strip()
            txt = re.sub(r"```json\s*|\s*```", "", txt).strip()
            for item in json.loads(txt):
                oi = item.get("idx", -1)
                ci = item.get("correct_idx", 0)
                ex = item.get("explanation", "")
                if 0 <= oi < len(questions):
                    opts = questions[oi].get("options", [])
                    if 0 <= ci < len(opts):
                        questions[oi]["correct"]    = opts[ci]
                        questions[oi]["explanation"] = f"🤖 {ex}" if ex else ""
                        questions[oi]["_ai_solved"]  = True
                        solved += 1
        except Exception as e:
            log.error(f"Batch {bn} xato: {e}")
            # Xato bo'lgan batchni keyinroq qayta urinish uchun saqlaymiz
            failed_batches.append((bn, bs))
        else:
            log.info(f"AI batch {bn}/{total_batches}: {solved} ta yechildi")

    # Xato bo'lgan batchlarni qayta urinib ko'ramiz (1 marta)
    if failed_batches:
        log.info(f"Xato batchlar ({len(failed_batches)} ta) qayta urinilmoqda...")
        if msg:
            try:
                await msg.edit_text(
                    f"🔄 <b>Qayta urinilmoqda...</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ {len(failed_batches)} ta batch qayta yuborilmoqda",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        await asyncio.sleep(65)  # Rate limit uchun kutamiz
        for bn, bs in failed_batches:
            batch  = unmarked[bs:bs+batch_size]
            q_data = [
                {"idx": oi, "q": q.get("question",""),
                 "opts": [re.sub(r"^[A-Ha-h]\s*[).]\s*","",o)
                          for o in q.get("options",[])]}
                for oi, q in batch
            ]
            USER = (
                "Savollarni yeching va JSON qaytaring:\n"
                "[{\"idx\": N, \"correct_idx\": 0, \"explanation\": \"izoh\"}]\n\n"
                f"Savollar:\n{json.dumps(q_data, ensure_ascii=False)}"
            )
            try:
                data = await _post({
                    "messages": [{"role":"system","content":SYSTEM},
                                 {"role":"user","content":USER}],
                    "max_tokens": 4000, "temperature": 0.05,
                })
                txt = data["choices"][0]["message"]["content"].strip()
                txt = re.sub(r"```json\s*|\s*```", "", txt).strip()
                for item in json.loads(txt):
                    oi = item.get("idx", -1)
                    ci = item.get("correct_idx", 0)
                    ex = item.get("explanation", "")
                    if 0 <= oi < len(questions):
                        opts = questions[oi].get("options", [])
                        if 0 <= ci < len(opts):
                            questions[oi]["correct"]    = opts[ci]
                            questions[oi]["explanation"] = f"🤖 {ex}" if ex else ""
                            questions[oi]["_ai_solved"]  = True
                            solved += 1
                log.info(f"Retry batch {bn}: muvaffaqiyatli")
            except Exception as e:
                log.error(f"Retry batch {bn} ham xato: {e}")

    total_t = int(time.time() - t0)
    m, s = divmod(total_t, 60)
    log.info(f"AI yakunlandi: {solved}/{total_q} savol yechildi, {m}:{s:02d}")
    if msg:
        try:
            await msg.edit_text(
                f"✅ <b>AI (matn) tugatdi!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 {solved}/{total_q} savol yechildi\n"
                f"⏱ {m}:{s:02d}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    return questions

@router.callback_query(F.data == "method_poll", CreateTest.choose_method)
async def method_poll(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(questions=[], poll_time=30)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Tayyor", callback_data="finish_polls"))
    b.row(InlineKeyboardButton(text="❌ Bekor",  callback_data="cancel_create"))
    await callback.message.edit_text(
        "<b>📊 QUIZBOT FORWARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ @QuizBot ga o'ting\n"
        "2️⃣ Quiz savollarini bu yerga forward qiling\n"
        "3️⃣ Hammasi yuborilgach — <b>✅ Tayyor</b> bosing\n\n"
        "<i>💡 Faqat 'Viktorina' (Quiz) turi qabul qilinadi!</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    # Yo'riqnoma xabarini progress sifatida saqlash (birinchi poll kelganda o'chiriladi)
    uid = callback.from_user.id
    _poll_progress[uid] = callback.message.message_id
    _poll_count[uid] = 0
    await state.set_state(CreateTest.waiting_polls)


@router.message(F.poll, CreateTest.waiting_polls)
async def catch_poll(message: Message, state: FSMContext):
    if message.poll.type != "quiz":
        await _del(message.bot, message.chat.id, message.message_id)
        return await message.answer("❌ Faqat <b>Viktorina (Quiz)</b> turi qabul qilinadi!")

    import re as _re
    p    = message.poll
    lts  = ["A)", "B)", "C)", "D)", "E)", "F)"]
    opts = [f"{lts[i]} {op.text}" for i, op in enumerate(p.options)]

    # QuizBot [N/N] raqamlarini olib tashlash
    clean_q = _re.sub(r"^\[\d+/\d+\]\s*", "", p.question).strip()

    d  = await state.get_data()
    qs = d.get("questions", [])
    qs.append({
        "type":        "multiple_choice",
        "question":    clean_q,
        "options":     opts,
        "correct":     opts[p.correct_option_id],
        "explanation": p.explanation or "",
        "points":      1
    })
    await state.update_data(questions=qs)

    # Poll xabarini o'chirish
    await _del(message.bot, message.chat.id, message.message_id)

    # Debounce: 0.8s kutib, oxirgi sanoq bilan bitta progress xabar yuboradi
    uid = message.from_user.id
    _poll_count[uid] = len(qs)
    old_task = _poll_debounce.pop(uid, None)
    if old_task:
        old_task.cancel()
    task = asyncio.create_task(_flush_polls(message.bot, message.chat.id, uid))
    _poll_debounce[uid] = task


@router.callback_query(F.data == "finish_polls", CreateTest.waiting_polls)
async def finish_polls(callback: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d.get("questions"):
        return await callback.answer("❌ Hali savol yo'q!", show_alert=True)
    await callback.answer()
    b = InlineKeyboardBuilder()
    for s in POLL_TIMES:
        b.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"ptime_{s}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Vaqtsiz", callback_data="ptime_0"))
    b.row(InlineKeyboardButton(text="❌ Bekor",   callback_data="cancel_create"))
    await callback.message.edit_text(
        f"<b>⏱ POLL VAQTI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ {len(d['questions'])} ta savol qabul qilindi!\n\n"
        f"Har bir savol uchun necha soniya?",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_poll_time)


@router.callback_query(F.data.startswith("ptime_"))
async def set_pt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    pt  = int(callback.data[6:])
    await state.update_data(poll_time=pt)
    ptt = f"{pt} soniya/savol" if pt else "Vaqtsiz"
    await callback.message.edit_text(
        f"⏱ <b>Savol vaqti: {ptt}</b>\n\n"
        f"📁 Qaysi fanga tegishli?",
        reply_markup=subject_kb(extra_subjects=_get_user_subjects(callback.from_user.id))
    )
    await state.set_state(CreateTest.set_subject)


# ═══════════════════════════════════════════════════════════
# 4. FAN, MAVZU, SOZLAMALAR
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("subj_"), CreateTest.set_subject)
async def set_subj(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    s = callback.data[5:]
    if s == "other":
        return await callback.message.edit_text(
            "✏️ <b>Fan nomini yozing:</b>\n"
            "<i>Masalan: Fizika, Ona tili, Tarix...</i>"
        )
    await state.update_data(category=s)
    await callback.message.edit_text(
        f"📁 Fan: <b>{s}</b>\n\n"
        f"<b>🏷 Test nomini yozing:</b>"
    )
    await state.set_state(CreateTest.set_title)


@router.message(F.text, CreateTest.set_subject)
async def subj_text(message: Message, state: FSMContext):
    subj = message.text.strip()
    await state.update_data(category=subj)
    await _del(message.bot, message.chat.id, message.message_id)
    # Maxsus fan nomini RAM ga saqlash
    from utils.ram_cache import add_user_custom_subject
    add_user_custom_subject(message.from_user.id, subj)
    await message.answer("<b>🏷 Test nomini yozing:</b>")
    await state.set_state(CreateTest.set_title)


@router.message(F.text, CreateTest.set_title)
async def set_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await _del(message.bot, message.chat.id, message.message_id)
    await message.answer(
        f"<b>📊 QIYINLIK DARAJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mavzu: <b>{message.text.strip()}</b>",
        reply_markup=difficulty_kb()
    )
    await state.set_state(CreateTest.set_difficulty)


@router.callback_query(F.data.startswith("diff_"), CreateTest.set_difficulty)
async def set_diff(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(difficulty=callback.data[5:])
    b = InlineKeyboardBuilder()
    for m in [15, 20, 30, 45, 60, 90, 120]:
        b.add(InlineKeyboardButton(text=f"⏱ {m}daq", callback_data=f"tlim_{m}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="tlim_0"))
    await callback.message.edit_text(
        "<b>⏱ UMUMIY VAQT LIMITI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Test uchun umumiy necha daqiqa?",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_time_limit)


@router.callback_query(F.data.startswith("tlim_"), CreateTest.set_time_limit)
async def set_tlim(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(time_limit=int(callback.data[5:]))
    b = InlineKeyboardBuilder()
    for p in [50, 60, 70, 80, 90, 100]:
        b.add(InlineKeyboardButton(text=f"{p}%", callback_data=f"pass_{p}"))
    b.adjust(3)
    await callback.message.edit_text(
        "<b>🎯 O'TISH FOIZI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Testdan o'tish uchun minimum foiz?",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_passing)


@router.callback_query(F.data.startswith("pass_"), CreateTest.set_passing)
async def set_pass(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(passing_score=int(callback.data[5:]))
    b = InlineKeyboardBuilder()
    for a in [1, 2, 3, 5, 10]:
        b.add(InlineKeyboardButton(text=f"🔄 {a}x", callback_data=f"att_{a}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="att_0"))
    await callback.message.edit_text(
        "<b>🔄 URINISHLAR SONI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Har foydalanuvchi necha marta ishlashi mumkin?",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_attempts)


@router.callback_query(F.data.startswith("att_"), CreateTest.set_attempts)
async def set_att(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(max_attempts=int(callback.data[4:]))
    await callback.message.edit_text(
        "<b>🔒 TEST MAXFIYLIGI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🌍 <b>Ommaviy</b> — hamma ko'ra oladi\n"
        "🔗 <b>Ssilka</b> — faqat havola orqali\n"
        "🔒 <b>Shaxsiy</b> — faqat siz",
        reply_markup=visibility_kb()
    )
    await state.set_state(CreateTest.set_visibility)


# ═══════════════════════════════════════════════════════════
# 5. SAQLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("vis_"), CreateTest.set_visibility)
async def save_test(callback: CallbackQuery, state: FSMContext):
    await callback.answer("⏳")
    uid = callback.from_user.id
    # Double-click himoyasi: bir vaqtda faqat bitta saqlash
    if uid in _save_in_progress:
        return await callback.answer("⏳ Test saqlanmoqda...", show_alert=True)
    _save_in_progress.add(uid)
    try:
        await _do_save_test(callback, state)
    finally:
        _save_in_progress.discard(uid)


async def _do_save_test(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    chosen_vis = callback.data[4:]

    # ── Ommaviy test faqat teacher/admin ━━━━━━━━━━━━━━━━━━━━━━━━
    if chosen_vis == "public":
        from config import ADMIN_IDS
        from utils.roles import can_create_public_test
        if not can_create_public_test(uid, ADMIN_IDS):
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(text="🔗 Havola orqali", callback_data="vis_link"))
            b.row(InlineKeyboardButton(text="🔒 Shaxsiy",       callback_data="vis_private"))
            b.row(InlineKeyboardButton(text="❌ Bekor",         callback_data="cancel_create"))
            await callback.message.edit_text(
                "🔒 <b>Ommaviy test cheklangan</b>\n\n"
                "❌ Ommaviy test yaratish faqat <b>Teacher</b> va <b>Admin</b> uchun.\n\n"
                "✅ Student sifatida:\n"
                "  🔗 <b>Havola orqali</b> — havola bilganlarga\n"
                "  🔒 <b>Shaxsiy</b> — faqat siz\n\n"
                "💡 Teacher bo'lish uchun adminga murojaat qiling.",
                parse_mode="HTML",
                reply_markup=b.as_markup()
            )
            return
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    d = await state.get_data()
    td = {
        "title":         d.get("title", "Nomsiz"),
        "category":      d.get("category", "Boshqa"),
        "difficulty":    d.get("difficulty", "medium"),
        "visibility":    chosen_vis,
        "time_limit":    d.get("time_limit", 0),
        "poll_time":     d.get("poll_time", 30),
        "passing_score": d.get("passing_score", 60),
        "max_attempts":  d.get("max_attempts", 0),
        "questions":     d.get("questions", []),
    }
    tid  = await create_test(
        callback.from_user.id, td,
        creator_name=callback.from_user.full_name or "",
        creator_username=callback.from_user.username or "",
    )
    bu   = (await callback.bot.me()).username
    link = f"https://t.me/{bu}?start={tid}"
    pt_t = f"{td['poll_time']}s/savol" if td.get("poll_time") else "Vaqtsiz"
    tl_t = f"{td['time_limit']} daqiqa" if td.get("time_limit") else "Cheksiz"
    diff_map = {
        "easy": "🟢 Oson", "medium": "🟡 O'rtacha",
        "hard": "🔴 Qiyin", "expert": "⚡ Ekspert"
    }
    diff = diff_map.get(td["difficulty"], "")
    vis_map = {"public": "🌍 Ommaviy", "link": "🔗 Ssilka", "private": "🔒 Shaxsiy"}
    vis  = vis_map.get(td["visibility"], "")

    await state.clear()

    # Kalit javoblar matni
    qs   = td["questions"]
    keys = (
        f"🔑 <b>JAVOBLAR KALITI</b> — <code>{tid}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for i, q in enumerate(qs, 1):
        corr = q.get("correct", "?")
        keys += f"<b>{i}.</b> {corr}\n"

    # Test haqida to'liq ma'lumot + kalit + tugmalar
    info_text = (
        "🎉 <b>TEST MUVAFFAQIYATLI YARATILDI!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Kod: <code>{tid}</code>\n"
        f"🔗 Ssilka: <code>{link}</code>\n\n"
        f"📝 Mavzu: <b>{td['title']}</b>\n"
        f"📁 Fan: {td['category']}\n"
        f"📊 Qiyinlik: {diff}\n"
        f"🔒 Ko'rinish: {vis}\n"
        f"📋 Savollar: <b>{len(qs)} ta</b>\n"
        f"⏱ Umumiy vaqt: {tl_t}\n"
        f"⏱ Poll vaqti: {pt_t}\n"
        f"🎯 O'tish foizi: <b>{td['passing_score']}%</b>\n\n"
        "👇 <b>Boshlash usulini tanlang:</b>"
    )

    try:
        await callback.message.edit_text(info_text, reply_markup=test_created_kb(tid, bu))
    except Exception:
        await callback.message.answer(info_text, reply_markup=test_created_kb(tid, bu))

    # Kalitni alohida xabar sifatida yuborish
    if len(keys) <= 4000:
        await callback.message.answer(keys)

    # ── Baza guruhiga e'lon qilish ──
    try:
        from utils.baza_publisher import publish_to_baza
        await publish_to_baza(
            bot           = callback.bot,
            tid           = tid,
            title         = td["title"],
            questions     = td["questions"],
            creator_id    = uid,
            creator_name  = callback.from_user.full_name or "",
            bot_username  = bu,
            category      = td.get("category", ""),
            difficulty    = td.get("difficulty", "medium"),
            passing_score = td.get("passing_score", 60),
        )
    except Exception as _bpe:
        import logging
        logging.getLogger(__name__).warning(f"Baza publish xato: {_bpe}")


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
