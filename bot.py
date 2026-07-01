
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from utils import ram_cache as ram
from handlers import webauth
from handlers import web_cmd


import blocked as _blocked_mod

async def _send_blocked_msg(bot, uid: int):
    """Bloklangan userga xabar + tugmalar."""
    from config import ADMIN_USERNAME
    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
    from aiogram.types import InlineKeyboardButton as _IKBtn
    b = _IKB()
    b.row(_IKBtn(text="📩 Adminga murojat", url=f"https://t.me/{ADMIN_USERNAME}"))
    b.row(_IKBtn(text="🤖 Bot orqali yozish", callback_data="contact_admin"))
    try:
        await bot.send_message(
            uid,
            "🚫 <b>Hisobingiz bloklangan</b>\n\n"
            "Botdan foydalanish to\'xtatilgan.\n\n"
            "To\'lov qilgan bo\'lsangiz yoki xato bo\'lsa\n"
            "admin bilan bog\'laning 👇",
            reply_markup=b.as_markup()
        )
    except Exception:
        pass


class ForceJoinMiddleware(BaseMiddleware):
    """
    Majburiy obuna tekshiruvi.
    FAQAT private chatda ishlaydi.
    Guruh/kanal chatlarida UMUMAN ishlamaydi.
    """
    SKIP_CALLBACKS = {"fj_check", "main_menu", "noop"}
    SKIP_COMMANDS  = {"/start"}

    async def __call__(self, handler, event, data):
        try:
            from utils.force_join import (
                is_force_enabled, check_user_joined, send_join_request
            )
            from config import ADMIN_IDS

            if not is_force_enabled():
                return await handler(event, data)

            # Chat turini aniqlash - GURUHDA ISHLAMAYDI
            chat_type = "private"
            uid       = None

            if isinstance(event, Message):
                chat_type = event.chat.type if event.chat else "private"
                uid       = event.from_user.id if event.from_user else None
                # /start o'zi tekshiradi
                if event.text and event.text.startswith("/start"):
                    return await handler(event, data)
            elif isinstance(event, CallbackQuery):
                chat_type = (event.message.chat.type
                             if event.message and event.message.chat
                             else "private")
                uid       = event.from_user.id if event.from_user else None
                if event.data in self.SKIP_CALLBACKS:
                    return await handler(event, data)

            # GURUH — tekshirmasdan o'tkazish
            if chat_type in ("group", "supergroup", "channel"):
                return await handler(event, data)

            # Admin tekshirilmaydi
            if uid and uid in ADMIN_IDS:
                return await handler(event, data)

            # Private chatda tekshirish
            if uid:
                not_joined = await check_user_joined(event.bot, uid)
                if not_joined:
                    await send_join_request(event, not_joined, event.bot)
                    if isinstance(event, CallbackQuery):
                        await event.answer(
                            "❌ Avval kanallarga a'zo bo'ling!",
                            show_alert=True
                        )
                    return   # Bloklaymiz

        except Exception as _fje:
            import logging
            logging.getLogger(__name__).warning(f"ForceJoinMiddleware: {_fje}")

        return await handler(event, data)



class BlockedUserMiddleware(BaseMiddleware):
    """
    Barcha event turlarida bloklangan userlarni to'xtatadi.
    blocked.py dan tez O(1) tekshiruv.
    """
    # contact_admin — bloklangan user ham murojat qila olsin
    ALLOWED_CALLBACKS = {"contact_admin"}

    async def __call__(self, handler, event, data):
        from aiogram.types import PollAnswer as _PA, InlineQuery as _IQ

        uid = None
        if isinstance(event, Message):
            uid = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            uid = event.from_user.id if event.from_user else None
            # Murojat tugmasi — o'tkazib yuborish
            if uid and event.data in self.ALLOWED_CALLBACKS:
                return await handler(event, data)
        elif isinstance(event, _PA):
            uid = event.user.id if event.user else None
        elif isinstance(event, _IQ):
            uid = event.from_user.id if event.from_user else None

        if uid and _blocked_mod.is_blocked(uid):
            bot = data.get("bot")
            if bot:
                await _send_blocked_msg(bot, uid)
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(
                        "🚫 Hisobingiz bloklangan!", show_alert=True
                    )
                except Exception:
                    pass
            return  # Handler ga O'TKAZMAYMIZ

        return await handler(event, data)


