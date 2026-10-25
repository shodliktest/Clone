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

# ══════════════════════════════════════════════════════════════
# SAQLASH — `await` + qayta o'qib TEKSHIRISH bilan
# ──────────────────────────────────────────────────────────────
# Sozlama ikki joyga yoziladi:
#   1) force_join_config (id=1)   — asosiy, faqat shu modul yozadi
#   2) app_settings.data.force_join — zaxira/moslik (tungi flush ustidan
#      yozmasligi uchun tg_db.save_settings uni DOIM bazadagisi bilan saqlaydi)
# Admin o'zgartirish kiritganda natija TASDIQLANGANDAN KEYINGINA "bajarildi"
# deb ko'rsatiladi; yozilmasa RAM o'zgarishi orqaga qaytariladi (ekran va baza
# hech qachon ikki xil bo'lib qolmaydi).
# ══════════════════════════════════════════════════════════════
import time as _time

_persist_ok: bool = True          # oxirgi saqlash muvaffaqiyatli bo'ldimi
_persist_err: str = ""
_persist_where: str = ""
_loaded_ok: bool = False
_save_lock = None
_chan_last_error: dict = {}       # kanal id -> oxirgi tekshiruv xatosi (admin panelda ko'rsatiladi)


def _lock():
    global _save_lock
    if _save_lock is None:
        _save_lock = asyncio.Lock()
    return _save_lock


def persist_status() -> tuple:
    """(ok, xato_matni) — admin panelda ko'rsatish uchun."""
    return _persist_ok, _persist_err


def channel_errors() -> dict:
    return dict(_chan_last_error)


def _fj_equal(enabled, channels) -> bool:
    return (bool(enabled) == bool(_force_enabled)
            and [c.get("id") for c in (channels or [])] == [c["id"] for c in _force_channels])


async def _write_all() -> tuple:
    """Hozirgi RAM holatini bazaga yozadi va QAYTA O'QIB tekshiradi → (ok, xato, qaerga)."""
    from utils import tg_db, supabase_client as sb
    if not tg_db.ready():
        return False, "Supabase tayyor emas", ""
    channels = [dict(c) for c in _force_channels]
    enabled  = bool(_force_enabled)
    wrote, errs = [], []

    # 1) asosiy jadval
    try:
        await sb.upsert("force_join_config",
                        {"id": 1, "enabled": enabled, "channels": channels}, on_conflict="id")
        row = await sb.select_one("force_join_config", "id", 1)
        if row and _fj_equal(row.get("enabled"), row.get("channels")):
            wrote.append("force_join_config")
        else:
            errs.append("force_join_config: yozildi, lekin qayta o'qishda mos kelmadi")
    except Exception as e:
        errs.append(f"force_join_config: {e}")

    # 2) app_settings ichidagi nusxa (to'g'ridan-to'g'ri birlashtirib yozamiz)
    try:
        row  = await sb.select_one("app_settings", "id", 1)
        data = dict((row or {}).get("data") or {})
        data["force_join"] = {"channels": channels, "enabled": enabled}
        await sb.upsert("app_settings", {"id": 1, "data": data}, on_conflict="id")
        row2 = await sb.select_one("app_settings", "id", 1)
        fj   = ((row2 or {}).get("data") or {}).get("force_join") or {}
        if _fj_equal(fj.get("enabled"), fj.get("channels")):
            wrote.append("app_settings")
        else:
            errs.append("app_settings: qayta o'qishda mos kelmadi")
    except Exception as e:
        errs.append(f"app_settings: {e}")

    return bool(wrote), " | ".join(errs), "+".join(wrote)


async def _persist_locked() -> tuple:
    global _persist_ok, _persist_err, _persist_where
    ok, err, where = False, "", ""
    for attempt in range(3):
        ok, err, where = await _write_all()
        if ok:
            break
        log.error("force_join saqlash xato (urinish %d/3): %s", attempt + 1, err)
        await asyncio.sleep(1.2 * (attempt + 1))
    _persist_ok, _persist_err, _persist_where = ok, ("" if ok else err[:200]), where
    if ok:
        log.info("force_join SAQLANDI [%s]: %d kanal, enabled=%s",
                 where, len(_force_channels), _force_enabled)
        if err:
            log.warning("force_join: ba'zi joyga yozilmadi: %s", err)
    return ok, err


async def persist() -> tuple:
    async with _lock():
        return await _persist_locked()


# ── ADMIN uchun: o'zgartiradi → bazaga yozadi → tasdiqlaydi (yozilmasa orqaga qaytaradi) ──
async def set_enabled_async(val: bool) -> tuple:
    global _force_enabled
    async with _lock():
        prev = _force_enabled
        _force_enabled = bool(val)
        ok, err = await _persist_locked()
        if not ok:
            _force_enabled = prev
        return ok, err


