"""
🔗 TEST REFERAL TIZIMI
========================
Muayyan testni yechish uchun referal talab qilish.

Mantiq:
  - Har bir test uchun alohida referal_required va referal_count
  - Faqat bot private chat va web testda tekshiriladi
  - Guruhda tekshirilmaydi
  - Admin va test yaratuvchisi tekshirilmaydi
  - Foydalanuvchi yetarli referal chaqirgan bo'lsa — o'tadi

Referal hisobi:
  - Har user ning umumiy referral_count (mavjud tizim)
  - Testga kirish uchun zarur son: test.ref_count
"""
import logging
from typing import Optional

log = logging.getLogger(__name__)

# RAM da test kirish ruxsatlari keshi
# {uid: {tid: True}} — bu user bu testga ruxsat berilgan
_access_cache: dict = {}


def has_test_access(uid: int, tid: str) -> bool:
    """Foydalanuvchi bu test uchun referal shartini bajarishdimi?"""
    return _access_cache.get(uid, {}).get(tid, False)


def grant_test_access(uid: int, tid: str):
    """Ruxsat berish (referal sharti bajarildi)"""
    if uid not in _access_cache:
        _access_cache[uid] = {}
    _access_cache[uid][tid] = True


def get_user_referral_count(uid: int) -> int:
    """Foydalanuvchining umumiy referal soni"""
    try:
        from utils import ram_cache as ram
        user = ram.get_user(uid) or {}
        return int(user.get("referral_count", 0))
    except Exception:
        return 0


async def check_test_referral(
    bot,
    uid: int,
    tid: str,
    test_meta: dict,
    bot_username: str = "",
) -> dict:
    """
    Test uchun referal shartini tekshirish.
    
    Qaytaradi:
        {"ok": True}  — kirish ruxsat
        {"ok": False, "need": 3, "have": 1, "ref_link": "..."}  — yetarli emas
    """
    # Referal talab qilinmasa
    ref_required = test_meta.get("ref_required", False)
    ref_count    = int(test_meta.get("ref_count", 0))
    
    if not ref_required or ref_count <= 0:
        return {"ok": True}

    # Admin va yaratuvchi tekshirilmaydi
    creator_id = int(test_meta.get("creator_id", 0))
    if uid == creator_id:
        return {"ok": True}
    
    try:
        from config import ADMIN_IDS
        if uid in ADMIN_IDS:
            return {"ok": True}
    except Exception:
        pass

    # RAM keshda ruxsat bormi?
    if has_test_access(uid, tid):
        return {"ok": True}

    # Referal sonini tekshirish
    user_refs = get_user_referral_count(uid)
    
    if user_refs >= ref_count:
        grant_test_access(uid, tid)
        return {"ok": True}

    # Yetarli emas
    from utils.roles import get_referral_code
    ref_code = get_referral_code(uid)
    ref_link = f"https://t.me/{bot_username}?start={ref_code}" if bot_username else ""

    return {
        "ok":       False,
        "need":     ref_count,
        "have":     user_refs,
        "ref_link": ref_link,
        "short":    ref_count - user_refs,  # nechta yetishmaydi
    }


async def send_referral_required_msg(event, result: dict, test_title: str, bot_username: str):
    """
    Referal talab xabari yuborish
    """
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton, Message, CallbackQuery

    need  = result["need"]
    have  = result["have"]
    short = result["short"]
    link  = result["ref_link"]

    text = (
        f"🔒 <b>Bu test uchun referal talab qilinadi</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 Test: <b>{test_title}</b>\n\n"
        f"📊 Sizda: <b>{have} ta</b> referal\n"
        f"🎯 Kerak: <b>{need} ta</b> referal\n"
        f"⚡️ Yetishmaydi: <b>{short} ta</b>\n\n"
        f"👇 Havolangizni do'stlaringizga yuboring:"
    )

    b = InlineKeyboardBuilder()
    if link:
        b.row(InlineKeyboardButton(
            text="🔗 Mening referal havolam",
            url=f"https://t.me/share/url?url={link}&text=Bu+testni+yechish+uchun+botga+qo%27shiling!"
        ))
        b.row(InlineKeyboardButton(
            text="📋 Havolani nusxalash",
            callback_data="copy_ref_link"
        ))
    b.row(InlineKeyboardButton(
        text="🔄 Tekshirish",
        callback_data=f"ref_check_{event._tid if hasattr(event, '_tid') else ''}"
    ))

    if isinstance(event, Message):
        await event.answer(text, reply_markup=b.as_markup())
    elif isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=b.as_markup())
        await event.answer("🔒 Referal talab qilinadi", show_alert=True)