class ClearMenuMiddleware(BaseMiddleware):
    """
    Xabarni O'CHIRMAYDI — chunki o'chirilsa pastdagi ReplyKeyboard yo'qoladi.
    Faqat inline keyboard ni tozalaydi (edit).
    """
    async def __call__(self, handler, event, data):
        uid = None
        bot = None
        if isinstance(event, Message):
            uid = event.from_user.id if event.from_user else None
            bot = event.bot
        elif isinstance(event, CallbackQuery):
            if event.data == "main_menu":
                return await handler(event, data)
            uid = event.from_user.id if event.from_user else None
            bot = event.bot

        if uid and bot:
            menu = ram.get_menu_msg(uid)
            if menu:
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=menu["cid"],
                        message_id=menu["mid"],
                        reply_markup=None
                    )
                except Exception:
                    pass
                ram.pop_menu_msg(uid)

        try:
            return await handler(event, data)
        except TelegramBadRequest as e:
            if "query is too old" in str(e) or "query ID is invalid" in str(e):
                return
            raise


class GroupTrackerMiddleware(BaseMiddleware):
    """
    Guruhdan kelgan har bir xabar/callbackda guruhni
    avtomatik ro'yxatga qo'shadi. Shu tarzda bot
    avval qo'shilgan guruhlar ham saqlanadi.
    """
    async def __call__(self, handler, event, data):
        chat = None
        bot  = None
        if isinstance(event, Message):
            chat = event.chat
            bot  = event.bot
        elif isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat
            bot  = event.bot

        if chat and chat.type in ("group", "supergroup"):
            cid = str(chat.id)
            existing = ram.get_known_groups().get(cid)
            # Faqat noma'lum yoki yangi ma'lumot bo'lsa yangilaymiz
            if not existing or not existing.get("active"):
                try:
                    mc = await bot.get_chat_member_count(chat.id)
                except Exception:
                    mc = existing.get("member_count", 0) if existing else 0
                ram.add_known_group(
                    chat_id=chat.id,
                    title=chat.title or "Nomsiz guruh",
                    username=getattr(chat, "username", "") or "",
                    chat_type=chat.type,
                    member_count=mc,
                )

        return await handler(event, data)




"""🤖 BOT — Asosiy ishga tushirish"""
import asyncio, logging
from datetime import datetime, timezone, date, timedelta
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, STORAGE_CHANNEL_ID, ADMIN_IDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger(__name__)
UTC = timezone.utc



# ── LOOP HEALTH — real-time monitoring ───────────────────────────
import time as _time

_LOOP_HEALTH: dict = {}   # loop_name → {last_beat, status, errors, started_at}

def _beat(name: str, status: str = "ok", error: str = ""):
    """Loop o'z yurak urishi (heartbeat) ni yozadi"""
    _LOOP_HEALTH[name] = {
        "last_beat":  _time.time(),
        "status":     status,
        "error":      error,
        "started_at": _LOOP_HEALTH.get(name, {}).get("started_at", _time.time()),
        "errors":     _LOOP_HEALTH.get(name, {}).get("errors", 0) + (1 if error else 0),
    }

def get_loop_health() -> dict:
    return dict(_LOOP_HEALTH)