async def add_channel_async(ch_id: int, title: str, invite: str = "", ch_type: str = "channel") -> tuple:
    """→ ("added"|"exists"|"failed", xato)"""
    global _force_channels
    async with _lock():
        if any(c["id"] == ch_id for c in _force_channels):
            return "exists", ""
        prev = list(_force_channels)
        _force_channels = prev + [{"id": ch_id, "title": title, "invite": invite, "type": ch_type}]
        ok, err = await _persist_locked()
        if not ok:
            _force_channels = prev
            return "failed", err
        invalidate_member_cache()
        return "added", ""


async def remove_channel_async(ch_id: int) -> tuple:
    """→ ("removed"|"missing"|"failed", xato)"""
    global _force_channels
    async with _lock():
        prev = list(_force_channels)
        if not any(c["id"] == ch_id for c in prev):
            return "missing", ""
        _force_channels = [c for c in prev if c["id"] != ch_id]
        ok, err = await _persist_locked()
        if not ok:
            _force_channels = prev
            return "failed", err
        invalidate_member_cache()
        return "removed", ""


def _save():
    """Eski sinxron API uchun (moslik). Yangi kod *_async funksiyalardan foydalansin."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("force_join _save: ishlayotgan event loop yo'q, saqlanmadi")
        return
    loop.create_task(persist())


def load_from_cache():
    """RAM cache'dan (agar shu jarayonda allaqachon yuklangan bo'lsa)."""
    global _force_channels, _force_enabled
    try:
        from utils import ram_cache as ram
        chs = ram._get("force_join_channels")
        if chs: _force_channels = chs
        en = ram._get("force_join_enabled")
        if en is not None: _force_enabled = bool(en)
    except Exception as e:
        log.warning(f"force_join load (RAM): {e}")


async def load_from_db(_retries: int = 6) -> bool:
    """
    Bot start da Supabase'dan yuklash — main() va _main_no_signals() ikkalasi ham
    AYNAN BIR MARTA chaqiradi. O'qishda xato bo'lsa RAM dagi qiymat O'CHIRILMAYDI
    va qayta uriniladi. Tartib: force_join_config → app_settings.force_join.
    """
    global _force_channels, _force_enabled, _loaded_ok
    from utils import tg_db, supabase_client as sb
    for attempt in range(_retries):
        try:
            if not tg_db.ready():
                raise RuntimeError("Supabase hali tayyor emas")
            row, source = None, ""
            try:
                row = await sb.select_one("force_join_config", "id", 1)
                if row is not None:
                    source = "force_join_config"
            except Exception as te:
                log.warning("force_join_config o'qilmadi (jadval yo'qmi?): %s", te)
            if row is None:
                # tg_db.get_settings_tg() xatoni yutib {} qaytaradi — bu yerda xato
                # ko'rinishi kerak (qayta urinish uchun), shuning uchun to'g'ridan-to'g'ri o'qiymiz
                arow = await sb.select_one("app_settings", "id", 1)
                fj = ((arow or {}).get("data") or {}).get("force_join")
                if fj:
                    row = {"channels": fj.get("channels", []), "enabled": fj.get("enabled", False)}
                    source = "app_settings"
            if row is not None:
                _force_channels = list(row.get("channels") or [])
                _force_enabled  = bool(row.get("enabled", False))
            _loaded_ok = True
            try:
                from utils import ram_cache as ram
                ram._set("force_join_channels", list(_force_channels))
                ram._set("force_join_enabled",  _force_enabled)
            except Exception:
                pass
            log.info("Force join yuklandi [%s]: %d kanal, enabled=%s",
                     source or "bo'sh (hali sozlanmagan)", len(_force_channels), _force_enabled)
            if source == "app_settings":
                await persist()          # yangi jadvalga ko'chirib qo'yamiz
            return True
        except Exception as e:
            log.warning("force_join load xato (urinish %d/%d): %s", attempt + 1, _retries, e)
            await asyncio.sleep(5 * (attempt + 1))
    log.error("force_join yuklanmadi — RAM dagi qiymat saqlab qolindi (%d kanal, enabled=%s)",
              len(_force_channels), _force_enabled)
    return False


# ── Asosiy tekshiruv ────────────────────────────────────────
_member_cache: dict = {}          # uid -> (vaqt, [a'zo bo'lmagan kanal id lari])
_TTL_OK, _TTL_BAD = 90, 4         # a'zo bo'lganlar 90s, bo'lmaganlar 4s keshlanadi
_chan_err_ts: dict = {}           # kanal -> oxirgi xato log vaqti (spam bo'lmasin)
_pending_start: dict = {}         # uid -> "/start ..." parametri (obunadan keyin qaytarish)


_pub: dict = {}                    # uid -> (ok, vaqt)  (web uchun holat e'loni)


def publish_status(uid: int, ok: bool):
    """
    Foydalanuvchining obuna holatini Supabase `force_join_status` jadvaliga yozadi (fonda,
    o'zgarganda yoki 20 daqiqada bir). Web sahifa shu jadvalni o'qib, obunasizni to'xtatadi
    (qarang: WEB_FORCE_JOIN.md).
    """
    now = _time.time()
    last = _pub.get(uid)
    if last and last[0] == ok and now - last[1] < 1200:
        return
    _pub[uid] = (ok, now)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _go():
        try:
            from utils import tg_db, supabase_client as sb
            if tg_db.ready():
                from datetime import datetime, timezone
                await sb.upsert("force_join_status",
                                {"user_id": int(uid), "ok": bool(ok),
                                 "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                on_conflict="user_id")
        except Exception as e:
            log.debug("force_join_status yozilmadi: %s", e)
    loop.create_task(_go())


def invalidate_member_cache(uid: int = None):
    if uid is None:
        _member_cache.clear()
    else:
        _member_cache.pop(uid, None)


def remember_start(uid: int, param: str):
    if param:
        _pending_start[uid] = param


def pop_pending_start(uid: int) -> str:
    return _pending_start.pop(uid, "")


def _is_not_member(member) -> bool:
    status = getattr(member, "status", "")
    if status in ("left", "kicked", "banned"):
        return True
    # "restricted" — a'zo bo'lib chiqib ketgan bo'lishi mumkin (is_member=False)
    if status == "restricted" and getattr(member, "is_member", True) is False:
        return True
    return False


async def check_user_joined(bot, user_id: int, use_cache: bool = True) -> list:
    """
    Foydalanuvchi barcha majburiy kanallarga a'zo ekanligini tekshirish.
    Qaytaradi: a'zo bo'lmagan kanallar ro'yxati (bo'sh = hammaga a'zo).
    """
    if not _force_enabled or not _force_channels:
        return []
    now = _time.time()
    if use_cache:
        hit = _member_cache.get(user_id)
        if hit:
            ts, ids = hit
            ttl = _TTL_BAD if ids else _TTL_OK
            if now - ts < ttl:
                return [c for c in _force_channels if c["id"] in ids]

    not_joined = []
    for ch in _force_channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            _chan_last_error.pop(ch["id"], None)
            if _is_not_member(member):
                not_joined.append(ch)
        except Exception as e:
            # Tekshira olmadik (bot kanalda admin emas / kanal topilmadi). Foydalanuvchini
            # bloklamaymiz, lekin buni ADMIN ko'rishi uchun ERROR darajasida yozamiz.
            _chan_last_error[ch["id"]] = str(e)[:120]
            if now - _chan_err_ts.get(ch["id"], 0) > 600:
                _chan_err_ts[ch["id"]] = now
                log.error("MAJBURIY OBUNA: get_chat_member(%s) ishlamayapti: %s "
                          "— bot shu kanalda ADMIN bo'lishi shart!", ch["id"], e)
    _member_cache[user_id] = (now, [c["id"] for c in not_joined])
    publish_status(user_id, not not_joined)
    return not_joined


async def user_allowed(bot, user_id: int) -> bool:
    """True — majburiy obuna o'chiq, yoki foydalanuvchi admin, yoki hamma kanalga a'zo."""
    if not _force_enabled or not _force_channels:
        return True
    try:
        from config import ADMIN_IDS
        if user_id in ADMIN_IDS:
            return True
    except Exception:
        pass
    return not await check_user_joined(bot, user_id)


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
            return True
        elif isinstance(event, CallbackQuery):
            if event.message:
                await event.message.answer(text, reply_markup=markup)
            elif event.from_user:
                await bot.send_message(event.from_user.id, text, reply_markup=markup)
        elif isinstance(event, int):          # to'g'ridan user_id ga (guruhdan DM)
            await bot.send_message(event, text, reply_markup=markup)
            return True
        return True
    except Exception as e:
        log.warning(f"send_join_request: {e}")
        return False

async def handle_fj_check(callback: CallbackQuery):
    """'A'zo bo'ldim' tugmasi bosilganda qayta tekshirish"""
    uid       = callback.from_user.id
    not_joined = await check_user_joined(callback.bot, uid, use_cache=False)
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
