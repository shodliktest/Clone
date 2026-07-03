"""
🔒 FORCE JOIN — Majburiy obuna moduli
======================================
Admin panel orqali boshqariladi:
  - Kanal/guruh qo'shish va o'chirish
  - Tekshirishni yoqish/o'chirish
  - Har bir user /start bosganda tekshiriladi
  - Supabase (app_settings jadvali) da saqlanadi — bot qayta ishga
    tushsa yoki qulasa ham, sozlamalar YO'QOLMAYDI.
"""
import logging
import asyncio
from typing import Optional
from aiogram.types import Message, CallbackQuery

log = logging.getLogger(__name__)

# ── RAM da tezkor cache (har so'rovda Supabase'ga bormaslik uchun) ──
_force_channels: list = []   # [{"id": -100xxx, "title": "...", "invite": "...", "type": "channel"}]
_force_enabled:  bool = False

def get_force_channels() -> list:
    return list(_force_channels)

def is_force_enabled() -> bool:
    return _force_enabled

def set_force_enabled(val: bool):
    global _force_enabled
    _force_enabled = val
    _save()

def add_channel(ch_id: int, title: str, invite: str = "", ch_type: str = "channel") -> bool:
    """Kanal/guruh ro'yxatga qo'shish"""
    for ch in _force_channels:
        if ch["id"] == ch_id:
            return False  # allaqachon bor
    _force_channels.append({
        "id":     ch_id,
        "title":  title,
        "invite": invite,
        "type":   ch_type,   # channel | group
    })
    _save()
    return True

def remove_channel(ch_id: int) -> bool:
    """Ro'yxatdan o'chirish"""
    global _force_channels
    before = len(_force_channels)
    _force_channels = [c for c in _force_channels if c["id"] != ch_id]
    if len(_force_channels) < before:
        _save()
        return True
    return False

