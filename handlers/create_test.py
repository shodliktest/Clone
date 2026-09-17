"""➕ TEST YARATISH — Fayl yoki QuizBot forward"""
import os, re, logging, tempfile, asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from utils.parser import parse_file, check_images_in_file
from utils import file_fingerprint as fp
from utils.states import CreateTest
from utils.db import create_test
from keyboards.keyboards import subject_kb, difficulty_kb, visibility_kb, main_kb, test_created_kb


async def bump_fingerprint_seen_safe(file_hash: str):
    """fp.bump_fingerprint_seen() ni xatoni yutib chaqiradi — asosiy oqim to'xtamasin."""
    if not file_hash:
        return
    try:
        await fp.bump_fingerprint_seen(file_hash)
    except Exception:
        pass

def _get_user_subjects(uid):
    from utils.ram_cache import get_user_custom_subjects
    return get_user_custom_subjects(uid)


def _validate_parsed_questions(questions: list) -> str | None:
    """Parse natijasini AI chaqirmasdan tekshiradi.

    None -> parser natijasi bot formatiga yaroqli.
    String -> foydalanuvchiga ko'rsatiladigan format xatosi.
    """
    if not questions:
        return "Savollar topilmadi — fayl formati bot tanigan formatlardan biriga mos emas."

    for n, q in enumerate(questions, 1):
        if not isinstance(q, dict):
            return f"{n}-savol noto'g'ri tuzilgan."
        question = str(q.get("question", "") or "").strip()
        if len(question) < 2:
            return f"{n}-savolda savol matni topilmadi."
        qtype = str(q.get("type", "multiple_choice") or "multiple_choice")
        if qtype in ("multiple_choice", "multi_select"):
            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                return (f"{n}-savolda variantlar yetarli emas "
                        f"(topilgan: {len(opts) if isinstance(opts, list) else 0} ta).")
            clean = [str(x).strip() for x in opts if str(x).strip()]
            if len(clean) < 2 or len({x.casefold() for x in clean}) < 2:
                return f"{n}-savol variantlari noto'g'ri yoki takrorlangan."
    return None


def _format_repair_keyboard():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🤖 AI bilan formatni tuzatish", callback_data="format_ai_repair"))
    b.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_create"))
    return b.as_markup()


def _format_error_text(file_name: str, reason: str) -> str:
    return (
        f"❌ <b>«{file_name}» — FORMAT XATO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ {reason}\n\n"
        "Oddiy parser hech qanday AI chaqirmasdan faylni tekshirdi, "
        "lekin bot formatiga mos natija chiqmadi.\n\n"
        "🤖 <b>AI bilan formatni tuzatish</b> — fayldagi xom matnni "
        "o'qib, bot formatiga keltiradi. To'g'ri javobni AI bu bosqichda "
        "belgilamaydi. Keyin alohida javob aniqlash bosqichi ishlaydi.\n\n"
        "Quyidagidan birini tanlang:"
    )


def _extract_text_for_ai_repair(path: str) -> str:
    """AI repair tugmasi bosilgandagina xom matnni ajratib beradi."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".csv"):
        for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
            try:
                return open(path, "r", encoding=enc, errors="replace").read()
            except Exception:
                pass
        return ""
    if ext == ".doc":
        try:
            from utils.parser import _convert_doc
            converted = _convert_doc(path)
            if converted and converted != path:
                return _extract_text_for_ai_repair(converted)
        except Exception as e:
            log.warning(f"AI repair DOC text extraction: {e}")
        return ""
    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(path)
            parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
            return "\n".join(parts)
        except Exception as e:
            log.warning(f"AI repair DOCX text extraction: {e}")
            return ""
    if ext == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n".join((page.extract_text() or "") for page in pdf.pages)
        except Exception as e:
            log.warning(f"AI repair PDF text extraction: {e}")
            return ""
    if ext in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
                    if vals:
                        parts.append(" | ".join(vals))
            wb.close()
            return "\n".join(parts)
        except Exception as e:
            log.warning(f"AI repair XLSX text extraction: {e}")
            return ""
    return ""


async def _show_format_error(status, state, tmp_path: str, file_name: str, reason: str, file_id: str = ""):
    """Format xatosida faylni o'chirmaydi; AI repair uchun path'ni state'da saqlaydi."""
    await state.update_data(
        _format_repair_tmp_path=tmp_path,
        _format_repair_file_name=file_name,
        _format_repair_file_id=file_id,
        _format_repair_reason=reason,
        _file_name=file_name,
    )
    await state.set_state(CreateTest.upload_file)
    await status.edit_text(
        _format_error_text(file_name, reason),
        parse_mode="HTML",
        reply_markup=_format_repair_keyboard(),
    )

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
# Forward pairing registry: {uid: {source_message_id: Future[file_id|None]}}.
# Future is created at the very start of the photo handler, so a concurrently
# arriving Quiz can wait for the preceding photo upload instead of racing it.
_photo_registry: dict = {}
_photo_registry_lock: dict = {}
_channel_upload_lock = asyncio.Lock()


def _get_photo_registry_lock(uid: int) -> asyncio.Lock:
    lock = _photo_registry_lock.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _photo_registry_lock[uid] = lock
    return lock


def _register_photo(uid: int, message_id: int) -> asyncio.Future:
    reg = _photo_registry.setdefault(uid, {})
    fut = reg.get(message_id)
    if fut is None:
        fut = asyncio.get_running_loop().create_future()
        reg[message_id] = fut
    return fut


def _cleanup_photo_registry(uid: int):
    reg = _photo_registry.get(uid)
    if reg is not None and not reg:
        _photo_registry.pop(uid, None)
        _photo_registry_lock.pop(uid, None)


# aiogram handle_as_tasks=True bilan har bir update ALOHIDA asyncio.Task
# sifatida, bir-biriga nisbatan PARALLEL ishga tushadi. Foydalanuvchi
# QuizBot'dan bir nechta xabarni (rasm, poll, rasm, poll...) tez ketma-ket
# forward qilganda, ularning handlerlari deyarli bir vaqtda ishlab
# ketishi mumkin — natijada _pending_photo bir-birining ustidan yozilib
# yoki "questions" ro'yxati eskirib qolishi (lost update) mumkin edi.
# Shuning uchun bitta foydalanuvchining waiting_polls xabarlarini
# QAT'IY KETMA-KET ishlashga majburlaymiz — boshqa foydalanuvchilarga
# ta'sir qilmaydi.
_poll_locks: dict = {}  # {uid: asyncio.Lock}