async def main():
    from handlers.inline_mode import router as r_inline
    from handlers.poll_router import router as r_poll_router
    from handlers.group       import router as r_group
    from handlers.poll_test   import router as r_poll
    from handlers.start       import router as r_start
    from handlers.tests       import router as r_tests
    from handlers.create_test  import router as r_create
    from handlers.profile      import router as r_profile
    from handlers.leaderboard  import router as r_lb
    from handlers.admin        import router as r_admin
    from handlers.roles_admin  import router as r_roles
    from handlers.referral        import router as r_referral
    from handlers.group_scheduler import router as r_scheduler
    from handlers.photo_upload    import router as r_photo

    # Xavfsizlik sozlamasi (dinamik)
    from utils.ram_cache import is_protect_content
    _protect = is_protect_content()

    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML, protect_content=_protect))
    dp  = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ForceJoinMiddleware())
    dp.callback_query.middleware(ForceJoinMiddleware())
    dp.message.middleware(BlockedUserMiddleware())
    dp.callback_query.middleware(BlockedUserMiddleware())
    dp.poll_answer.middleware(BlockedUserMiddleware())
    dp.inline_query.middleware(BlockedUserMiddleware())
    dp.message.middleware(ClearMenuMiddleware())
    dp.callback_query.middleware(ClearMenuMiddleware())
    dp.message.middleware(GroupTrackerMiddleware())
    dp.callback_query.middleware(GroupTrackerMiddleware())

    dp.include_router(r_inline)
    dp.include_router(r_poll_router)
    dp.include_router(r_group)
    dp.include_router(r_poll)
    dp.include_router(r_start)
    dp.include_router(r_tests)
    dp.include_router(r_create)
    dp.include_router(r_profile)
    dp.include_router(r_lb)
    dp.include_router(r_admin)
    dp.include_router(r_roles)
    dp.include_router(r_referral)
    dp.include_router(r_scheduler)
    dp.include_router(r_photo)
    dp.include_router(webauth.router)
    dp.include_router(web_cmd.router)
    # TG DB (Supabase) boshlash
    from config import SUPABASE_URL, SUPABASE_KEY
    if SUPABASE_URL and SUPABASE_KEY:
        from utils import tg_db
        log.info("Supabase DB initsializatsiya...")
        await tg_db.init(bot, STORAGE_CHANNEL_ID)
        from utils import ram_cache as ram
        tests = await tg_db.get_tests()
        if tests: ram.set_tests(tests)
        users = await tg_db.get_users()
        if users: ram.set_users(users)
        settings = await tg_db.get_settings_tg()
        if settings: ram.set_all_settings(settings)
        log.info(f"✅ Yuklandi: {ram.stats()['tests']} test meta, {ram.stats()['users']} user (savollar lazy)")
        _blocked_mod.load()
    else:
        log.error("❌ SUPABASE_URL / SUPABASE_KEY sozlanmagan — bot ma'lumotlarsiz ishga tushadi!")

    # Background tasklar — to'g'ri bekor qilish uchun saqlaymiz
    _bg_tasks = [
        asyncio.create_task(_midnight_flush_loop(bot),      name="midnight_flush"),
        asyncio.create_task(_users_auto_flush_loop(bot),    name="users_flush"),
        asyncio.create_task(_cache_cleanup_loop(),          name="cache_cleanup"),
        asyncio.create_task(_web_sync_watchdog(),           name="web_sync_watchdog"),
        asyncio.create_task(tg_db.auto_flush_loop(),        name="auto_flush"),
    ]

    # Admin ga xabar
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"✅ <b>Bot ishga tushdi!</b>\n"
                f"📅 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC",
                protect_content=False)
        except Exception: pass

    log.info("🚀 Bot ishga tushdi!")
    try:
        await dp.start_polling(bot, drop_pending_updates=True, allowed_updates=["message","callback_query","poll_answer","inline_query","my_chat_member"])
    finally:
        # Background tasklarni to'g'ri to'xtatish
        for t in _bg_tasks:
            t.cancel()
        await asyncio.gather(*_bg_tasks, return_exceptions=True)
        # Session ni yopish
        session = bot.session
        if hasattr(session, 'close'):
            await session.close()


# ── MIDNIGHT FLUSH — kuniga 1 marta, faqat 00:00 ──────────────

async def _scan_groups_on_startup(bot):
    """
    Bot yoqilganda get_chat_administrators orqali guruhlarni topish.
    get_updates ishlatilmaydi — conflict oldini olish uchun.
    Middleware har xabar kelganda guruhni avtomatik qo'shadi.
    """
    await asyncio.sleep(10)
    log.info("Guruh startup skani: middleware orqali avtomatik to'ldiriladi")


