"""
photo_upload.py — Rasmli savollar uchun yordamchi handler

Foydalanish:
  1. Botga SHAXSIY xabarda /photo_upload yuboring
  2. Keyin rasm yuboring — bot file_id qaytaradi
  3. Shu file_id ni TXT testga qo'shing:
     [rasm: AgACAgI...]
     Savol matni...
     *A) To'g'ri javob

main.py ga qo'shing:
  from handlers.photo_upload import router as photo_router
  dp.include_router(photo_router)
"""

import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

log    = logging.getLogger(__name__)
router = Router()

# Faqat /photo_upload buyrug'ini bergan foydalanuvchilar user_id lari
_waiting_photo: set[int] = set()


@router.message(Command("photo_upload"))
async def cmd_upload_photo(message: Message):
    """Rasm yuklash yo'riqnomasi — faqat shaxsiy chatda."""

    # Faqat private chat (shaxsiy suhbat) da ishlaydi
    if message.chat.type != "private":
        return  # Guruh/kanal — e'tiborsiz qoldirish

    user_id = message.from_user.id
    _waiting_photo.add(user_id)

    await message.answer(
        "📸 <b>Rasm yuklash</b>\n\n"
        "Menga rasm yuboring — men uning <code>file_id</code> sini qaytaraman.\n\n"
        "So'ng shu <code>file_id</code> ni TXT testga qo'shing:\n"
        "<pre>[rasm: file_id_bu_yerga]\n"
        "Savol matni...\n"
        "*A) To'g'ri javob\n"
        "B) Variant\n"
        "C) Variant\n"
        "D) Variant</pre>",
        parse_mode="HTML",
        protect_content=True,
    )


@router.message(lambda m: m.photo is not None)
async def handle_photo(message: Message):
    """Rasm qabul qilish — faqat private chat + /photo_upload kutayotgan foydalanuvchi."""

    # Faqat private chat
    if message.chat.type != "private":
        return

    user_id = message.from_user.id

    # Faqat /photo_upload buyrug'ini bergan foydalanuvchi
    if user_id not in _waiting_photo:
        return

    photo   = message.photo[-1]  # Eng yuqori sifatli rasm
    file_id = photo.file_id

    # Ro'yxatdan o'chirish (bir martalik)
    _waiting_photo.discard(user_id)

    await message.answer(
        f"✅ <b>Rasm qabul qilindi!</b>\n\n"
        f"Quyidagi qatorni ko'chiring va savol oldiga qo'ying:\n\n"
        f"<code>[rasm: {file_id}]</code>",
        parse_mode="HTML",
        protect_content=False,
    )
    log.info(f"Rasm yuklandi (user={user_id}): {file_id[:30]}...")


@router.message(lambda m: m.document is not None and
                m.document.mime_type and
                m.document.mime_type.startswith("image/"))
async def handle_photo_doc(message: Message):
    """Fayl sifatida yuborilgan rasm — faqat private chat + /photo_upload kutayotgan foydalanuvchi."""

    # Faqat private chat
    if message.chat.type != "private":
        return

    user_id = message.from_user.id

    # Faqat /photo_upload buyrug'ini bergan foydalanuvchi
    if user_id not in _waiting_photo:
        return

    file_id = message.document.file_id

    # Ro'yxatdan o'chirish (bir martalik)
    _waiting_photo.discard(user_id)

    await message.answer(
        f"✅ <b>Rasm (fayl) qabul qilindi!</b>\n\n"
        f"<code>[rasm: {file_id}]</code>",
        parse_mode="HTML",
    )
    log.info(f"Rasm (doc) yuklandi (user={user_id}): {file_id[:30]}...")
