"""
🔗 TEST REFERAL TIZIMI
========================
Muayyan testni yechish uchun referal talab qilish.
- Guruhda tekshirilmaydi
- Admin va test yaratuvchisi tekshirilmaydi
- RAM cache da ruxsatlar saqlanadi
"""
import logging
from typing import Optional

log = logging.getLogger(__name__)

# RAM kesh: {uid: {tid: True}}
_access_cache: dict = {}


def has_test_access(uid: int, tid: str) -> bool:
    return _access_cache.get(uid, {}).get(tid, False)


def grant_test_access(uid: int, tid: str):
    if uid not in _access_cache:
        _access_cache[uid] = {}
    _access_cache[uid][tid] = True


def get_user_referral_count(uid: int) -> int:
    try:
        from utils import ram_cache as ram
        user = ram.get_user(uid) or {}
        return int(user.get("referral_count", 0))
    except Exception:
        return 0


async def check_test_referral(
    bot, uid: int, tid: str,
    test_meta: dict, bot_username: str = ""
) -> dict:
    """
    Tekshirish natijasi:
      {"ok": True}
      {"ok": False, "need": 3, "have": 1, "short": 2, "ref_link": "..."}
    """
    ref_required = test_meta.get("ref_required", False)
    ref_count    = int(test_meta.get("ref_count", 0))

    if not ref_required or ref_count <= 0:
        return {"ok": True}

    # Yaratuvchi tekshirilmaydi
    creator_id = int(test_meta.get("creator_id", 0))
    if uid == creator_id:
        return {"ok": True}

    # Admin tekshirilmaydi
    try:
        from config import ADMIN_IDS
        if uid in ADMIN_IDS:
            return {"ok": True}
    except Exception:
        pass

    # Cache da ruxsat bormi?
    if has_test_access(uid, tid):
        return {"ok": True}

    # Referral soni tekshirish
    user_refs = get_user_referral_count(uid)
    if user_refs >= ref_count:
        grant_test_access(uid, tid)
        return {"ok": True}

    # Referal havola
    try:
        from utils.roles import get_referral_code
        ref_code = get_referral_code(uid)
        ref_link = (f"https://t.me/{bot_username}?start={ref_code}"
                    if bot_username else "")
    except Exception:
        ref_link = ""

    return {
        "ok":       False,
        "need":     ref_count,
        "have":     user_refs,
        "short":    ref_count - user_refs,
        "ref_link": ref_link,
    }


async def send_referral_required_msg(
    event, result: dict, test_title: str,
    bot_username: str, tid: str = ""
):
    """Referal talab xabari yuborish"""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton, Message, CallbackQuery

    need  = result["need"]
    have  = result["have"]
    short = result["short"]
    link  = result["ref_link"]

    text = (
        f"🔒 <b>Bu test uchun referal talab qilinadi</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>{test_title}</b>\n\n"
        f"📊 Sizda: <b>{have} ta</b> referal\n"
        f"🎯 Kerak: <b>{need} ta</b> referal\n"
        f"⚡ Yetishmaydi: <b>{short} ta</b>\n\n"
        f"👇 Havolangizni do\'stlaringizga yuboring:"
    )

    b = InlineKeyboardBuilder()
    if link:
        share = (f"https://t.me/share/url?url={link}"
                 f"&text=Bu+testni+yechish+uchun+botga+qo%27shiling!")
        b.row(InlineKeyboardButton(
            text="🔗 Mening referal havolam",
            url=share
        ))
    if tid:
        b.row(InlineKeyboardButton(
            text="🔄 Qayta tekshirish",
            callback_data=f"ref_recheck_{tid}"
        ))

    try:
        if isinstance(event, Message):
            await event.answer(text, reply_markup=b.as_markup())
        elif isinstance(event, CallbackQuery):
            await event.message.answer(text, reply_markup=b.as_markup())
            await event.answer("🔒 Referal talab qilinadi", show_alert=True)
    except Exception as e:
        log.warning(f"send_referral_required_msg: {e}")


async def handle_ref_recheck(callback, tid: str, bot_username: str):
    """Foydalanuvchi 'Qayta tekshirish' bosdi"""
    uid  = callback.from_user.id
    try:
        from utils.ram_cache import get_test_meta_any
        meta = get_test_meta_any(tid) or {}
    except Exception:
        meta = {}

    result = await check_test_referral(callback.bot, uid, tid, meta, bot_username)
    if result["ok"]:
        grant_test_access(uid, tid)
        await callback.answer("✅ Referal sharti bajarildi!", show_alert=True)
        # Test havolasini yuborish
        try:
            from handlers.webauth import WEBAPP_URL
            import urllib.parse
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            from aiogram.types import InlineKeyboardButton
            u      = callback.from_user
            params = urllib.parse.urlencode({
                "id": tid, "uid": uid,
                "name": u.full_name or str(uid),
                "uname": u.username or "", "auto": "1"
            })
            web_url = f"{WEBAPP_URL}/web_test.html?{params}"
            bld = InlineKeyboardBuilder()
            bld.row(InlineKeyboardButton(text="🌐 Testni boshlash", url=web_url))
            bld.row(InlineKeyboardButton(
                text="📊 Quiz Poll",
                callback_data=f"start_poll_{tid}"
            ))
            await callback.message.answer(
                f"✅ <b>Referal sharti bajarildi!</b>\n"
                f"Endi testni boshlashingiz mumkin:",
                reply_markup=bld.as_markup()
            )
        except Exception as e:
            log.warning(f"ref_recheck web url: {e}")
    else:
        await callback.answer(
            f"❌ Hali {result['short']} ta referal yetishmaydi!",
            show_alert=True
        )
        title = meta.get("title", tid)
        await send_referral_required_msg(
            callback, result, title, bot_username, tid
        )