async def _midnight_flush_loop(bot):
    """
    Har kun 00:00 UTC da:
    1. Kecha kunlik natijalarni TG ga yuboradi (backup)
    2. Users va settings saqlaydi
    3. RAM daily tozalanmaydi — testlar va users doim qoladi
    """
    flushed_date = None
    _beat("midnight_flush", "ok")
    while True:
        try:
            await asyncio.sleep(60)
            _beat("midnight_flush", "ok")
            now   = datetime.now(UTC)
            today = date.today()
            if now.hour == 0 and now.minute < 5 and flushed_date != today:
                flushed_date = today
                _beat("midnight_flush", "running")
                log.info("🌙 Midnight flush boshlanmoqda...")
                from utils import tg_db, ram_cache as ram

                yesterday = str(today - timedelta(days=1))
                daily     = ram.get_daily()
                users     = ram.get_users()
                settings  = ram.get_all_settings()

                if tg_db.ready():
                    if daily:
                        mid = await tg_db.upload_backup(daily, yesterday)
                        log.info(f"✅ Backup yuborildi: {yesterday} msg={mid}")
                    await tg_db.save_users(users)
                    ram.clear_users_dirty()
                    await tg_db.save_settings(settings)
                    ram.clear_daily()
                    log.info("✅ Midnight flush yakunlandi, daily RAM tozalandi")

                for aid in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            aid,
                            f"🌙 <b>Midnight Flush</b> yakunlandi!\n"
                            f"📅 {yesterday} backupi saqlandi\n"
                            f"👥 {len(users)} user | 💾 {len(daily)} kunlik yozuv"
                        )
                    except Exception: pass
                _beat("midnight_flush", "ok")
        except asyncio.CancelledError:
            break
        except Exception as e:
            _beat("midnight_flush", "error", str(e))
            log.error(f"Flush loop xato: {e}")


# ── USERS AUTO FLUSH — o'chirildi
# Users faqat midnight da yoki yangi user kelganda yuklanadi
# (test yechilganda TG ga hech narsa yuborilmaydi)

async def _users_auto_flush_loop(bot):
    """Disabled — users faqat midnight da yuklanadi"""
    pass


async def _web_sync_watchdog():
    """
    web_sync_loop ni kuzatib turadi.
    - Loop to'xtab qolsa → qayta ishga tushiradi
    - 15 daqiqa heartbeat kelmasa → o'ldiradi va qayta boshlaydi
    - Holat _LOOP_HEALTH ga yoziladi
    """
    from utils import tg_db
    _beat("web_sync", "starting")
    HEARTBEAT_TIMEOUT = 900  # 15 daqiqa

    while True:
        try:
            _beat("web_sync", "running")
            task = asyncio.create_task(_web_sync_with_beat(tg_db))
            # Heartbeat kuzatuvchi
            while not task.done():
                await asyncio.sleep(60)
                h = _LOOP_HEALTH.get("web_sync", {})
                last = h.get("last_beat", _time.time())
                if _time.time() - last > HEARTBEAT_TIMEOUT:
                    log.warning("⚠️ web_sync_loop javob bermayapti — majburan qayta boshlanadi")
                    _beat("web_sync", "timeout", "Heartbeat timeout")
                    task.cancel()
                    try: await task
                    except: pass
                    break

            if not task.cancelled():
                log.warning("⚠️ web_sync_loop tugadi — 10s dan keyin qayta boshlanadi")
            _beat("web_sync", "restarting")
            await asyncio.sleep(10)

        except asyncio.CancelledError:
            break
        except Exception as e:
            _beat("web_sync", "error", str(e))
            log.error(f"web_sync_watchdog xato: {e} — 30s dan keyin qayta boshlanadi")
            await asyncio.sleep(30)