def _get_poll_lock(uid: int) -> asyncio.Lock:
    lock = _poll_locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _poll_locks[uid] = lock
    return lock


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
    b.row(InlineKeyboardButton(text="📋 Anonim viktorina forward", callback_data="method_regular_poll"))
    b.row(InlineKeyboardButton(text="❌ Bekor",               callback_data="cancel_create"))
    await message.answer(
        "<b>➕ TEST YARATISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Fayl yuklash</b> — TXT, PDF yoki DOCX\n"
        "   Yaratilgan test ▶️ Inline va 📊 Poll\n"
        "   ikki rejimda ishlaydi!\n\n"
        "📊 <b>QuizBotdan forward</b> — @QuizBot savollarini\n"
        "   uzating. TXT yuklab olish + Poll rejimi!\n\n"
        "📋 <b>Anonim viktorina forward</b> — to'g'ri javob\n"
        "   Telegram tomonidan berilmagani uchun, har\n"
        "   savoldan keyin javobni o'zingiz belgilaysiz.\n\n"
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
        # Matn parse qilinadi, lekin bu yerda AI umuman chaqirilmaydi.
        # Format xato bo'lsa vaqtinchalik TXT AI repair tugmasi uchun saqlanadi.
        questions = parse_file(tmp_path)
        parse_error = _validate_parsed_questions(questions)
        if parse_error:
            await state.update_data(
                _format_repair_tmp_path=tmp_path,
                _format_repair_file_name="Chat matni.txt",
                _format_repair_file_id="",
                _format_repair_reason=parse_error,
            )
            return await status.edit_text(
                _format_error_text("Chat matni.txt", parse_error),
                parse_mode="HTML",
                reply_markup=_format_repair_keyboard(),
            )
        os.remove(tmp_path)

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
        "<i>💡 Bir nechta fayl yuborishingiz mumkin —\n"
        "bittadan ketma-ket yoki birga (albom)\n"
        "qilib. Tugagach ✅ Tugatdim tugmasini bosing.</i>\n\n"
        "<i>💡 Yaratilgan test ▶️ Inline va 📊 Poll\n"
        "ikki rejimda ishlaydi!</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    await state.update_data(_multi_pending=[], _multi_done=[], _multi_status_msg_id=None)
    await state.set_state(CreateTest.upload_files_multi)


@router.callback_query(F.data.startswith("sample_"), CreateTest.upload_files_multi)
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


async def _upload_images_to_channel(bot, questions: list) -> tuple:
    """
    Rasmli savollarning rasmlarini Telegram STORAGE_CHANNEL_ID kanaliga
    yuklaydi va qaytgan file_id'ni savolga yozadi (q["photo"] = file_id).

    Supabase Storage ENDI ISHLATILMAYDI — "quiz-images" bucket loyihada
    yaratilmagan bo'lishi mumkin va shu sabab avval barcha rasmlar
    404 "Bucket not found" bilan yuklanmay qolgan edi. Rasmlar faqat
    Telegram orqali, id yordamida saqlanadi/olib kelinadi.

    Qaytaradi: (questions, uploaded, failed, total_img) — chaqiruvchi
    tomon foydalanuvchiga natija haqida xabar bera olishi uchun.
    """
    from config import STORAGE_CHANNEL_ID
    from aiogram.types import BufferedInputFile
    from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError

    media_channel = STORAGE_CHANNEL_ID
    total_img = sum(1 for q in questions if q.get("_img_bytes"))

    if not media_channel:
        log.warning("STORAGE_CHANNEL_ID sozlanmagan — rasmlar yuklanmadi")
        for q in questions:
            q.pop("_img_bytes", None)
            q.pop("_img_ext", None)
        return questions, 0, total_img, total_img

    # Telegram bitta chatga taxminan 1 xabar/soniya limitini qo'yadi.
    # Har bir yuborishdan oldin shu oraliqni kutamiz — shunda flood control'ga
    # deyarli hech qachon uchramaymiz (proaktiv throttling).
    MIN_INTERVAL = 1.1  # soniya, xabarlar orasidagi minimal oraliq
    MAX_ATTEMPTS = 8    # RetryAfter kelsa ham rasm baribir tushib qolmasin

    uploaded = failed = 0
    last_send_ts = 0.0

    for idx, q in enumerate(questions):
        img_bytes = q.get("_img_bytes")
        if not img_bytes:
            continue
        img_ext = q.get("_img_ext", ".png").lstrip(".")
        fname   = f"q{idx+1}.{img_ext}"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            # Proaktiv throttling: oldingi yuborishdan beri yetarli vaqt
            # o'tmagan bo'lsa, kutib turamiz.
            elapsed = asyncio.get_event_loop().time() - last_send_ts
            if elapsed < MIN_INTERVAL:
                await asyncio.sleep(MIN_INTERVAL - elapsed)

            try:
                photo = BufferedInputFile(img_bytes, filename=fname)
                msg = await bot.send_photo(
                    media_channel, photo,
                    caption=f"📷 Savol #{idx+1}",
                    disable_notification=True,
                )
                last_send_ts = asyncio.get_event_loop().time()
                if msg.photo:
                    q["photo"] = msg.photo[-1].file_id
                    uploaded += 1
                q.pop("_img_bytes", None)
                q.pop("_img_ext", None)
                break

            except TelegramRetryAfter as e:
                # Telegram aniq qancha kutish kerakligini aytadi — shuncha
                # kutamiz va HECH QACHON hisobdan chiqarmaymiz (urinishni
                # sarflamaymiz, chunki bu bizning xatomiz emas).
                wait = e.retry_after + 1
                log.warning(
                    f"Rasm #{idx+1}: flood control, {wait}s kutilmoqda "
                    f"(urinish {attempt}/{MAX_ATTEMPTS})"
                )
                await asyncio.sleep(wait)
                last_send_ts = asyncio.get_event_loop().time()
                continue

            except TelegramNetworkError as e:
                log.warning(f"Rasm #{idx+1}: tarmoq xatosi, qayta urinilmoqda: {e}")
                await asyncio.sleep(2 * attempt)
                continue

            except Exception as e:
                if attempt == MAX_ATTEMPTS:
                    log.error(f"Rasm #{idx+1} yuklanmadi (oxirgi urinish): {e}")
                    q.pop("_img_bytes", None)
                    q.pop("_img_ext", None)
                    failed += 1
                else:
                    await asyncio.sleep(min(2 * attempt, 10))
        else:
            # for-else: MAX_ATTEMPTS marta RetryAfter/NetworkError bo'lib,
            # baribir break bo'lmagan bo'lsa ham rasmni yo'qotmaymiz.
            failed += 1
            q.pop("_img_bytes", None)
            q.pop("_img_ext", None)
            log.error(f"Rasm #{idx+1} yuklanmadi: {MAX_ATTEMPTS} urinishdan keyin ham muvaffaqiyatsiz")

    log.info(f"Rasmlar Telegram STORAGE_CHANNEL_ID'ga: {uploaded} muvaffaqiyatli, {failed} xato")
    return questions, uploaded, failed, total_img


@router.message(F.document, CreateTest.upload_files_multi)
async def upload_files_multi_collect(message: Message, state: FSMContext):
    """
    Ko'p-fayl rejimi: har kelgan faylni faqat yuklab olib navbatga
    qo'shadi (hali parse qilmaydi). "✅ Tugatdim" bosilgach, fayllar
    ketma-ket _run_next_queued_file() orqali ishlanadi.
    """
    doc = message.document
    if not doc.file_name.lower().endswith((".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm")):
        return await message.answer("❌ Faqat TXT, PDF yoki DOCX fayllar qabul qilinadi!")

    d = await state.get_data()
    pending = d.get("_multi_pending", [])

    try:
        file   = await message.bot.get_file(doc.file_id)
        suffix = os.path.splitext(doc.file_name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
        await message.bot.download_file(file.file_path, tmp_path)
    except Exception as e:
        log.error(f"upload_files_multi_collect yuklab olish xato: {e}", exc_info=True)
        return await message.answer(f"❌ «{doc.file_name}» yuklab olinmadi. Qayta yuboring.")

    pending.append({"tmp_path": tmp_path, "file_name": doc.file_name})
    await state.update_data(_multi_pending=pending)
    await _del(message.bot, message.chat.id, message.message_id)

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=f"✅ Tugatdim ({len(pending)} ta fayl)", callback_data="multi_files_done"))
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
    text = (
        f"📎 <b>{len(pending)} ta fayl qabul qilindi:</b>\n"
        + "\n".join(f"  • {p['file_name']}" for p in pending[-10:])
        + "\n\nYana fayl yuborishingiz mumkin, yoki tugating 👇"
    )

    status_id = d.get("_multi_status_msg_id")
    edited = False
    if status_id:
        try:
            await message.bot.edit_message_text(
                text, chat_id=message.chat.id, message_id=status_id,
                parse_mode="HTML", reply_markup=b.as_markup()
            )
            edited = True
        except Exception:
            pass  # eski xabar o'chirilgan/tahrirlanmaydi — yangisini yuboramiz

    if not edited:
        sent = await message.answer(text, parse_mode="HTML", reply_markup=b.as_markup())
        await state.update_data(_multi_status_msg_id=sent.message_id)


@router.callback_query(F.data == "multi_files_done", CreateTest.upload_files_multi)
async def multi_files_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    d = await state.get_data()
    pending = d.get("_multi_pending", [])
    if not pending:
        return await callback.answer("❌ Hali birorta fayl yubormadingiz!", show_alert=True)

    first, *rest = pending
    # Faqat 1 ta fayl bo'lsa — A/B tanlovisiz, oddiy bitta-test oqimi
    is_multi = len(pending) > 1
    await state.update_data(_multi_pending=[], _multi_queue=rest, _multi_done=[],
                             _multi_active=is_multi)
    await _run_next_queued_file(callback.message, state, first)


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

        # ── Fayl-tanish: bu fayl avval yuklanganmi? ──
        # Xuddi shu fayl (bayt darajasida bir xil) allaqachon test
        # sifatida saqlangan bo'lsa, qayta parse qilmasdan taklif qilamiz.
        try:
            file_hash = fp.compute_file_hash(tmp_path)
            existing  = await fp.find_existing_by_hash(file_hash)
        except Exception as _fp_e:
            log.warning(f"fingerprint tekshiruvi xato (davom etamiz): {_fp_e}")
            file_hash, existing = "", {}

        if existing:
            await bump_fingerprint_seen_safe(file_hash)
            await state.update_data(
                _pending_fp_hash=file_hash,
                _pending_fp_name=doc.file_name,
                _pending_fp_size=doc.file_size or 0,
                _pending_fp_tmp_path=tmp_path,   # "qaytadan yaratish" tanlansa kerak bo'ladi
            )
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(
                text="✅ Ha, shu testni ishlataman",
                callback_data=f"fp_use_{existing['test_id']}"
            ))
            b.row(InlineKeyboardButton(
                text="🔄 Yo'q, qaytadan yarataman",
                callback_data="fp_reparse"
            ))
            await status.edit_text(
                f"📎 <b>Bu fayl avval yuklangan!</b>\n\n"
                f"🆔 Test: <code>{existing['test_id']}</code>\n"
                f"📝 {existing.get('title') or '(nomsiz)'}\n"
                f"📋 {existing['question_count']} ta savol\n"
                f"🔁 Bu fayl {existing.get('upload_count', 1)} marta ko'rilgan\n\n"
                f"Qayta tahlil qilmasdan, mavjud testdan foydalanaymi?",
                reply_markup=b.as_markup()
            )
            # tmp_path ATAYLAB o'chirilmaydi — "qaytadan yaratish" bosilsa kerak bo'ladi.
            # Agar foydalanuvchi hech narsa bosmasa, eski vaqtinchalik fayllar
            # bot serverida qolib ketmasligi uchun quyidagi tozalash vazifasi
            # (_cleanup_stale_tmp_files) bot.py da davriy ishga tushiriladi.
            return

        # Yangi fayl (avval ko'rilmagan) — hashini state'da saqlaymiz,
        # test yaratilganda shu hash bilan ro'yxatga olinadi
        await state.update_data(
            _source_file_hash=file_hash,
            _source_file_name=doc.file_name,
            _source_file_size=doc.file_size or 0,
        )

        # MUHIM: parse bosqichida AI umuman chaqirilmaydi.
        questions = parse_file(tmp_path)
        parse_error = _validate_parsed_questions(questions)
        if parse_error:
            await _del(message.bot, message.chat.id, message.message_id)
            return await _show_format_error(
                status, state, tmp_path, doc.file_name, parse_error, doc.file_id
            )

        # Faqat parser muvaffaqiyatli bo'lsa temp faylni keyin tozalaymiz.
        has_img_qs = any(q.get("_has_image") for q in questions)
        if has_img_qs:
            await state.update_data(_tmp_path=tmp_path, _file_name=doc.file_name)
        else:
            await state.update_data(_file_name=doc.file_name)
            try: os.remove(tmp_path)
            except Exception: pass
        await _del(message.bot, message.chat.id, message.message_id)

        total    = len(questions)
        unmarked = sum(1 for q in questions if not q.get("_marked"))

        # Rasmli savollar bo'lsa — rasmlarni TG kanalga yuklab file_id olamiz
        img_count = sum(1 for q in questions if q.get("_img_bytes"))
        # Faylda umuman rasm bormi (parse qilolmagan bo'lsa ham)
        img_in_file = 0
        try:
            if os.path.exists(tmp_path):
                _ii = check_images_in_file(tmp_path)
                img_in_file = _ii.get("count", 0)
        except Exception:
            img_in_file = img_count

        img_upload_summary = ""
        if img_count > 0:
            await status.edit_text(
                f"🖼 <b>{img_count} ta rasm test bilan ulanmoqda...</b>\n"
                f"<i>Iltimos kuting</i>",
                parse_mode="HTML"
            )
            questions, up_ok, up_fail, up_total = await _upload_images_to_channel(message.bot, questions)
            if up_fail > 0:
                img_upload_summary = (
                    f"🖼 Rasmlar: <b>{up_ok}/{up_total}</b> muvaffaqiyatli, "
                    f"<b>{up_fail}</b> ta xato bo'ldi\n"
                )
        elif img_in_file > 0:
            log.info(f"Faylda {img_in_file} rasm bor, savolga bog'lanmadi")

        await state.update_data(questions=questions, _file_id=doc.file_id)
        await state.set_state(CreateTest.upload_file)  # state saqlanadi

        if unmarked > 0:
            b = InlineKeyboardBuilder()
            b.button(text="🔡 Seryalik javob",    callback_data="uj_serial")
            b.button(text="🤖 AI bilan yechish",   callback_data="uj_ai")
            b.button(text="📨 Adminga murojaat",   callback_data="uj_admin")
            b.button(text="▶️ Shundayicha davom",  callback_data="uj_skip")
            b.adjust(1)
            img_line = ""
            if img_count > 0:
                img_line = f"🖼 Rasmli: <b>{img_count}</b> ta (test bilan ulandi)\n"
            elif img_in_file > 0:
                img_line = f"⚠️ Faylda {img_in_file} rasm bor, lekin bog\'lanmadi\n"
            await status.edit_text(
                f"📋 <b>{total} TA SAVOL TOPILDI</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Belgilangan: <b>{total - unmarked}</b> ta\n"
                f"❓ Belgilanmagan: <b>{unmarked}</b> ta\n"
                + img_line + img_upload_summary +
                f"\n<i>To\'g\'ri javob aniqlanmagan. Nima qilamiz?</i>",
                parse_mode="HTML",
                reply_markup=b.as_markup()
            )
        else:
            if img_upload_summary:
                await status.edit_text(img_upload_summary, parse_mode="HTML")
            await _ask_poll_time(status, state, total)

    except Exception as e:
        log.error(f"upload_file xato: {e}", exc_info=True)
        await status.edit_text("❌ Faylni o\'qishda xatolik. Boshqa fayl yoki formatni sinab ko\'ring.")


