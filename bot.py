
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from utils import ram_cache as ram
from handlers import webauth


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

    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML, protect_content=True))
    dp  = Dispatcher(storage=MemoryStorage())
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
    # TG DB boshlash
    if STORAGE_CHANNEL_ID:
        from utils import tg_db
        log.info("TG DB initsializatsiya...")
        await tg_db.init(bot, STORAGE_CHANNEL_ID)
        from utils import ram_cache as ram
        # Faqat META yuklanadi — savollar yuklanmaydi (lazy load)
        tests = await tg_db.get_tests()
        if tests: ram.set_tests(tests)   # set_tests endi faqat meta saqlaydi
        users = await tg_db.get_users()
        if users: ram.set_users(users)
        settings = await tg_db.get_settings_tg()
        if settings: ram.set_all_settings(settings)
        log.info(f"✅ Yuklandi: {ram.stats()['tests']} test meta, {ram.stats()['users']} user (savollar lazy)")

    # Background tasklar
    asyncio.create_task(_midnight_flush_loop(bot))
    asyncio.create_task(_users_auto_flush_loop(bot))
    asyncio.create_task(_cache_cleanup_loop())
    asyncio.create_task(_web_sync_watchdog())   # Watchdog bilan web sync
    asyncio.create_task(tg_db.auto_flush_loop())

    # Admin ga xabar
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"✅ <b>Bot ishga tushdi!</b>\n"
                f"📅 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC",
                protect_content=False)
        except Exception: pass

    log.info("🚀 Bot ishga tushdi!")
    await dp.start_polling(bot, drop_pending_updates=True, allowed_updates=["message","callback_query","poll_answer","inline_query","my_chat_member"])


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
    while True:
        try:
            await asyncio.sleep(60)
            now   = datetime.now(UTC)
            today = date.today()
            if now.hour == 0 and now.minute < 5 and flushed_date != today:
                flushed_date = today
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
        except asyncio.CancelledError:
            break
        except Exception as e:
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
    Agar loop to'xtab qolsa — qayta ishga tushiradi.
    """
    from utils import tg_db
    while True:
        try:
            task = asyncio.create_task(tg_db.web_sync_loop())
            await task
            log.warning("⚠️ web_sync_loop tugadi — 10s dan keyin qayta boshlanadi")
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"web_sync_watchdog xato: {e} — 30s dan keyin qayta boshlanadi")
            await asyncio.sleep(30)


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
                    tg_db._tests_cache.pop(tid, None)
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

    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML, protect_content=True))
    dp  = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ClearMenuMiddleware())
    dp.callback_query.middleware(ClearMenuMiddleware())


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

    if STORAGE_CHANNEL_ID:
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

    log.info("🚀 Bot ishga tushdi!")
    # handle_signals=False — thread dan ishga tushirilganda signal xatosini oldini oladi
    await dp.start_polling(bot, drop_pending_updates=True, handle_signals=False, allowed_updates=["message","callback_query","poll_answer","inline_query","my_chat_member"])