async def _web_sync_with_beat(tg_db):
    """web_sync_loop — heartbeat bilan o'ralgan versiya"""
    from utils import tg_db as _tg
    _beat("web_sync", "running")
    consecutive_errors = 0
    last_sig           = None

    while True:
        try:
            await asyncio.sleep(60)
            _beat("web_sync", "ok")  # ← har daqiqada yurak urishi

            if not _tg.ready():
                continue

            from utils import ram_cache as ram

            try:
                chat = await asyncio.wait_for(_tg._bot.get_chat(_tg._cid), timeout=10)
                pin  = getattr(chat, "pinned_message", None)
                if not pin:
                    continue
                doc     = getattr(pin, "document", None)
                doc_uid = getattr(doc, "file_unique_id", None) if doc else None
                cur_sig = (pin.message_id, doc_uid, getattr(pin, "edit_date", None))
            except Exception as e:
                _beat("web_sync", "warn", f"get_chat: {e}")
                consecutive_errors += 1
                continue

            if cur_sig == last_sig:
                continue
            last_sig = cur_sig

            try:
                new_meta = await asyncio.wait_for(_tg._read_pinned_index(), timeout=20)
            except asyncio.TimeoutError:
                _beat("web_sync", "warn", "read_pinned timeout")
                consecutive_errors += 1
                continue
            if not new_meta:
                continue
            consecutive_errors = 0

            new_metas    = []
            new_test_ids = {}
            for ch in new_meta.get("index_chunks", []):
                fid  = ch.get("fid")
                mid  = ch.get("msg_id")
                data = {}
                if fid:  data = await _tg._read_file(fid)
                if not data and mid: data = await _tg._download_doc(mid)
                for m in data.get("tests_meta", []):
                    if not any(x.get("test_id") == m.get("test_id") for x in new_metas):
                        new_metas.append(m)
                for k, v in data.items():
                    if k.startswith("test_"):
                        new_test_ids[k] = v

            if "tests_meta" in new_meta and "index_chunks" not in new_meta:
                new_metas    = new_meta.get("tests_meta", [])
                new_test_ids = {k: v for k, v in new_meta.items() if k.startswith("test_")}

            ram_ids = {t.get("test_id") for t in ram.get_all_tests_meta()}
            added = updated = 0
            for meta in new_metas:
                tid = meta.get("test_id")
                if not tid: continue
                new_msg_id  = new_test_ids.get(f"test_{tid}")
                old_msg_id  = _tg._index.get(f"test_{tid}")
                msg_changed = new_msg_id and str(new_msg_id) != str(old_msg_id or "")
                if tid not in ram_ids:
                    clean = {k: v for k, v in meta.items() if k != "questions"}
                    ram.add_test_meta(clean)
                    if not any(m.get("test_id") == tid for m in _tg._index.get("tests_meta", [])):
                        _tg._index.setdefault("tests_meta", []).insert(0, clean)
                    if new_msg_id:
                        _tg._index[f"test_{tid}"] = new_msg_id
                    added += 1
                    if meta.get("source", "") in ("web", "web_split"):
                        asyncio.create_task(_tg._notify_web_test(meta, tid))
                elif msg_changed:
                    old_meta = next((m for m in ram.get_all_tests_meta() if m.get("test_id") == tid), {})
                    old_qc   = old_meta.get("question_count", 0)
                    _tg._tests_cache.pop(tid, None)
                    ram.invalidate_cached_questions(tid)
                    _tg._index[f"test_{tid}"] = new_msg_id
                    _tg._index.pop(f"fid_{old_msg_id}", None)
                    clean = {k: v for k, v in meta.items() if k != "questions"}
                    ram.update_test_meta(tid, clean)
                    updated += 1
                    new_qc = meta.get("question_count", 0)
                    asyncio.create_task(_tg._notify_updated_test(meta, tid, old_qc, new_qc))

            if added or updated:
                log.info(f"Web sync: {added} yangi, {updated} yangilangan test")
                _tg.mark_index_dirty()
                try:
                    await _tg._save_index()
                    try:
                        chat2 = await _tg._bot.get_chat(_tg._cid)
                        pin2  = getattr(chat2, "pinned_message", None)
                        if pin2:
                            doc2 = getattr(pin2, "document", None)
                            uid2 = getattr(doc2, "file_unique_id", None) if doc2 else None
                            last_sig = (pin2.message_id, uid2, getattr(pin2, "edit_date", None))
                    except Exception: pass
                except Exception as _se:
                    log.warning(f"Web sync: index saqlashda xato: {_se}")

        except asyncio.CancelledError:
            _beat("web_sync", "cancelled")
            break
        except Exception as e:
            consecutive_errors += 1
            _beat("web_sync", "error", str(e))
            log.error(f"web_sync_loop: {e}")
            if consecutive_errors >= 5:
                await asyncio.sleep(900)
                consecutive_errors = 0