async def _parse_and_present(bot, status, state, tmp_path: str, file_name: str, file_id: str = ""):
    """
    tmp_path'dagi faylni parse qilib, natijani (savollar soni,
    belgilanmagan savollar, rasm) ko'rsatadi. upload_file (bitta fayl)
    va _run_next_queued_file (ko'p fayl navbati) ikkalasi ham shu
    funksiyani ishlatadi — parse mantig'i bitta joyda saqlanadi.
    """
    # MUHIM: bu funksiya ham faqat parser qiladi; AI faqat tugma callback'ida ishlaydi.
    questions = parse_file(tmp_path)
    parse_error = _validate_parsed_questions(questions)
    if parse_error:
        return await _show_format_error(status, state, tmp_path, file_name, parse_error, file_id)

    has_img_qs = any(q.get("_has_image") for q in questions)
    if has_img_qs:
        await state.update_data(_tmp_path=tmp_path, _file_name=file_name)
    else:
        await state.update_data(_file_name=file_name)
        try: os.remove(tmp_path)
        except Exception: pass

    total    = len(questions)
    unmarked = sum(1 for q in questions if not q.get("_marked"))

    img_count = sum(1 for q in questions if q.get("_img_bytes"))
    img_in_file = 0
    try:
        if os.path.exists(tmp_path):
            _ii = check_images_in_file(tmp_path)
            img_in_file = _ii.get("count", 0)
    except Exception:
        img_in_file = img_count

    img_upload_summary = ""
    if img_count > 0:
        await status.edit_text(
            f"🖼 <b>{img_count} ta rasm test bilan ulanmoqda...</b>\n"
            f"<i>Iltimos kuting</i>",
            parse_mode="HTML"
        )
        questions, up_ok, up_fail, up_total = await _upload_images_to_channel(bot, questions)
        if up_fail > 0:
            img_upload_summary = (
                f"🖼 Rasmlar: <b>{up_ok}/{up_total}</b> muvaffaqiyatli, "
                f"<b>{up_fail}</b> ta xato bo'ldi\n"
            )
    elif img_in_file > 0:
        log.info(f"Faylda {img_in_file} rasm bor, savolga bog'lanmadi")

    await state.update_data(questions=questions, _file_id=file_id)

    if unmarked > 0:
        b = InlineKeyboardBuilder()
        b.button(text="🔡 Seryalik javob",    callback_data="uj_serial")
        b.button(text="🤖 AI bilan yechish",   callback_data="uj_ai")
        b.button(text="📨 Adminga murojaat",   callback_data="uj_admin")
        b.button(text="▶️ Shundayicha davom",  callback_data="uj_skip")
        b.adjust(1)
        img_line = ""
        if img_count > 0:
            img_line = f"🖼 Rasmli: <b>{img_count}</b> ta (test bilan ulandi)\n"
        elif img_in_file > 0:
            img_line = f"⚠️ Faylda {img_in_file} rasm bor, lekin bog\'lanmadi\n"
        await status.edit_text(
            f"📋 <b>«{file_name}» — {total} TA SAVOL TOPILDI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Belgilangan: <b>{total - unmarked}</b> ta\n"
            f"❓ Belgilanmagan: <b>{unmarked}</b> ta\n"
            + img_line + img_upload_summary +
            f"\n<i>To\'g\'ri javob aniqlanmagan. Nima qilamiz?</i>",
            parse_mode="HTML",
            reply_markup=b.as_markup()
        )
    else:
        if img_upload_summary:
            await status.edit_text(img_upload_summary, parse_mode="HTML")
        await _ask_poll_time(status, state, total)


async def _run_next_queued_file(msg, state, next_file: dict):
    """
    Ko'p-fayl navbatidagi keyingi faylni ishga tushiradi.
    next_file: {"tmp_path": str, "file_name": str}
    """
    status = await msg.answer(f"⏳ «{next_file['file_name']}» tahlil qilinmoqda...")
    await state.set_state(CreateTest.upload_file)
    try:
        await _parse_and_present(msg.bot, status, state, next_file["tmp_path"], next_file["file_name"])
    except Exception as e:
        log.error(f"_run_next_queued_file xato: {e}", exc_info=True)
        await status.edit_text(
            f"❌ «{next_file['file_name']}» faylini o'qishda xatolik. "
            "Keyingi faylga o'tamiz..."
        )
        await asyncio.sleep(1)
        # Bu faylni "0 savol" bilan tugagan deb belgilab, davom etamiz
        await state.update_data(questions=[], _file_name=next_file["file_name"])
        await _ask_poll_time(status, state, 0)