# ── Supabase'ga saqlash (bot restart/crash bo'lsa ham yo'qolmasin) ──
def _save():
    """
    RAM'ni darhol yangilaydi va Supabase'ga background'da yozadi.
    Sinxron funksiya bo'lgani uchun (chaqiruvchilar await qilmaydi),
    yozuv fire-and-forget task orqali amalga oshadi — lekin
    milliseкundlar ichida boshlanadi, foydalanuvchi kutmaydi.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_save_async())
        else:
            log.warning("force_join _save: event loop ishlamayapti, saqlanmadi")
    except RuntimeError:
        log.warning("force_join _save: event loop topilmadi")
    except Exception as e:
        log.warning(f"force_join save: {e}")

async def _save_async():
    """app_settings jadvalidagi 'force_join' kalitiga yozadi."""
    try:
        from utils import tg_db
        if not tg_db.ready():
            return
        current = await tg_db.get_settings_tg()
        current["force_join"] = {
            "channels": _force_channels,
            "enabled":  _force_enabled,
        }
        await tg_db.save_settings(current)
    except Exception as e:
        log.warning(f"force_join _save_async: {e}")

def load_from_cache():
    """
    Bot start da RAM cache'dan yuklash (agar shu jarayon ichida
    allaqachon yuklangan bo'lsa — masalan ikkinchi marta chaqirilganda).
    Haqiqiy manba — Supabase, uni load_from_db() orqali yuklang.
    """
    global _force_channels, _force_enabled
    try:
        from utils import ram_cache as ram
        chs = ram._get("force_join_channels")
        if chs: _force_channels = chs
        en = ram._get("force_join_enabled")
        if en is not None: _force_enabled = bool(en)
        log.info(f"Force join (RAM cache): {len(_force_channels)} kanal, enabled={_force_enabled}")
    except Exception as e:
        log.warning(f"force_join load (RAM): {e}")

async def load_from_db():
    """
    Bot start da Supabase'dan haqiqiy yuklash — bot necha marta
    o'chib-yonsa ham, majburiy obuna sozlamalari saqlanib qoladi.
    bot.py da tg_db.init() dan KEYIN chaqirilishi kerak.
    """
    global _force_channels, _force_enabled
    try:
        from utils import tg_db
        if not tg_db.ready():
            log.warning("force_join load_from_db: Supabase hali tayyor emas")
            return
        settings = await tg_db.get_settings_tg()
        fj = settings.get("force_join") or {}
        _force_channels = fj.get("channels", [])
        _force_enabled  = bool(fj.get("enabled", False))
        # RAM cache'ga ham yozib qo'yamiz (moslik uchun)
        from utils import ram_cache as ram
        ram._set("force_join_channels", list(_force_channels))
        ram._set("force_join_enabled",  _force_enabled)
        log.info(f"Force join (Supabase'dan): {len(_force_channels)} kanal, enabled={_force_enabled}")
    except Exception as e:
        log.warning(f"force_join load_from_db: {e}")

# ── Asosiy tekshiruv ────────────────────────────────────────
async def check_user_joined(bot, user_id: int) -> list:
    """
    Foydalanuvchi barcha majburiy kanallarga a'zo ekanligini tekshirish.
    Qaytaradi: a'zo bo'lmagan kanallar ro'yxati (bo'sh = hammaga a'zo)
    """
    if not _force_enabled or not _force_channels:
        return []
    not_joined = []
    for ch in _force_channels:
        try:
            member = await bot.get_chat_member(
                chat_id=ch["id"], user_id=user_id
            )
            status = member.status
            if status in ("left", "kicked", "banned"):
                not_joined.append(ch)
        except Exception as e:
            log.warning(f"get_chat_member {ch['id']}: {e}")
            # Tekshira olmadik - o'tkazib yuboramiz
    return not_joined

async def send_join_request(event, not_joined: list, bot):
    """
    A'zo bo'lmagan kanallarga havola yuborish.
    Guruhda bo'lsa — faqat PM ga yuboriladi.
    """
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton, Message, CallbackQuery

    b = InlineKeyboardBuilder()
    # Tugmalar - har kanal uchun
    for ch in not_joined:
        invite = ch.get("invite") or ""
        icon   = "📢" if ch.get("type") == "channel" else "👥"
        title  = ch['title'][:25] + "..." if len(ch['title']) > 25 else ch['title']
        if invite:
            b.row(InlineKeyboardButton(
                text=f"{icon} {title}",
                url=invite
            ))
    b.row(InlineKeyboardButton(
        text="✅ A'zo bo'ldim — Tekshirish",
        callback_data="fj_check"
    ))
    # Qisqa matn - 4096 limitdan xavfsiz
    count = len(not_joined)
    def _e(s):  # HTML-escape (kanal nomida "<" bo'lsa xato bermasin)
        return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    names = ", ".join(
        _e((ch['title'][:20] + "...") if len(ch['title']) > 20 else ch['title'])
        for ch in not_joined[:3]
    )
    if count > 3: names += f" va yana {count-3} ta"
    text = (
        f"🔒 <b>Majburiy obuna</b>\n\n"
        f"Botdan foydalanish uchun quyidagi "
        f"{'kanallarga' if count > 1 else 'kanalga'} a'zo bo'ling:\n"
        f"<b>{names}</b>\n\n"
        f"👇 Tugmalarni bosib a'zo bo'ling:"
    )
    # Telegram 4096 limitidan qat'iy himoya (kanal soni ko'p bo'lsa ham)
    if len(text) > 4000:
        text = text[:3990] + "\n…"

    # Faqat private chatda yuboriladi (middleware guruhni bloklaydi)
    try:
        markup = b.as_markup()
        if isinstance(event, Message):
            await event.answer(text, reply_markup=markup)
        elif isinstance(event, CallbackQuery):
            if event.message:
                await event.message.answer(text, reply_markup=markup)
            elif event.from_user:
                await bot.send_message(event.from_user.id, text, reply_markup=markup)
    except Exception as e:
        log.warning(f"send_join_request: {e}")

async def handle_fj_check(callback: CallbackQuery):
    """'A'zo bo'ldim' tugmasi bosilganda qayta tekshirish"""
    uid       = callback.from_user.id
    not_joined = await check_user_joined(callback.bot, uid)
    if not not_joined:
        await callback.answer("✅ Rahmat! Endi davom etishingiz mumkin.", show_alert=True)
        # /start ni qayta ishlatish
        from aiogram.fsm.context import FSMContext
        try:
            await callback.message.delete()
        except Exception:
            pass
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.bot.send_message(
            callback.from_user.id,
            "✅ <b>A'zolik tasdiqlandi!</b>\n\n"
            "Endi botdan foydalanishingiz mumkin.\n"
            "👇 /start bosing."
        )
    else:
        await callback.answer(
            "❌ Hali ba'zi kanallarga a'zo emassiz!", show_alert=True
        )
        await send_join_request(callback, not_joined, callback.bot)