# ── CACHE CLEANUP — har 30 daqiqada ──────────────────────────

async def _cache_cleanup_loop():
    """
    Har 15 daqiqada:
    - 48 soat yechilmagan test savollarini RAMdan o'chiradi
    - 2 soatdan eski tahlillarni RAMdan o'chiradi
    - 2 soatdan eski user stats RAMdan o'chiradi
    """
    await asyncio.sleep(900)
    while True:
        try:
            await asyncio.sleep(900)
            from utils import ram_cache as ram, tg_db
            removed = ram.clear_expired_cache()
            if removed:
                for tid in removed:
                    tg_db._tests_cache.pop(tid, None)  # noqa: SLF001 — internal cache, intentional
                log.info(f"🧹 Cache: {len(removed)} test RAMdan o'chirildi")
            ana = ram.clear_expired_analysis()
            if ana:
                log.info(f"🧹 Analysis: {ana} ta tahlil RAMdan o'chirildi")
            sts = ram.clear_expired_stats()
            if sts:
                log.info(f"🧹 Stats: {sts} ta user stats RAMdan o'chirildi")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Cache cleanup xato: {e}")


if __name__ == "__main__":
    asyncio.run(main())


# ── Streamlit uchun background thread ────────────────────────

_bot_thread    = None
_BOT_LOCK_FILE = "/tmp/quizmakerbot.lock"


def run_in_background():
    """
    streamlit_app.py tomonidan chaqiriladi.
    OS lock fayl orqali faqat BITTA instance ishlashini ta'minlaydi.
    """
    global _bot_thread
    import threading, fcntl, os

    # 1. Thread allaqachon ishlayaptimi?
    if _bot_thread is not None and _bot_thread.is_alive():
        log.info("Bot thread allaqachon ishlayapti — qayta tushirilmadi")
        return _bot_thread

    # 2. Lock fayl — boshqa process ishlayaptimi?
    try:
        lock_fd = open(_BOT_LOCK_FILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        log.info(f"Bot lock olindi: {_BOT_LOCK_FILE}")
    except BlockingIOError:
        log.warning("Boshqa bot instance ishlayapti — bu instance ishga tushmaydi")
        return None

    def _run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_main_no_signals())
        except Exception as e:
            log.error(f"Bot thread xato: {e}")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
                os.unlink(_BOT_LOCK_FILE)
            except Exception:
                pass

    _bot_thread = threading.Thread(target=_run, daemon=True, name="TelegramBot")
    _bot_thread.start()
    log.info("Bot thread ishga tushdi")
    return _bot_thread


