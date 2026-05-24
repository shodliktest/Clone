"""
blocked.py — Bloklangan foydalanuvchilar boshqaruvi
=====================================================
IDlar RAM set + Telegram kanalda saqlanadi.
Bot restart da TG dan qayta yuklanadi.
"""
import logging

log = logging.getLogger(__name__)

# Bloklangan IDlar — xotira tez O(1)
_blocked: set = set()


def load():
    """Bot yoqilganda RAM cache dan yuklash (TG yuklanishi background da)."""
    try:
        from utils import ram_cache as ram
        for uid, u in ram.get_users().items():
            if u.get("is_blocked"):
                _blocked.add(int(uid))
        if _blocked:
            log.info(f"Bloklangan (RAM cache): {len(_blocked)} ta")
    except Exception as e:
        log.error(f"blocked.load: {e}")


def block(uid: int):
    """Bloklash — RAM + TG kanal."""
    _blocked.add(uid)
    # RAM cache yangilash
    try:
        from utils.db import block_user
        block_user(uid, True)
    except Exception:
        pass
    # TG ga saqlash
    _save_to_tg()
    log.info(f"Bloklandi: {uid}")


def unblock(uid: int):
    """Blokni ochish — RAM + TG kanal."""
    _blocked.discard(uid)
    try:
        from utils.db import block_user
        block_user(uid, False)
    except Exception:
        pass
    _save_to_tg()
    log.info(f"Blok ochildi: {uid}")


def is_blocked(uid: int) -> bool:
    """Bloklangan yoki yo'q — O(1)."""
    return uid in _blocked


def get_all() -> set:
    return set(_blocked)


def _save_to_tg():
    """TG kanalga asinxron saqlash."""
    import asyncio
    try:
        from utils import tg_db
        if tg_db.ready():
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(tg_db.save_blocked_users(_blocked))
            else:
                loop.run_until_complete(tg_db.save_blocked_users(_blocked))
    except Exception as e:
        log.error(f"blocked._save_to_tg: {e}")