async def _ask_multi_mode(msg, state):
    """
    Barcha fayllar tahlil qilingandan va poll_time so'ralgandan keyin
    chaqiriladi. Foydalanuvchidan A/B tanlovini so'raydi:
      - Alohida  → har fayl o'z nomi bilan alohida test bo'ladi
      - Birlashtirilgan → barcha fayl savollari bitta testga qo'shiladi
    """
    d    = await state.get_data()
    done = d.get("_multi_done", [])
    total_q = sum(len(f["questions"]) for f in done)
    files_list = "\n".join(f"  • {f['file_name']} ({len(f['questions'])} ta savol)" for f in done)

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📂 Alohida testlar",       callback_data="multimode_separate"))
    b.row(InlineKeyboardButton(text="🔗 Bitta birlashtirilgan test", callback_data="multimode_merged"))
    await msg.answer(
        f"<b>✅ {len(done)} TA FAYL TAHLIL QILINDI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{files_list}\n\n"
        f"📊 Jami: <b>{total_q} ta savol</b>\n\n"
        f"<b>Qanday saqlaymiz?</b>\n"
        f"📂 <b>Alohida testlar</b> — har fayl o'z nomi bilan alohida test\n"
        f"🔗 <b>Birlashtirilgan</b> — barchasi bitta umumiy testga\n\n"
        f"<i>Sozlamalar (fan, qiyinlik, vaqt...) endi bir marta so'raladi\n"
        f"va barcha testlarga qo'llaniladi.</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("multimode_"))
async def set_multi_mode(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    mode = callback.data.split("_", 1)[1]  # "separate" | "merged"
    await state.update_data(_multi_mode=mode)
    mode_label = "📂 Alohida testlar" if mode == "separate" else "🔗 Birlashtirilgan test"
    await callback.message.edit_text(
        f"{mode_label}\n\n📁 Qaysi fanga tegishli?",
        reply_markup=subject_kb(extra_subjects=_get_user_subjects(callback.from_user.id))
    )
    await state.set_state(CreateTest.set_subject)


@router.callback_query(F.data.startswith("fp_use_"), CreateTest.upload_file)
async def fp_use_existing(callback: CallbackQuery, state: FSMContext):
    """
    Fayl-tanish: foydalanuvchi "Ha, shu testni ishlataman" tugmasini bosdi.
    Qayta parse qilinmaydi — mavjud testga havola beriladi.
    """
    tid = callback.data.replace("fp_use_", "", 1)
    await callback.answer("✅ Mavjud testdan foydalanilmoqda...")

    d = await state.get_data()
    tmp_path = d.get("_pending_fp_tmp_path")
    if tmp_path and os.path.exists(tmp_path):
        try: os.remove(tmp_path)
        except Exception: pass
    await state.clear()

    from utils.tg_db import get_test_full
    test = await get_test_full(tid)
    if not test:
        return await callback.message.edit_text(
            "❌ Test topilmadi (o\'chirilgan bo\'lishi mumkin). Iltimos faylni qaytadan yuboring."
        )

    bu   = (await callback.bot.me()).username
    link = f"https://t.me/{bu}?start={tid}"
    qc   = test.get("question_count") or len(test.get("questions", []))
    await callback.message.edit_text(
        f"✅ <b>Mavjud test ulandi!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>{test.get('title', 'Nomsiz')}</b>\n"
        f"📋 {qc} ta savol\n"
        f"🆔 <code>{tid}</code>\n\n"
        f"🔗 Havola: {link}",
        parse_mode="HTML",
        reply_markup=test_created_kb(tid, bu)
    )


@router.callback_query(F.data == "fp_reparse", CreateTest.upload_file)
async def fp_force_reparse(callback: CallbackQuery, state: FSMContext):
    """
    Fayl-tanish: foydalanuvchi "Yo'q, qaytadan yarataman" tugmasini bosdi.
    Saqlab qo'yilgan vaqtinchalik fayl qayta parse qilinadi.
    """
    await callback.answer("🔄 Qaytadan tahlil qilinmoqda...")
    d = await state.get_data()
    tmp_path  = d.get("_pending_fp_tmp_path")
    file_name = d.get("_pending_fp_name", "fayl")
    file_size = d.get("_pending_fp_size", 0)
    file_hash = d.get("_pending_fp_hash", "")

    if not tmp_path or not os.path.exists(tmp_path):
        return await callback.message.edit_text(
            "❌ Vaqtinchalik fayl topilmadi (muddati o\'tgan bo\'lishi mumkin).\n"
            "Iltimos faylni qaytadan yuboring."
        )

    status = callback.message
    await status.edit_text("⏳ Fayl qaytadan tahlil qilinmoqda...")

    try:
        # Hash "yangi manba" sifatida saqlanadi — yangi test yaratilsa,
        # shu fayl endi UNGA bog'lanadi (eski test o'zgarishsiz qoladi)
        await state.update_data(
            _source_file_hash=file_hash,
            _source_file_name=file_name,
            _source_file_size=file_size,
        )

        # Qayta parse ham AI'siz. Format xato bo'lsa yana tanlov beradi.
        questions = parse_file(tmp_path)
        parse_error = _validate_parsed_questions(questions)
        if parse_error:
            return await _show_format_error(status, state, tmp_path, file_name, parse_error)

        has_img_qs = any(q.get("_has_image") for q in questions)
        if has_img_qs:
            await state.update_data(_tmp_path=tmp_path, _file_name=file_name)
        else:
            await state.update_data(_file_name=file_name)
            try: os.remove(tmp_path)
            except Exception: pass

        total    = len(questions)
        unmarked = sum(1 for q in questions if not q.get("_marked"))

        img_count = sum(1 for q in questions if q.get("_img_bytes"))
        img_in_file = 0
        try:
            if os.path.exists(tmp_path):
                _ii = check_images_in_file(tmp_path)
                img_in_file = _ii.get("count", 0)
        except Exception:
            img_in_file = img_count

        img_upload_summary = ""
        if img_count > 0:
            await status.edit_text(
                f"🖼 <b>{img_count} ta rasm test bilan ulanmoqda...</b>\n"
                f"<i>Iltimos kuting</i>",
                parse_mode="HTML"
            )
            questions, up_ok, up_fail, up_total = await _upload_images_to_channel(callback.bot, questions)
            if up_fail > 0:
                img_upload_summary = (
                    f"🖼 Rasmlar: <b>{up_ok}/{up_total}</b> muvaffaqiyatli, "
                    f"<b>{up_fail}</b> ta xato bo'ldi\n"
                )
        elif img_in_file > 0:
            log.info(f"Faylda {img_in_file} rasm bor, savolga bog\'lanmadi")

        await state.update_data(questions=questions, _file_id=None)
        await state.set_state(CreateTest.upload_file)

        if unmarked > 0:
            b = InlineKeyboardBuilder()
            b.button(text="🔡 Seryalik javob",    callback_data="uj_serial")
            b.button(text="🤖 AI bilan yechish",   callback_data="uj_ai")
            b.button(text="📨 Adminga murojaat",   callback_data="uj_admin")
            b.button(text="▶️ Shundayicha davom",  callback_data="uj_skip")
            b.adjust(1)
            img_line = ""
            if img_count > 0:
                img_line = f"🖼 Rasmli: <b>{img_count}</b> ta (test bilan ulandi)\n"
            elif img_in_file > 0:
                img_line = f"⚠️ Faylda {img_in_file} rasm bor, lekin bog\'lanmadi\n"
            await status.edit_text(
                f"📋 <b>{total} TA SAVOL TOPILDI</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Belgilangan: <b>{total - unmarked}</b> ta\n"
                f"❓ Belgilanmagan: <b>{unmarked}</b> ta\n"
                + img_line + img_upload_summary +
                f"\n<i>To\'g\'ri javob aniqlanmagan. Nima qilamiz?</i>",
                parse_mode="HTML",
                reply_markup=b.as_markup()
            )
        else:
            if img_upload_summary:
                await status.edit_text(img_upload_summary, parse_mode="HTML")
            await _ask_poll_time(status, state, total)

    except Exception as e:
        log.error(f"fp_force_reparse xato: {e}", exc_info=True)
        await status.edit_text("❌ Faylni o\'qishda xatolik. Boshqa fayl yoki formatni sinab ko\'ring.")


async def _ask_poll_time(msg, state, q_count: int):
    """
    Bitta faylning savollari tayyor bo'lganda chaqiriladi.
    Ko'p-fayl rejimida (navbatda hali fayl bo'lsa) — joriy fayl
    natijasini saqlab, navbatdagi faylni avtomatik ishga tushiradi.
    Navbat tugagach — barcha fayllar uchun UMUMIY "necha soniya?"
    so'rovi (poll_time) faqat bir marta ko'rsatiladi.
    """
    d     = await state.get_data()
    queue = d.get("_multi_queue", [])
    if queue:
        # Joriy faylning natijasini "tugagan fayllar" ro'yxatiga qo'shamiz
        done = d.get("_multi_done", [])
        done.append({
            "file_name": d.get("_file_name", "Nomsiz"),
            "questions": d.get("questions", []),
        })
        next_file = queue.pop(0)
        await state.update_data(_multi_done=done, _multi_queue=queue)
        await _run_next_queued_file(msg, state, next_file)
        return

    # Navbat bo'sh — ko'p-fayl bo'lgan bo'lsa, oxirgi faylni ham "tugagan"ga qo'shamiz
    if d.get("_multi_active"):
        done = d.get("_multi_done", [])
        done.append({
            "file_name": d.get("_file_name", "Nomsiz"),
            "questions": d.get("questions", []),
        })
        await state.update_data(_multi_done=done)
        total_all = sum(len(f["questions"]) for f in done)
        q_count = total_all

    b = InlineKeyboardBuilder()
    for s in POLL_TIMES:
        b.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"ptime_{s}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="ptime_0"))
    txt = (
        f"<b>✅ {q_count} TA SAVOL TOPILDI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ <b>Har bir savol uchun necha soniya?</b>"
    )
    # Eski xabarni edit qilishga urinamiz, fail bo'lsa yangi yuboramiz
    try:
        await msg.edit_text(txt, parse_mode="HTML", reply_markup=b.as_markup())
    except Exception:
        try:
            await msg.answer(txt, parse_mode="HTML", reply_markup=b.as_markup())
        except Exception:
            try:
                await msg.bot.send_message(msg.chat.id, txt,
                                           parse_mode="HTML", reply_markup=b.as_markup())
            except Exception:
                pass
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


@router.callback_query(F.data == "format_ai_repair", CreateTest.upload_file)
async def format_ai_repair(cb: CallbackQuery, state: FSMContext):
    """Faqat foydalanuvchi tugmani bosganda xom matnni AI orqali bot formatiga keltiradi."""
    await cb.answer("🤖 AI formatni tuzatmoqda...")
    d = await state.get_data()
    tmp_path = d.get("_format_repair_tmp_path")
    file_name = d.get("_format_repair_file_name", "fayl")
    file_id = d.get("_format_repair_file_id", "")
    if not tmp_path or not os.path.exists(tmp_path):
        return await cb.message.edit_text(
            "❌ <b>Fayl vaqtinchalik xotirada topilmadi.</b>\n\n"
            "Iltimos faylni qaytadan yuboring.", parse_mode="HTML"
        )

    await cb.message.edit_text(
        f"🤖 <b>«{file_name}» formatini AI tuzatmoqda...</b>\n\n"
        "⏳ Xom matn ajratilmoqda va bot formatiga keltirilmoqda.\n"
        "<i>Bu bosqichda to'g'ri javob belgilanmaydi.</i>",
        parse_mode="HTML",
    )
    try:
        raw_text = _extract_text_for_ai_repair(tmp_path)
        if len(raw_text.strip()) < 20:
            raise ValueError("Fayldan yetarli xom matn ajratib bo'lmadi.")

        from utils.ai_engine import repair_questions_from_text
        repaired, provider = await repair_questions_from_text(raw_text)
        if not repaired:
            raise ValueError("AI bot formatida yaroqli savollar qaytara olmadi.")

        parse_error = _validate_parsed_questions(repaired)
        if parse_error:
            raise ValueError(f"AI tuzatgan format ham yaroqsiz: {parse_error}")

        await state.update_data(
            questions=repaired,
            _file_id=file_id,
            _file_name=file_name,
            _tmp_path=tmp_path,
            _format_repair_tmp_path=None,
            _format_repair_file_name=None,
            _format_repair_file_id=None,
            _format_repair_used=True,
        )
        # AI qayta tuzgan savollar uchun rasm oqimini hozircha parserga qoldiramiz.
        b = InlineKeyboardBuilder()
        b.button(text="🤖 AI bilan javoblarni aniqlash", callback_data="uj_ai")
        b.button(text="❌ Bekor qilish", callback_data="cancel_create")
        b.adjust(1)
        await cb.message.edit_text(
            f"✅ <b>Format AI orqali tuzatildi!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Provider: <b>{provider}</b>\n"
            f"📋 Topilgan: <b>{len(repaired)}</b> ta savol\n"
            f"❓ Javobi belgilanmagan: <b>{len(repaired)}</b> ta\n\n"
            "Endi to'g'ri javoblarni AI bilan aniqlash mumkin.",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
    except Exception as e:
        log.error(f"AI format repair xato: {e}", exc_info=True)
        b = _format_repair_keyboard()
        await cb.message.edit_text(
            f"❌ <b>AI bilan formatni tuzatib bo'lmadi.</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{str(e)[:500]}</code>\n\n"
            "Qayta urinishingiz yoki bekor qilishingiz mumkin.",
            parse_mode="HTML",
            reply_markup=b,
        )


@router.callback_query(F.data == "uj_ai", CreateTest.upload_file)
async def uj_ai(cb: CallbackQuery, state: FSMContext):
    """1-bosqich: izoh turini so'raydi"""
    await cb.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📖 To'liq izoh (asoslab)", callback_data="aimode_full"))
    b.row(InlineKeyboardButton(text="✂️ Qisqa izoh",            callback_data="aimode_short"))
    b.row(InlineKeyboardButton(text="🚫 Izohsiz (faqat javob)", callback_data="aimode_none"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga",                callback_data="uj_back"))
    await cb.message.edit_text(
        "🤖 <b>AI BILAN YECHISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Izoh qanday bo'lsin?</b>\n\n"
        "📖 <b>To'liq</b> — har javob asoslab tushuntiriladi (2-4 jumla)\n"
        "✂️ <b>Qisqa</b> — bir jumlalik izoh\n"
        "🚫 <b>Izohsiz</b> — faqat to'g'ri javob belgilanadi",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("aimode_"))
async def do_ai_solve(cb: CallbackQuery, state: FSMContext):
    """2-bosqich: tanlangan izoh turi bilan yechadi"""
    await cb.answer()
    explain_mode = cb.data[len("aimode_"):]  # full / short / none
    await state.update_data(_explain_mode=explain_mode)

    d         = await state.get_data()
    questions = d.get("questions", [])
    file_id   = d.get("_file_id", "")
    docx_path = d.get("_tmp_path", "")
    unmarked  = [q for q in questions if not q.get("_marked")]
    img_qs    = [q for q in unmarked if q.get("_has_image")]
    txt_qs    = [q for q in unmarked if not q.get("_has_image")]
    has_images = len(img_qs) > 0
    has_texts  = len(txt_qs) > 0

    mode_label = {"full": "To'liq izoh", "short": "Qisqa izoh", "none": "Izohsiz"}.get(explain_mode, "")
    await cb.message.edit_text(
        "🤖 <b>AI BILAN YECHISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Belgilanmagan: {len(unmarked)} ta\n"
        f"💬 Rejim: {mode_label}\n"
        + (f"🖼️ Rasmli: {len(img_qs)} ta (Gemini Vision)\n" if has_images else "")
        + (f"📝 Matnli: {len(txt_qs)} ta (Groq/OpenAI)\n" if has_texts else "")
        + "\n<i>AI ishlamoqda...</i>",
        parse_mode="HTML"
    )
    try:
        # Matnli savollar — oddiy AI
        if has_texts:
            questions = await _ai_solve(questions,
                                        cb.message if not has_images else None,
                                        explain_mode)

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
                questions = await _solve_image_questions(questions, path, cb.message, explain_mode)

        await state.update_data(questions=questions)
        await state.update_data(questions=questions)
        solved     = sum(1 for q in questions if q.get("_ai_solved"))
        img_solved = sum(1 for q in questions if q.get("_ai_solved") and q.get("_has_image"))
        img_total  = sum(1 for q in questions if q.get("_has_image"))
        txt_solved = solved - img_solved
        total_q    = len(questions)
        not_solved = len(unmarked) - solved

        stat_text = (
            f"✅ <b>AI tugatdi!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Jami: <b>{total_q}</b> ta savol\n"
            + (f"📝 Matnli: <b>{txt_solved}</b> ta yechildi\n" if has_texts else "")
            + (f"🖼️ Rasmli: <b>{img_solved}/{img_total}</b> ta yechildi\n" if has_images else "")
            + f"✅ Yechildi: <b>{solved}/{len(unmarked)}</b> ta\n"
            + (f"⚠️ Yechilmadi: <b>{not_solved}</b> ta\n" if not_solved > 0 else "")
        )
        # Avval edit qilamiz — progress xabarini yangilaymiz
        try:
            await cb.message.edit_text(stat_text + "\n<i>Davom etamiz...</i>",
                                        parse_mode="HTML")
        except Exception:
            pass
        # Keyin YANGI xabar — saqlanib qolsin
        try:
            await cb.bot.send_message(cb.from_user.id, stat_text, parse_mode="HTML")
        except Exception:
            pass
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
# AI PROVIDERLAR
# ═══════════════════════════════════════════════════════════
# Matnli savollar: Groq -> Gemini fallback.
# Rasmli savollar: Gemini Vision.
#
# Secrets:
#   GROQ_API_KEY = "gsk_..."
#   GROQ_API_KEY1 = "gsk_..."
#   GEMINI_API_KEY = "AQ..."
#   GEMINI_API_KEY1 = "AQ..."
#
# Ixtiyoriy environment sozlamalar:
#   GROQ_AI_MODEL=openai/gpt-oss-20b
#   GROQ_AI_MIN_INTERVAL=3.0
#   GROQ_AI_MAX_OUTPUT=900
#   GEMINI_AI_MODEL=gemini-3.6-flash
#   GEMINI_AI_MIN_INTERVAL=7.0
#   GEMINI_AI_MAX_OUTPUT=600
# ═══════════════════════════════════════════════════════════

async def _solve_image_questions(questions: list, docx_path: str, msg, explain_mode: str = "full") -> list:
    """Rasmli savollarni Gemini 3.6 Flash bilan rasm+matn sifatida yechadi.

    Gemini uchun alohida rate-gate ishlatiladi. Kalitlar credential rotation
    uchun; Google quota project darajasida bo'lgani sababli kalitlar quota'ni
    ko'paytiruvchi vosita sifatida hisoblanmaydi.
    """
    import zipfile, time, mimetypes
    from utils.ai_engine import solve_image

    img_unmarked = [
        (i, q) for i, q in enumerate(questions)
        if q.get("_has_image") and not q.get("_marked")
    ]
    if not img_unmarked:
        return questions

    img_cache = {}
    try:
        with zipfile.ZipFile(docx_path) as z:
            for name in z.namelist():
                if "word/media/" in name:
                    fname = os.path.basename(name)
                    img_cache[fname] = z.read(name)
    except Exception as e:
        log.error(f"Rasm ajratish: {e}")
        return questions

    _vexp = {
        "full": "O'zbek tilida 2-3 jumla: javob nima uchun to'g'ri ekanini tushuntiring.",
        "short": "O'zbek tilida 1 qisqa jumla.",
        "none": "Bo'sh satr.",
    }.get(explain_mode, "O'zbek tilida qisqa izoh.")

    solved = 0
    t0 = time.time()
    total = len(img_unmarked)

    def _bar(done, total, w=10):
        f = int(w * done / max(total, 1))
        return "█" * f + "░" * (w - f)

    for n, (orig_idx, q) in enumerate(img_unmarked, 1):
        image_bytes = img_cache.get(q.get("_img_file", ""))
        if not image_bytes:
            continue

        opts = [re.sub(r"^[A-Ha-h]\s*[).]\s*", "", o) for o in q.get("options", [])]
        prompt = (
            "Siz akademik test eksperti. Berilgan RASM va savol/variantlar asosida "
            "faqat dalilga tayangan holda javobni aniqlang. Rasmda yo'q faktni o'ylab "
            "topmang. Hisob-kitob bo'lsa tekshirib hisoblang. Avval rasmni o'qing, "
            "so'ng variantlarni solishtiring. Faqat quyidagi JSON objectni qaytaring: "
            '{"correct_idx":0,"explanation":"..."}. '
            "correct_idx 0-based bo'lib, variantlar ro'yxatidan tashqarida bo'lmasin. "
            f"Explanation: {_vexp}\n\n"
            f"Question: {q.get('question', '')}\n"
            "Options:\n" + "\n".join(f"{j}. {o}" for j, o in enumerate(opts))
        )

        if msg:
            try:
                elapsed = time.time() - t0
                eta = int(elapsed / max(n - 1, 1) * (total - n + 1)) if n > 1 else total * 8
                m, sec = divmod(eta, 60)
                await msg.edit_text(
                    f"🖼️ <b>Gemini Vision...</b>\n"
                    f"[{_bar(n-1, total)}] {n-1}/{total}\n"
                    f"📊 {solved} ta yechildi\n"
                    f"⏱ Qoldi: ~{m}:{sec:02d}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        try:
            mime = mimetypes.guess_type(q.get("_img_file", ""))[0] or "image/jpeg"
            result = await solve_image(image_bytes, mime, prompt)
            ci = int(result.get("correct_idx", -1))
            if 0 <= ci < len(opts):
                # Preserve original option text exactly as stored in the test.
                original_opts = q.get("options", [])
                questions[orig_idx]["correct"] = original_opts[ci]
                questions[orig_idx]["explanation"] = str(result.get("explanation", "") or "")
                questions[orig_idx]["_ai_solved"] = True
                questions[orig_idx]["_marked"] = True
                solved += 1
        except Exception as e:
            log.warning(f"Gemini Vision {orig_idx} xato: {e}")
            # One failed image must not stop the rest of the test.
            continue

    total_t = int(time.time() - t0)
    m3, s3 = divmod(total_t, 60)
    log.info(f"Gemini Vision: {solved}/{total}, {m3}:{s3:02d}")
    if msg:
        try:
            await msg.edit_text(
                f"✅ <b>Gemini Vision tugatdi!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🖼️ {solved}/{total} rasm yechildi\n"
                f"⏱ {m3}:{s3:02d}", parse_mode="HTML"
            )
        except Exception:
            pass
    return questions


async def _ai_solve(questions: list, msg, explain_mode: str = "full") -> list:
    """Matnli testlarni Groq bilan, Groq limitida Gemini bilan yechadi.

    - Groq: official ``groq`` AsyncGroq SDK, primary.
    - Gemini: official ``google-genai`` SDK, dedicated fallback.
    - Batch 5: input/output token sarfini nazorat qiladi.
    - Har bir javob indeks va mavjud variant bilan lokal validatsiya qilinadi.
    - API kalitlarini aylantirish quota'ni ko'paytirmaydi; bu faqat credential
      rotation. Groq org-level, Gemini project-level limitlarga ega.
    """
    import json, time
    from utils.ai_engine import solve_text_batch

    unmarked = [(i, q) for i, q in enumerate(questions) if not q.get("_marked")]
    total_q = len(unmarked)
    if not total_q:
        return questions

    batch_size = 5
    total_batches = (total_q + batch_size - 1) // batch_size
    solved = 0
    t0 = time.time()

    _exp_instr = {
        "full": "O'zbek tilida 2-3 jumla yozing: nega tanlangan javob to'g'ri.",
        "short": "O'zbek tilida 1 qisqa jumla yozing.",
        "none": "Bo'sh satr qaytaring.",
    }.get(explain_mode, "O'zbek tilida qisqa izoh yozing.")

    SYSTEM = (
        "Siz yuqori aniqlikdagi akademik test yechuvchisiz. "
        "Faqat berilgan savol va variantlardan foydalaning. Mavjud bo'lmagan fakt, "
        "variant yoki shartni to'qimang. Matematik/texnik masalani ichingizda "
        "qadam-baqadam tekshiring. Eng ishonchli javobni tanlang. "
        "Chiqishda FAQAT JSON array qaytaring. Har element: "
        '{"idx":N,"correct_idx":N,"explanation":"..."}. '
        "idx kiruvchi savolning indeksidir; correct_idx 0-based. "
        + _exp_instr
    )

    def _bar(done, total, w=10):
        f = int(w * done / max(total, 1))
        return "█" * f + "░" * (w - f)

    for bn, bs in enumerate(range(0, total_q, batch_size), 1):
        batch = unmarked[bs:bs + batch_size]
        q_data = [
            {
                "idx": oi,
                "q": q.get("question", ""),
                "opts": [re.sub(r"^[A-Ha-h]\s*[).]\s*", "", o) for o in q.get("options", [])],
            }
            for oi, q in batch
        ]
        user_prompt = (
            "Quyidagi savollarni mustaqil va ehtiyotkorlik bilan yeching. "
            "Har bir idx aynan kiruvchi savol indeksiga teng bo'lsin. "
            "correct_idx faqat berilgan opts ichidagi 0-based indeks bo'lsin.\n\n"
            + json.dumps(q_data, ensure_ascii=False, separators=(",", ":"))
        )

        if msg:
            try:
                elapsed = time.time() - t0
                eta = int(elapsed / max(bn - 1, 1) * (total_batches - bn + 1)) if bn > 1 else total_batches * 6
                m, sec = divmod(eta, 60)
                await msg.edit_text(
                    f"🤖 <b>AI yechmoqda...</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"[{_bar(bn-1, total_batches)}] {bn-1}/{total_batches} batch\n"
                    f"📊 {min((bn-1)*batch_size,total_q)}/{total_q} savol\n"
                    f"⏱ Qoldi: ~{m}:{sec:02d}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        try:
            parsed, provider = await solve_text_batch(SYSTEM, user_prompt)
            log.info(f"AI batch {bn}/{total_batches}: provider={provider}, results={len(parsed)}")
            for item in parsed:
                oi = int(item.get("idx", -1))
                ci = int(item.get("correct_idx", -1))
                if not (0 <= oi < len(questions)):
                    continue
                opts = questions[oi].get("options", [])
                if not (0 <= ci < len(opts)):
                    log.warning(f"AI invalid index: q={oi}, correct_idx={ci}, options={len(opts)}")
                    continue
                questions[oi]["correct"] = opts[ci]
                questions[oi]["explanation"] = str(item.get("explanation", "") or "")
                questions[oi]["_ai_solved"] = True
                solved += 1
        except Exception as e:
            log.error(f"AI batch {bn}/{total_batches} xato: {e}")

    total_t = int(time.time() - t0)
    m, sec = divmod(total_t, 60)
    log.info(f"AI yakunlandi: {solved}/{total_q} savol, {m}:{sec:02d}")
    if msg:
        try:
            await msg.edit_text(
                f"✅ <b>AI tugatdi!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 {solved}/{total_q} savol yechildi\n"
                f"⏱ {m}:{sec:02d}", parse_mode="HTML"
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
        "3️⃣ Rasmli savol bo'lsa — avval rasmni, keyin quiz'ni forward qiling\n"
        "4️⃣ Hammasi yuborilgach — <b>✅ Tayyor</b> bosing\n\n"
        "<i>💡 Faqat 'Viktorina' (Quiz) turi qabul qilinadi!</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    # Yo'riqnoma xabarini progress sifatida saqlash (birinchi poll kelganda o'chiriladi)
    uid = callback.from_user.id
    _poll_progress[uid] = callback.message.message_id
    _poll_count[uid] = 0
    _photo_registry.pop(uid, None)
    _photo_registry_lock.pop(uid, None)
    await state.set_state(CreateTest.waiting_polls)


@router.callback_query(F.data == "method_regular_poll", CreateTest.choose_method)
@router.callback_query(F.data == "method_regular_poll", CreateTest.choose_method)
async def method_regular_poll(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(questions=[], poll_time=30)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Tayyor", callback_data="finish_polls"))
    b.row(InlineKeyboardButton(text="❌ Bekor",  callback_data="cancel_create"))
    await callback.message.edit_text(
        "<b>📋 ANONIM VIKTORINA FORWARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Anonim viktorina (Poll) savollarini shu yerga\n"
        "   forward qiling — nechta bo'lsa ham\n"
        "2️⃣ Rasmli savol bo'lsa — avval rasmni, keyin\n"
        "   poll'ni forward qiling\n"
        "3️⃣ Hammasi yuborilgach — <b>✅ Tayyor</b> bosing\n\n"
        "<i>💡 To'g'ri javob Telegram tomonidan berilmagani\n"
        "uchun, tugagach barcha savollarni bittada\n"
        "seryalik yoki AI bilan belgilaysiz — xuddi fayldan\n"
        "yuklaganda bo'lgani kabi.</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup()
    )
    uid = callback.from_user.id
    _poll_progress[uid] = callback.message.message_id
    _poll_count[uid] = 0
    _photo_registry.pop(uid, None)
    _photo_registry_lock.pop(uid, None)
    await state.set_state(CreateTest.waiting_regular_polls)


@router.message(F.poll, CreateTest.waiting_regular_polls)
async def catch_regular_poll(message: Message, state: FSMContext):
    """
    Anonim viktorina (regular poll): Telegram to'g'ri javobni bermaydi,
    shuning uchun savol '_marked: False' bilan (belgilanmagan holda)
    to'g'ridan-to'g'ri questions ro'yxatiga qo'shiladi — hech qanday
    to'xtash yoki tugma yo'q. Nechta forward qilinsa ham (masalan 100 ta),
    catch_poll (Quiz)dagi bilan bir xil debounce (_flush_polls) orqali
    faqat bitta progress xabari ko'rsatiladi. "✅ Tayyor" bosilgach,
    barcha belgilanmagan savollar bittada seryalik/AI/admin/skip
    oqimiga tushadi (fayl yuklashdagi kabi).
    """
    import re as _re
    p = message.poll
    lts = ["A)", "B)", "C)", "D)", "E)", "F)"]
    opts = [f"{lts[i]} {op.text}" for i, op in enumerate(p.options)]
    clean_q = _re.sub(r"^\[\d+/\d+\]\s*", "", p.question).strip()
    uid = message.from_user.id

    await asyncio.sleep(0.12)  # rasm bilan bir xil pairing oynasi

    async with _get_poll_lock(uid):
        photo_id = None
        reg = _photo_registry.get(uid, {})
        candidates = [mid for mid in reg if mid < message.message_id]
        if candidates:
            photo_mid = min(candidates)
            fut = reg.pop(photo_mid)
            try:
                photo_id = await asyncio.wait_for(fut, timeout=25.0)
            except Exception as e:
                log.error("catch_regular_poll: photo pairing xato: %s", e)
                photo_id = None
            _cleanup_photo_registry(uid)

        d = await state.get_data()
        qs = list(d.get("questions", []))
        new_q = {
            "type": "multiple_choice",
            "question": clean_q,
            "options": opts,
            "correct": "",
            "explanation": "",
            "points": 1,
            "_marked": False,
        }
        if photo_id:
            new_q["photo"] = photo_id
            # E'TIBOR: _has_image qasddan qo'yilmagan. Bu maydon butun tizimda
            # "savol matni rasm ICHIDA, Vision bilan o'qish kerak" degani.
            # Bu yerda savol matni allaqachon Telegram poll'dan to'liq keladi —
            # rasm faqat QO'SHIMCHA. Shu sabab bu savol oddiy matnli
            # "belgilanmagan savol" sifatida ko'riladi (seryalik bilan
            # belgilanadi, yoki belgilanmasdan qoldirilib keyin web'da
            # qo'lda tahrirlanadi) — AI Vision yo'liga tushmaydi.

        qs.append(new_q)
        await state.update_data(questions=qs)
        count = len(qs)

    await _del(message.bot, message.chat.id, message.message_id)

    _poll_count[uid] = count
    old_task = _poll_debounce.pop(uid, None)
    if old_task:
        old_task.cancel()
    _poll_debounce[uid] = asyncio.create_task(
        _flush_polls(message.bot, message.chat.id, uid)
    )


# Kanalga rasm yuborishda ham flood control'ga uchramaslik uchun,
# _upload_images_to_channel bilan bir xil minimal oraliq va uid bo'yicha
# oxirgi yuborish vaqtini kuzatamiz (global — botning o'zi bitta chatga
# yuboradi, foydalanuvchidan qat'iy nazar).
_last_channel_send_ts = 0.0


@router.message(F.photo, StateFilter(CreateTest.waiting_polls, CreateTest.waiting_regular_polls))
async def catch_poll_photo(message: Message, state: FSMContext):
    """QuizBot forward rasmi: avval ro'yxatga olinadi, keyin storage kanalga yuklanadi.

    Pairing message_id tartibi bilan qilinadi. Shu sababli handlerlar parallel
    ishga tushgan taqdirda ham keyingi Quiz o'zidan oldingi eng eski, hali
    biriktirilmagan rasmni oladi. Storage kanalidan qaytgan YANGI file_idgina
    savolga yoziladi.
    """
    global _last_channel_send_ts
    from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError

    uid = message.from_user.id
    source_mid = message.message_id
    src_file_id = message.photo[-1].file_id

    # MUHIM: uploaddan oldin future yaratamiz. Poll handler shu future'ni ko'rib
    # upload tugashini kutishi mumkin.
    async with _get_photo_registry_lock(uid):
        fut = _register_photo(uid, source_mid)

    saved_file_id = None
    from config import STORAGE_CHANNEL_ID
    if not STORAGE_CHANNEL_ID:
        log.error("catch_poll_photo: STORAGE_CHANNEL_ID sozlanmagan")
    else:
        MIN_INTERVAL = 1.1
        MAX_ATTEMPTS = 8
        for attempt in range(1, MAX_ATTEMPTS + 1):
            async with _channel_upload_lock:
                elapsed = asyncio.get_running_loop().time() - _last_channel_send_ts
                if elapsed < MIN_INTERVAL:
                    await asyncio.sleep(MIN_INTERVAL - elapsed)
                try:
                    # Kanalga faqat rasm yuboriladi — caption yo'q.
                    copied = await message.bot.send_photo(
                        chat_id=STORAGE_CHANNEL_ID,
                        photo=src_file_id,
                        disable_notification=True,
                    )
                    _last_channel_send_ts = asyncio.get_running_loop().time()
                    if copied.photo:
                        saved_file_id = copied.photo[-1].file_id
                    break
                except TelegramRetryAfter as e:
                    _last_channel_send_ts = asyncio.get_running_loop().time()
                    log.warning("catch_poll_photo: flood control, %ss kutilmoqda", e.retry_after)
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramNetworkError as e:
                    log.warning("catch_poll_photo: tarmoq xatosi (%s/%s): %s", attempt, MAX_ATTEMPTS, e)
                    await asyncio.sleep(min(2 * attempt, 10))
                except Exception as e:
                    log.error("catch_poll_photo: kanalga yuklashda xato (%s): %s", type(e).__name__, e)
                    break

    # Future'ni aynan shu source message_id bilan yakunlaymiz.
    if not fut.done():
        fut.set_result(saved_file_id)

    if saved_file_id is None:
        log.error("catch_poll_photo: rasm saqlanmadi uid=%s mid=%s", uid, source_mid)
        await message.answer("⚠️ Rasmni storage kanaliga saqlab bo'lmadi. Savol rasm-siz qo'shiladi.")

    await _del(message.bot, message.chat.id, message.message_id)


@router.message(F.poll, CreateTest.waiting_polls)
async def catch_poll(message: Message, state: FSMContext):
    if message.poll.type != "quiz":
        await _del(message.bot, message.chat.id, message.message_id)
        return await message.answer("❌ Faqat <b>Viktorina (Quiz)</b> turi qabul qilinadi!")

    import re as _re
    p = message.poll
    lts = ["A)", "B)", "C)", "D)", "E)", "F)"]
    opts = [f"{lts[i]} {op.text}" for i, op in enumerate(p.options)]
    clean_q = _re.sub(r"^\[\d+/\d+\]\s*", "", p.question).strip()
    uid = message.from_user.id

    # Handlerlar parallel bo'lishi mumkin. Photo handler Future'ni birinchi
    # qadamdayoq yaratadi; biz esa juda qisqa scheduling oynasi berib, so'ng
    # message_id bo'yicha qat'iy FIFO pairing qilamiz.
    await asyncio.sleep(0.12)

    async with _get_poll_lock(uid):
        photo_id = None
        reg = _photo_registry.get(uid, {})

        # Poll'dan oldin kelgan, hali biriktirilmagan rasmlardan ENG ESKISI.
        candidates = [mid for mid in reg if mid < message.message_id]
        if candidates:
            photo_mid = min(candidates)
            fut = reg.pop(photo_mid)
            try:
                photo_id = await asyncio.wait_for(fut, timeout=25.0)
            except asyncio.TimeoutError:
                log.error("catch_poll: photo timeout uid=%s photo_mid=%s poll_mid=%s", uid, photo_mid, message.message_id)
                photo_id = None
            except Exception as e:
                log.error("catch_poll: photo future xatosi: %s", e)
                photo_id = None
            _cleanup_photo_registry(uid)

        d = await state.get_data()
        qs = list(d.get("questions", []))
        new_q = {
            "type": "multiple_choice",
            "question": clean_q,
            "options": opts,
            "correct": opts[p.correct_option_id],
            "explanation": p.explanation or "",
            "points": 1,
        }
        if photo_id:
            new_q["photo"] = photo_id

        qs.append(new_q)
        await state.update_data(questions=qs)
        count = len(qs)
        log.info("catch_poll: uid=%s poll_mid=%s paired_photo=%s total=%s",
                 uid, message.message_id, photo_id[:20] + "..." if photo_id else "YO'Q", count)

    await _del(message.bot, message.chat.id, message.message_id)

    _poll_count[uid] = count
    old_task = _poll_debounce.pop(uid, None)
    if old_task:
        old_task.cancel()
    _poll_debounce[uid] = asyncio.create_task(
        _flush_polls(message.bot, message.chat.id, uid)
    )


@router.callback_query(F.data == "finish_polls", StateFilter(CreateTest.waiting_polls, CreateTest.waiting_regular_polls))
async def finish_polls(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    d = await state.get_data()
    questions = d.get("questions", [])
    if not questions:
        return await callback.answer("❌ Hali savol yo'q!", show_alert=True)
    await callback.answer()

    unmarked = sum(1 for q in questions if not q.get("_marked", True))
    if unmarked > 0:
        # Belgilanmagan savollar bor — fayl oqimidagi kabi seryalik/AI/admin/skip
        # so'raladi. State'ni 'upload_file'ga o'tkazamiz, chunki uj_* handlerlar
        # shu holatga bog'langan — bir xil mexanizmni qayta ishlatamiz.
        await state.set_state(CreateTest.upload_file)
        total = len(questions)
        b = InlineKeyboardBuilder()
        b.button(text="🔡 Seryalik javob",    callback_data="uj_serial")
        b.button(text="🤖 AI bilan yechish",   callback_data="uj_ai")
        b.button(text="📨 Adminga murojaat",   callback_data="uj_admin")
        b.button(text="▶️ Shundayicha davom",  callback_data="uj_skip")
        b.adjust(1)
        img_count = sum(1 for q in questions if q.get("photo"))
        img_line = f"🖼 Rasmli: <b>{img_count}</b> ta (test bilan ulandi)\n" if img_count else ""
        await callback.message.edit_text(
            f"📋 <b>{total} TA SAVOL QABUL QILINDI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Belgilangan: <b>{total - unmarked}</b> ta\n"
            f"❓ Belgilanmagan: <b>{unmarked}</b> ta\n"
            + img_line +
            f"\n<i>To'g'ri javob aniqlanmagan. Nima qilamiz?</i>",
            parse_mode="HTML",
            reply_markup=b.as_markup()
        )
        return

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

    d = await state.get_data()
    if d.get("_multi_active"):
        await callback.message.edit_text(f"⏱ <b>Savol vaqti: {ptt}</b>")
        await _ask_multi_mode(callback.message, state)
        return

    await callback.message.edit_text(
        f"⏱ <b>Savol vaqti: {ptt}</b>\n\n"
        f"📁 Qaysi fanga tegishli?",
        reply_markup=subject_kb(extra_subjects=_get_user_subjects(callback.from_user.id))
    )
    await state.set_state(CreateTest.set_subject)


# ═══════════════════════════════════════════════════════════
# 4. FAN, MAVZU, SOZLAMALAR
# ═══════════════════════════════════════════════════════════

async def _ask_title(msg, state: FSMContext, category: str, file_name: str = ""):
    """Test nomini so'rash — qo'lda yoki fayl nomidan.
    Ko'p-fayl 'separate' rejimida title umuman so'ralmaydi — har fayl
    o'z nomi bilan saqlanadi, shuning uchun to'g'ridan-to'g'ri
    qiyinlik darajasiga o'tkaziladi."""
    d = await state.get_data()
    if d.get("_multi_active") and d.get("_multi_mode") == "separate":
        await state.update_data(category=category)
        await state.set_state(CreateTest.set_difficulty)
        text = (
            f"📁 Fan: <b>{category}</b>\n"
            f"<i>📂 Alohida testlar — har biri o'z fayl nomi bilan saqlanadi</i>\n\n"
            f"<b>📊 QIYINLIK DARAJASI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=difficulty_kb())
        except Exception:
            await msg.answer(text, parse_mode="HTML", reply_markup=difficulty_kb())
        return

    b = InlineKeyboardBuilder()
    if file_name:
        # Fayl nomidan tozalangan nom
        clean = file_name
        # Kengaytmani olib tashlaymiz
        for ext in ('.docx','.doc','.pdf','.txt','.xlsx','.xls'):
            clean = clean.replace(ext, '').replace(ext.upper(), '')
        # Maxsus belgilar va pastki chiziqlarni bo'sh joyga
        import re as _re
        clean = _re.sub(r'[_\-]+', ' ', clean).strip()
        clean = _re.sub(r'\s+', ' ', clean).strip()
        if clean:
            b.row(InlineKeyboardButton(
                text=f"📄 {clean[:40]}",
                callback_data="title_from_file"
            ))
    await state.update_data(category=category, _title_suggestion=file_name)
    await state.set_state(CreateTest.set_title)

    if hasattr(msg, 'edit_text'):
        try:
            await msg.edit_text(
                f"📁 Fan: <b>{category}</b>\n\n"
                f"<b>🏷 Test nomini yozing:</b>\n"
                f"<i>Yoki pastdagi tugma bilan fayl nomidan oling</i>",
                parse_mode="HTML",
                reply_markup=b.as_markup() if file_name else None
            )
            return
        except Exception:
            pass  # foydalanuvchi xabari edit qilinmaydi — pastda yangi xabar yuboramiz

    await msg.answer(
        f"📁 Fan: <b>{category}</b>\n\n"
        f"<b>🏷 Test nomini yozing:</b>\n"
        f"<i>Yoki pastdagi tugma bilan fayl nomidan oling</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup() if file_name else None
    )


@router.callback_query(F.data == "title_from_file", CreateTest.set_title)
async def title_from_file(callback: CallbackQuery, state: FSMContext):
    """Fayl nomidan test nomini olish"""
    await callback.answer()
    d = await state.get_data()
    file_name = d.get("_file_name", "")

    import re as _re
    clean = file_name
    for ext in ('.docx','.doc','.pdf','.txt','.xlsx','.xls'):
        clean = clean.replace(ext, '').replace(ext.upper(), '')
    clean = _re.sub(r'[_\-]+', ' ', clean).strip()
    clean = _re.sub(r'\s+', ' ', clean).strip()

    if not clean:
        return await callback.answer("Fayl nomi topilmadi", show_alert=True)

    await state.update_data(title=clean)
    await callback.message.edit_text(
        f"<b>📊 QIYINLIK DARAJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mavzu: <b>{clean}</b>",
        parse_mode="HTML",
        reply_markup=difficulty_kb()
    )
    await state.set_state(CreateTest.set_difficulty)



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
    d = await state.get_data()
    file_name = d.get("_file_name", "")
    await _ask_title(callback.message, state, s, file_name)


@router.message(F.text, CreateTest.set_subject)
async def subj_text(message: Message, state: FSMContext):
    subj = message.text.strip()
    await state.update_data(category=subj)
    await _del(message.bot, message.chat.id, message.message_id)
    # Maxsus fan nomini RAM ga saqlash
    from utils.ram_cache import add_user_custom_subject
    add_user_custom_subject(message.from_user.id, subj)
    d = await state.get_data()
    file_name = d.get("_file_name", "")
    await _ask_title(message, state, subj, file_name)


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


async def _save_one_test(callback: CallbackQuery, title: str, category: str,
                          difficulty: str, chosen_vis: str, time_limit, poll_time,
                          passing_score, max_attempts, questions: list,
                          source_hash="", source_name="", source_size=0,
                          send_summary=True):
    """
    Bitta test yaratadi: create_test() chaqiradi, natija xabarini
    (+ kalit, + baza e'loni) yuboradi. _do_save_test buni bir marta
    (oddiy/merged) yoki bir necha marta (separate) chaqiradi.
    Qaytaradi: tid (test_id)
    """
    uid = callback.from_user.id
    clean_qs = [{k: v for k, v in q.items() if not k.startswith("_")} for q in questions]
    td = {
        "title":         title or "Nomsiz",
        "category":      category or "Boshqa",
        "difficulty":    difficulty or "medium",
        "visibility":    chosen_vis,
        "time_limit":    time_limit or 0,
        "poll_time":     poll_time if poll_time is not None else 30,
        "passing_score": passing_score if passing_score is not None else 60,
        "max_attempts":  max_attempts or 0,
        "questions":     clean_qs,
        "_source_file_hash": source_hash,
        "_source_file_name": source_name,
        "_source_file_size": source_size,
    }
    tid = await create_test(
        uid, td,
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

    if send_summary:
        qs   = td["questions"]
        keys = (
            f"🔑 <b>JAVOBLAR KALITI</b> — <code>{tid}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        for i, q in enumerate(qs, 1):
            corr = q.get("correct", "?")
            keys += f"<b>{i}.</b> {corr}\n"

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
        if len(keys) <= 4000:
            await callback.message.answer(keys)
    else:
        # Ko'p-fayl 'separate' rejimida — qisqa bitta qatorli xabar
        await callback.message.answer(
            f"✅ <b>{td['title']}</b> — <code>{tid}</code> ({len(td['questions'])} ta savol)\n"
            f"🔗 <code>{link}</code>",
            parse_mode="HTML"
        )

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

    return tid


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
    common = dict(
        category=d.get("category", "Boshqa"), difficulty=d.get("difficulty", "medium"),
        chosen_vis=chosen_vis, time_limit=d.get("time_limit", 0),
        poll_time=d.get("poll_time", 30), passing_score=d.get("passing_score", 60),
        max_attempts=d.get("max_attempts", 0),
    )

    if d.get("_multi_active") and d.get("_multi_mode") == "separate":
        # ── N ta fayl → N ta alohida test, umumiy sozlamalar bilan ──
        done = d.get("_multi_done", [])
        await callback.message.edit_text(
            f"⏳ <b>{len(done)} ta test yaratilmoqda...</b>", parse_mode="HTML"
        )
        created = []
        for f in done:
            import re as _re
            title = f["file_name"]
            for ext in ('.docx', '.doc', '.pdf', '.txt', '.xlsx', '.xls'):
                title = title.replace(ext, '').replace(ext.upper(), '')
            title = _re.sub(r'[_\-]+', ' ', title).strip()
            title = _re.sub(r'\s+', ' ', title).strip() or "Nomsiz"
            tid = await _save_one_test(
                callback, title=title, questions=f["questions"],
                send_summary=False, **common,
            )
            created.append((title, tid, len(f["questions"])))

        await state.clear()
        summary = "\n".join(f"  • {t} — <code>{i}</code> ({n} ta savol)" for t, i, n in created)
        await callback.message.answer(
            f"🎉 <b>{len(created)} TA TEST YARATILDI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n{summary}",
            parse_mode="HTML"
        )
        return

    # ── Oddiy (bitta fayl) yoki 'merged' (birlashtirilgan) — bitta test ──
    raw_qs = d.get("questions", [])
    if d.get("_multi_active") and d.get("_multi_mode") == "merged":
        # _multi_done'da barcha N ta fayl (oxirgisi ham) allaqachon bor —
        # ularning savollarini bitta ro'yxatga birlashtiramiz
        done = d.get("_multi_done", [])
        raw_qs = []
        for f in done:
            raw_qs.extend(f["questions"])

    await _save_one_test(
        callback, title=d.get("title", "Nomsiz"), questions=raw_qs,
        source_hash=d.get("_source_file_hash", ""),
        source_name=d.get("_source_file_name", ""),
        source_size=d.get("_source_file_size", 0),
        send_summary=True, **common,
    )
    await state.clear()


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


# ═══════════════════════════════════════════════════════════
# AI BILAN QAYTA YECHISH (mavjud test uchun)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("reai_"))
async def reai_solve(cb: CallbackQuery, state: FSMContext):
    """Mavjud testning savollarini AI bilan qayta yechadi"""
    from utils.tg_db import get_test_full, save_test_full

    tid = cb.data[len("reai_"):]
    await cb.answer()

    test = await get_test_full(tid)
    if not test or not test.get("questions"):
        return await cb.message.answer("❌ Test topilmadi yoki bo'sh.")

    questions = test["questions"]
    total = len(questions)

    # Barcha savollarni AI ga beramiz (belgilangan-belgilanmaganidan qat'i nazar)
    msg = await cb.message.answer(
        f"🤖 <b>AI qayta yechmoqda...</b>\n"
        f"📊 Jami: {total} ta savol\n"
        f"<i>Iltimos kuting</i>",
        parse_mode="HTML"
    )

    # Rasmli va matnli ajratamiz
    img_qs = [q for q in questions if q.get("_has_image") or q.get("photo")]
    txt_qs = [q for q in questions if not (q.get("_has_image") or q.get("photo"))]

    solved = 0
    try:
        # Matnli savollar — Groq/Gemini/...
        if txt_qs:
            txt_qs = await _ai_solve(txt_qs, msg)
            solved += sum(1 for q in txt_qs if q.get("_ai_solved"))
        # Rasmli savollar — Gemini Vision (photo file_id orqali)
        # Eslatma: qayta yechishda rasm bytes yo'q, faqat file_id bor
        # Shuning uchun rasmli savollar o'tkazib yuboriladi (web edit orqali)
    except Exception as e:
        log.error(f"reai_solve xato: {e}")

    # Vaqtinchalik flaglarni tozalaymiz
    clean_qs = []
    for q in questions:
        cq = {k: v for k, v in q.items() if not k.startswith("_")}
        clean_qs.append(cq)
    test["questions"] = clean_qs

    # Saqlaymiz
    try:
        await save_test_full(test)
    except Exception as e:
        log.error(f"reai save xato: {e}")
        return await msg.edit_text("❌ Saqlashda xato yuz berdi.")

    try:
        await msg.edit_text(
            f"✅ <b>AI qayta yechdi!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Jami: <b>{total}</b> ta savol\n"
            f"✅ Yechildi: <b>{solved}</b> ta\n"
            + (f"🖼 Rasmli {len(img_qs)} ta — web orqali tahrirlang\n" if img_qs else "")
            + f"\n<i>Test yangilandi.</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# YANGI FAYL YUKLASH (eski test o'rniga)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("reupload_"))
async def reupload_start(cb: CallbackQuery, state: FSMContext):
    """Eski test savollarini yangi fayl bilan almashtirish"""
    tid = cb.data[len("reupload_"):]
    await cb.answer()

    await state.update_data(_reupload_tid=tid)
    await state.set_state(CreateTest.reupload_file)
    await cb.message.answer(
        f"📄 <b>Yangi fayl yuboring</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Eski savollar <b>o'chiriladi</b>, yangi fayldagi savollar yuklanadi.\n"
        f"Test nomi va sozlamalari <b>o'zgarmaydi</b>.\n\n"
        f"<i>Bekor qilish uchun /start</i>",
        parse_mode="HTML"
    )


@router.message(F.document, CreateTest.reupload_file)
async def reupload_file(message: Message, state: FSMContext):
    """Yangi fayl — eski test savollarini almashtiradi"""
    import tempfile, os
    from utils.tg_db import get_test_full, save_test_full

    d   = await state.get_data()
    tid = d.get("_reupload_tid", "")
    if not tid:
        await state.clear()
        return await message.answer("❌ Test ID topilmadi. /start bilan qayta urinib ko'ring.")

    doc = message.document
    status = await message.answer("⏳ Fayl yuklanmoqda...")

    try:
        file = await message.bot.get_file(doc.file_id)
        ext  = os.path.splitext(doc.file_name or "")[1].lower() or ".docx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
        await message.bot.download_file(file.file_path, tmp_path)

        questions = parse_file(tmp_path)

        # Rasmlarni TG kanalga yuklaymiz
        img_count = sum(1 for q in questions if q.get("_img_bytes"))
        img_upload_summary = ""
        if img_count > 0:
            await status.edit_text(f"🖼 {img_count} ta rasm yuklanmoqda...")
            questions, up_ok, up_fail, up_total = await _upload_images_to_channel(message.bot, questions)
            if up_fail > 0:
                img_upload_summary = (
                    f"🖼 Rasmlar: <b>{up_ok}/{up_total}</b> muvaffaqiyatli, "
                    f"<b>{up_fail}</b> ta xato bo'ldi\n"
                )

        try: os.remove(tmp_path)
        except Exception: pass

        if not questions:
            await state.clear()
            return await status.edit_text("❌ Faylda savol topilmadi.")

        # Eski testni olamiz, savollarni almashtiramiz
        test = await get_test_full(tid)
        if not test:
            await state.clear()
            return await status.edit_text("❌ Eski test topilmadi.")

        # Vaqtinchalik flaglarni tozalaymiz (photo qoladi)
        clean_qs = []
        for q in questions:
            cq = {k: v for k, v in q.items() if not k.startswith("_")}
            clean_qs.append(cq)

        test["questions"] = clean_qs
        await save_test_full(test)
        await state.clear()

        total  = len(clean_qs)
        marked = sum(1 for q in questions if q.get("_marked"))
        await status.edit_text(
            f"✅ <b>Test yangilandi!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Yangi savollar: <b>{total}</b> ta\n"
            f"✅ Belgilangan: <b>{marked}</b> ta\n"
            + (f"🖼 Rasmli: <b>{img_count}</b> ta\n" if img_count else "")
            + img_upload_summary
            + f"\n<i>Test nomi va sozlamalari saqlanди.</i>",
            parse_mode="HTML"
        )

    except Exception as e:
        log.error(f"reupload_file xato: {e}")
        await state.clear()
        try:
            await status.edit_text(f"❌ Xato: {str(e)[:100]}")
        except Exception:
            pass
