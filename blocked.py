"""
blocked.py — Bloklangan foydalanuvchilar boshqaruvi
=====================================================
Oddiy va ishonchli: set() + JSON fayl.
Bot istalgan eventda bu moduldan tekshiradi.
"""
import json
import logging
import os

log = logging.getLogger(__name__)

# Bloklangan IDlar — xotira tez
_blocked: set[int] = set()

# Saqlash fayli
_FILE = "blocked_ids.json"


def load():
    """Bot yoqilganda fayldan yuklash"""
    global _blocked
    try:
        if os.path.exists(_FILE):
            with open(_FILE, "r") as f:
                ids = json.load(f)
            _blocked = set(int(i) for i in ids)
            log.info(f"Bloklangan: {len(_blocked)} ta user yuklandi")
        # RAM cache dan ham yuklash (qo'shimcha)
        try:
            from utils import ram_cache as ram
            for uid, u in ram.get_users().items():
                if u.get("is_blocked"):
                    _blocked.add(int(uid))
        except Exception:
            pass
    except Exception as e:
        log.error(f"blocked.load: {e}")
        _blocked = set()


def _save():
    """Faylga saqlash"""
    try:
        with open(_FILE, "w") as f:
            json.dump(list(_blocked), f)
    except Exception as e:
        log.error(f"blocked._save: {e}")


def block(uid: int):
    """Bloklash"""
    _blocked.add(uid)
    _save()
    # RAM cache da ham yangilash
    try:
        from utils.db import block_user
        block_user(uid, True)
    except Exception:
        pass
    log.info(f"Bloklandi: {uid}")


def unblock(uid: int):
    """Blokni ochish"""
    _blocked.discard(uid)
    _save()
    try:
        from utils.db import block_user
        block_user(uid, False)
    except Exception:
        pass
    log.info(f"Blok ochildi: {uid}")


def is_blocked(uid: int) -> bool:
    """Bloklangan yoki yo'q — O(1)"""
    return uid in _blocked


def get_all() -> set:
    return set(_blocked)