async def _main_no_signals():
    """main() ning signal-handlersiz versiyasi — thread uchun"""
    from handlers.inline_mode import router as r_inline
    from handlers.poll_router import router as r_poll_router
    from handlers.group       import router as r_group
    from handlers.poll_test   import router as r_poll
    from handlers.start       import router as r_start
    from handlers.tests       import router as r_tests
    from handlers.create_test import router as r_create
    from handlers.profile     import router as r_profile
    from handlers.leaderboard import router as r_lb
    from handlers.admin       import router as r_admin
    from handlers.roles_admin import router as r_roles
    from handlers.referral        import router as r_referral
    from handlers.group_scheduler import router as r_scheduler
    from handlers.photo_upload    import router as r_photo

    # Xavfsizlik sozlamasi
    from utils.ram_cache import is_protect_content
    _protect = is_protect_content()

    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML, protect_content=_protect))
    dp  = Dispatcher(storage=MemoryStorage())
    # ── Barcha middlewarelar (main() bilan bir xil) ──
    dp.message.middleware(ForceJoinMiddleware())
    dp.callback_query.middleware(ForceJoinMiddleware())
    dp.message.middleware(BlockedUserMiddleware())
    dp.callback_query.middleware(BlockedUserMiddleware())
    dp.poll_answer.middleware(BlockedUserMiddleware())
    dp.inline_query.middleware(BlockedUserMiddleware())
    dp.message.middleware(ClearMenuMiddleware())
    dp.callback_query.middleware(ClearMenuMiddleware())
    dp.message.middleware(GroupTrackerMiddleware())
    dp.callback_query.middleware(GroupTrackerMiddleware())

    dp.include_router(r_inline)
    dp.include_router(r_poll_router)
    dp.include_router(r_group)
    dp.include_router(r_poll)
    dp.include_router(r_start)
    dp.include_router(r_tests)
    dp.include_router(r_create)
    dp.include_router(r_profile)
    dp.include_router(r_lb)
    dp.include_router(r_admin)
    dp.include_router(r_roles)
    dp.include_router(r_referral)
    dp.include_router(r_scheduler)
    dp.include_router(r_photo)
    dp.include_router(webauth.router)
    dp.include_router(web_cmd.router)

    # ── Baza guruhiga yuborilgan fayllarni handle qilish ──
    from aiogram import F as _F
    from aiogram.types import Message as _Msg
    from aiogram import Router as _Router

    _baza_router = _Router()

    @_baza_router.message(_F.document)
    async def _handle_group_doc(message: _Msg):
        """Baza guruhiga yuborilgan fayl → parse → test yaratish
        FAQAT guruh/kanal chatida ishlaydi — private chatda EMAS
        """
        try:
            # Private chat — bu handler ISHLAMAYDI
            # (private chatda create_test.py upload_file ishlaydi)
            if message.chat.type == "private":
                return

            from utils.baza_publisher import parse_group_file
            from config import BAZA_GROUP_ID
            if not BAZA_GROUP_ID:
                return
            if message.chat.id != int(BAZA_GROUP_ID):
                return
            u = message.from_user
            await parse_group_file(
                bot              = message.bot,
                message          = message,
                creator_id       = u.id,
                creator_name     = u.full_name or "",
                creator_username = u.username or "",
            )
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(f"Group doc handler: {_e}")

    dp.include_router(_baza_router)

    from config import SUPABASE_URL, SUPABASE_KEY
    if SUPABASE_URL and SUPABASE_KEY:
        from utils import tg_db
        await tg_db.init(bot, STORAGE_CHANNEL_ID)
        from utils import ram_cache as ram
        # Faqat META yuklanadi — savollar lazy load
        tests = await tg_db.get_tests()
        if tests: ram.set_tests(tests)
        users = await tg_db.get_users()
        if users: ram.set_users(users)
        settings = await tg_db.get_settings_tg()
        if settings: ram.set_all_settings(settings)
        log.info(f"✅ Yuklandi: {ram.stats()['tests']} test meta, {ram.stats()['users']} user")
        _blocked_mod.load()
    else:
        from utils import tg_db   # auto_flush_loop pastda kerak bo'ladi, lekin ready()=False bo'ladi
        log.error("❌ SUPABASE_URL / SUPABASE_KEY sozlanmagan!")

    # Startup da bot admin bo'lgan guruhlarni aniqlash
    asyncio.create_task(_scan_groups_on_startup(bot))

    asyncio.create_task(_midnight_flush_loop(bot))
    asyncio.create_task(_users_auto_flush_loop(bot))
    asyncio.create_task(_cache_cleanup_loop())
    asyncio.create_task(_web_sync_watchdog())
    asyncio.create_task(tg_db.auto_flush_loop())   # FIX: Streamlit threadida ham

    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"✅ <b>Bot ishga tushdi!</b>\n"
                f"📅 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
        except Exception: pass

    # Force join keshdan yuklash
    try:
        from utils.force_join import load_from_cache
        load_from_cache()
    except Exception as _fje:
        log.warning(f"force_join load: {_fje}")

    log.info("🚀 Bot ishga tushdi!")
    # handle_signals=False — thread dan ishga tushirilganda signal xatosini oldini oladi
    try:
        await dp.start_polling(bot, drop_pending_updates=True, handle_signals=False, allowed_updates=["message","callback_query","poll_answer","inline_query","my_chat_member"])
    finally:
        await bot.session.close()
