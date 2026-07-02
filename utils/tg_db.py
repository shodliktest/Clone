"""
TG_DB — Supabase (Postgres) bilan ishlaydigan ma'lumotlar qatlami
====================================================================
MUHIM: Bu modulning nomi va public funksiyalari ATAYLAB eski
"Telegram Storage Channel" versiyasi bilan bir xil saqlangan
(get_test_full, save_test_full, get_tests_meta, init, ready, ...).

Sabab: handlers/*.py, bot.py, streamlit_app.py barchasi shu
funksiya nomlari orqali murojaat qiladi. Shu fayl ichini
o'zgartirish orqali boshqa birorta faylga tegmasdan butun
saqlash arxitekturasini Telegram'dan Supabase'ga ko'chirish
mumkin bo'ladi.

NIMA O'ZGARDI (eski versiyaga nisbatan):
  • Endi hech qanday "kanal skanerlash", "chunk", "pin", "forward"
    yo'q — har bir o'qish/yozish to'g'ridan-to'g'ri SQL so'rov.
  • web_sync_loop endi DEYARLI BO'SH: bot va Telegram Web App
    bir xil Postgres'ga yozgani uchun alohida sinxronizatsiya
    kerak emas — RAM cache'ni vaqti-vaqti bilan yangilab turadi.
  • Flood-wait, "Too Many Requests", forward/delete xatolari —
    butunlay yo'qoladi (Telegram Bot API chaqirilmaydi, faqat
    PostgREST orqali ma'lumotlar bazasiga so'rov ketadi).
  • Crash xavfi kamaydi: har bir DB chaqiruvi alohida try/except
    bilan o'ralgan, bitta so'rov xatosi botni yiqitmaydi.
"""

import asyncio
import logging
from datetime import datetime, timezone, date

from utils import supabase_client as sb

log  = logging.getLogger(__name__)
UTC  = timezone.utc

_ready       = False
_tests_cache: dict = {}     # RAM-darajadagi tezkor cache (eski xulq-atvor saqlanadi)

_stats_dirty = False
_users_dirty = False
_index_dirty = False        # Endi haqiqiy ma'noga ega emas, lekin API moslik uchun saqlanadi

_otp_store: dict = {}        # OTP RAMda — bazaga yozish shart emas (qisqa umrli)


# ══════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════

async def init(bot, channel_id=None):
    """
    Eski imzo bilan moslik uchun `channel_id` parametri qoldirildi,
    lekin endi ishlatilmaydi — Supabase ulanishi config.py dagi
    SUPABASE_URL / SUPABASE_KEY orqali amalga oshiriladi.
    """
    global _ready, _tests_cache, _stats_dirty, _users_dirty, _index_dirty

    _tests_cache = {}
    _stats_dirty = False
    _users_dirty = False
    _index_dirty = False

    set_bot_instance(bot)

    from config import SUPABASE_URL, SUPABASE_KEY
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("❌ SUPABASE_URL / SUPABASE_KEY sozlanmagan — secrets.toml ni tekshiring")
        _ready = False
        return

    try:
        sb.init_client(SUPABASE_URL, SUPABASE_KEY)
        await sb.count("tests")
        _ready = True
        log.info("✅ Supabase ulanish tayyor")
    except Exception as e:
        _ready = False
        log.error(f"❌ Supabase ulanish xato: {e}")
        return

    try:
        await _load_tests_meta_to_ram()
    except Exception as e:
        log.error(f"tests meta yuklashda xato: {e}")

    asyncio.create_task(_load_users_to_ram())
    asyncio.create_task(_load_user_stats_to_ram())
    asyncio.create_task(load_known_groups())
    asyncio.create_task(_load_blocked_to_ram())

    log.info("Tayyor: tests meta yuklandi, qolganlari background da")


def ready():
    return _ready


def mark_stats_dirty():
    global _stats_dirty
    _stats_dirty = True

def mark_index_dirty():
    """Endi alohida 'index' tushunchasi yo'q — moslik uchun saqlangan no-op."""
    global _index_dirty
    _index_dirty = True

def mark_users_dirty_tg():
    global _users_dirty
    _users_dirty = True

def is_dirty():
    return _stats_dirty or _users_dirty or _index_dirty


# ══════════════════════════════════════════════════════════════
# YUKLASH — bot startida RAM cache'ni Supabase'dan to'ldiramiz
# ══════════════════════════════════════════════════════════════

async def _load_tests_meta_to_ram():
    from utils import ram_cache as ram
    try:
        rows = await sb.select("tests", columns="test_id,title,meta,question_count,"
                                                  "is_active,is_paused,solve_count,avg_score")
    except Exception as e:
        log.error(f"_load_tests_meta_to_ram: {e}")
        return

    metas = []
    for r in rows:
        meta = dict(r.get("meta") or {})
        meta["test_id"]        = r["test_id"]
        meta["title"]          = r.get("title", meta.get("title", ""))
        meta["question_count"] = r.get("question_count", 0)
        meta["is_active"]      = r.get("is_active", True)
        meta["is_paused"]      = r.get("is_paused", False)
        meta["solve_count"]    = r.get("solve_count", 0)
        meta["avg_score"]      = float(r.get("avg_score") or 0)
        metas.append(meta)

    ram.set_tests_meta(metas)
    log.info(f"tests meta yuklandi: {len(metas)} ta")


async def _load_users_to_ram():
    from utils import ram_cache as ram
    try:
        rows = await sb.select("users")
    except Exception as e:
        log.error(f"_load_users_to_ram: {e}")
        return
    users = {}
    for r in rows:
        d = dict(r.get("data") or {})
        d["tg_id"]      = r["tg_id"]
        d["is_blocked"] = r.get("is_blocked", False)
        users[str(r["tg_id"])] = d
    ram.set_users(users)
    log.info(f"users yuklandi: {len(users)} ta")


async def _load_user_stats_to_ram():
    from utils import ram_cache as ram
    try:
        rows = await sb.select("user_stats")
    except Exception as e:
        log.error(f"_load_user_stats_to_ram: {e}")
        return
    total = 0
    for r in rows:
        uid_str = str(r["tg_id"])
        ram.set_user_stats_cache(uid_str, dict(r.get("data") or {}), dirty=False)
        total += 1
    log.info(f"user_stats yuklandi: {total} ta")


async def _load_blocked_to_ram():
    from utils import ram_cache as ram
    try:
        blocked = await load_blocked_users()
        for uid in blocked:
            ram.set_blocked(uid, True)
        log.info(f"blocked yuklandi: {len(blocked)} ta")
    except Exception as e:
        log.error(f"_load_blocked_to_ram: {e}")


# ══════════════════════════════════════════════════════════════
# TESTLAR
# ══════════════════════════════════════════════════════════════

def get_tests_meta():
    from utils import ram_cache as ram
    return ram.get_all_tests_meta()


def get_test_meta(tid):
    from utils import ram_cache as ram
    m = ram.get_test_meta(tid)
    return m if (m and m.get("is_active", True)) else {}


async def get_test_full(tid: str) -> dict:
    """
    Test + savollarni qaytaradi. RAM cache → Postgres tartibida.
    Eski versiyadagi 4 bosqichli "fid/msg_id/chunk skan" zanjiri
    endi shunchaki BITTA SQL so'roviga almashtirildi.
    """
    from utils import ram_cache as ram

    if tid in _tests_cache:
        ram.touch_test_access(tid)
        return _tests_cache[tid]

    cached = ram.get_cached_questions(tid)
    if cached:
        _tests_cache[tid] = cached
        return cached

    if not ready():
        return {}

    try:
        row = await sb.select_one("tests", "test_id", tid)
    except Exception as e:
        log.error(f"get_test_full({tid}): {e}")
        return {}

    if not row:
        log.warning(f"{tid} topilmadi")
        return {}

    full = dict(row.get("meta") or {})
    full["test_id"]   = row["test_id"]
    full["title"]     = row.get("title", full.get("title", ""))
    full["questions"] = row.get("questions") or []

    _tests_cache[tid] = full
    ram.cache_questions(tid, full)
    return full


async def get_tests():
    return get_tests_meta()


async def save_test_full(test: dict) -> bool:
    """
    Test (meta + savollar) ni Postgres ga to'liq saqlaydi (upsert).

    Test tahrirlansa (yoki qayta yuklansa), eski holat 100% almashadi —
    versiya tarixi saqlanmaydi, faqat "joriy" holat bazada turadi.
    """
    if not ready():
        return False
    tid = test.get("test_id", "")
    if not tid:
        log.error("save_test_full: test_id yo'q")
        return False

    try:
        qc   = len(test.get("questions", []))
        meta = {k: v for k, v in test.items() if k not in ("questions", "test_id", "title")}

        row = {
            "test_id":        tid,
            "title":          test.get("title", ""),
            "questions":      test.get("questions", []),
            "meta":           meta,
            "question_count": qc,
            "is_active":      test.get("is_active", True),
            "is_paused":      test.get("is_paused", False),
            "solve_count":    test.get("solve_count", 0),
            "avg_score":      float(test.get("avg_score") or 0),
        }
        await sb.upsert("tests", row, on_conflict="test_id")

        _tests_cache[tid] = test

        from utils import ram_cache as ram
        clean = {k: v for k, v in test.items() if k != "questions"}
        clean["question_count"] = qc
        ram.add_test_meta(clean)
        ram.cache_questions(tid, test)

        log.info(f"save_test_full: {tid} saqlandi ({qc} savol)")
        return True
    except Exception as e:
        log.error(f"save_test_full({tid}): {e}")
        return False


async def save_deleted_test_backup(test: dict):
    """O'chirilgan testni 'backups' jadvaliga arxivlaydi (yo'qolmasligi uchun)."""
    if not ready():
        return
    tid = test.get("test_id", "NOID")
    _tests_cache.pop(tid, None)
    try:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        key = f"deleted_test_{tid}_{ts}"
        await sb.upsert("backups", {
            "date_str": key,
            "data": {"type": "deleted_test", "test": test, "deleted_at": ts},
        }, on_conflict="date_str")
        log.info(f"O'chirilgan test arxivlandi: {tid}")
    except Exception as e:
        log.error(f"save_deleted_test_backup({tid}): {e}")


async def delete_test_tg(tid: str):
    """Testni 'soft delete' qiladi (is_active=False) — ma'lumot bazada qoladi."""
    if not ready():
        return
    try:
        await sb.update("tests", "test_id", tid, {"is_active": False})
    except Exception as e:
        log.error(f"delete_test_tg({tid}): {e}")

    _tests_cache.pop(tid, None)
    from utils import ram_cache as ram
    ram.update_test_meta(tid, {"is_active": False})
    mark_stats_dirty()


async def update_test_meta_tg(tid: str, updates: dict):
    """Test meta'sini qisman yangilaydi (masalan is_paused, title, va h.k.)."""
    from utils import ram_cache as ram

    if not ready():
        return

    try:
        row = await sb.select_one("tests", "test_id", tid)
        if not row:
            log.warning(f"update_test_meta_tg: {tid} topilmadi")
            return

        patch = {}
        for col in ("title", "is_active", "is_paused", "solve_count", "avg_score"):
            if col in updates:
                patch[col] = updates[col]

        meta = dict(row.get("meta") or {})
        extra = {k: v for k, v in updates.items()
                 if k not in ("title", "is_active", "is_paused", "solve_count",
                              "avg_score", "test_id", "questions")}
        meta.update(extra)
        patch["meta"] = meta

        await sb.update("tests", "test_id", tid, patch)
    except Exception as e:
        log.error(f"update_test_meta_tg({tid}): {e}")
        return

    ram.update_test_meta(tid, updates)

    if tid in _tests_cache:
        _tests_cache[tid].update(updates)
        ram.cache_questions(tid, _tests_cache[tid])
    else:
        cached = ram.get_cached_questions(tid)
        if cached:
            cached.update(updates)
            ram.cache_questions(tid, cached)
            _tests_cache[tid] = cached

    mark_stats_dirty()
    log.info(f"update_test_meta_tg: {tid} → {list(updates.keys())}")


# ══════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════

async def get_users():
    from utils import ram_cache as ram
    return ram.get_users()


async def save_users(users):
    mark_users_dirty_tg()
    return True


async def save_users_full():
    await _flush_users_list()
    return True


async def _flush_users_list():
    global _users_dirty
    if not ready():
        return
    from utils import ram_cache as ram
    users = ram.get_users()
    if not users:
        return

    rows = []
    for uid_str, data in users.items():
        try:
            tg_id = int(uid_str)
        except (TypeError, ValueError):
            continue
        d = dict(data)
        is_blocked = bool(d.pop("is_blocked", False))
        rows.append({"tg_id": tg_id, "data": d, "is_blocked": is_blocked})

    BATCH = 500
    try:
        for i in range(0, len(rows), BATCH):
            await sb.upsert_many("users", rows[i:i+BATCH], on_conflict="tg_id")
        _users_dirty = False
        log.info(f"Users saqlandi: {len(rows)} ta")
    except Exception as e:
        log.error(f"_flush_users_list: {e}")


# ══════════════════════════════════════════════════════════════
# USER STATS (kim qaysi testni yechgan)
# ══════════════════════════════════════════════════════════════

async def write_user_stats_now(tg_id: int, stats_data: dict) -> bool:
    """
    Bitta foydalanuvchining statistikasini DARHOL Supabase'ga yozadi
    (5 daqiqalik flush kutmasdan). save_result() har test yakunlanganda
    shu funksiyani chaqiradi — shu tufayli bot istalgan payt qayta
    ishga tushsa ham, "kim nechta urinish qildi / eng yaxshi ball /
    o'tdimi" kabi ma'lumotlar hech qachon yo'qolmaydi.
    """
    if not ready():
        return False
    try:
        await sb.upsert("user_stats", {"tg_id": int(tg_id), "data": stats_data},
                         on_conflict="tg_id")
        from utils import ram_cache as ram
        ram.clear_stats_dirty(str(tg_id))
        return True
    except Exception as e:
        log.error(f"write_user_stats_now({tg_id}): {e}")
        return False


async def write_test_stats_now(test_id: str, solve_count: int, avg_score: float) -> bool:
    """Bitta testning solve_count/avg_score'ini darhol yozadi."""
    if not ready():
        return False
    try:
        await sb.update("tests", "test_id", test_id, {
            "solve_count": solve_count,
            "avg_score":   float(avg_score or 0),
        })
        return True
    except Exception as e:
        log.error(f"write_test_stats_now({test_id}): {e}")
        return False


async def write_user_now(tg_id: int, user_data: dict) -> bool:
    """Bitta foydalanuvchi profilini (total_tests, avg_score, ...) darhol yozadi."""
    if not ready():
        return False
    try:
        d = dict(user_data)
        is_blocked = bool(d.pop("is_blocked", False))
        await sb.upsert("users", {"tg_id": int(tg_id), "data": d, "is_blocked": is_blocked},
                         on_conflict="tg_id")
        return True
    except Exception as e:
        log.error(f"write_user_now({tg_id}): {e}")
        return False


async def flush_dirty_user_stats():
    if not ready():
        return
    from utils import ram_cache as ram
    dirty_stats = ram.get_dirty_user_stats()
    if not dirty_stats:
        return

    rows = []
    for uid_str in dirty_stats:
        s = ram.get_user_stats_cache(uid_str)
        if s is None:
            continue
        try:
            tg_id = int(uid_str)
        except (TypeError, ValueError):
            continue
        rows.append({"tg_id": tg_id, "data": s})

    if not rows:
        return
    try:
        await sb.upsert_many("user_stats", rows, on_conflict="tg_id")
        for uid_str in dirty_stats:
            ram.clear_stats_dirty(uid_str)
        log.info(f"User stats saqlandi: {len(rows)} ta")
    except Exception as e:
        log.error(f"flush_dirty_user_stats: {e}")


# ══════════════════════════════════════════════════════════════
# TESTS STATS
# ══════════════════════════════════════════════════════════════

async def save_tests_stats() -> bool:
    global _stats_dirty
    if not ready():
        return False
    from utils import ram_cache as ram

    metas = ram.get_all_tests_meta()
    try:
        for m in metas:
            tid = m.get("test_id", "")
            if not tid:
                continue
            await sb.update("tests", "test_id", tid, {
                "solve_count": m.get("solve_count", 0),
                "avg_score":   float(m.get("avg_score") or 0),
                "is_paused":   m.get("is_paused", False),
                "is_active":   m.get("is_active", True),
            })

        daily = ram.get_daily()
        stat_rows = []
        for uid_str, udata in daily.items():
            try:
                tg_id = int(uid_str)
            except (TypeError, ValueError):
                continue
            stat_rows.append({"tg_id": tg_id, "data": udata})
        if stat_rows:
            for i in range(0, len(stat_rows), 500):
                await sb.upsert_many("user_stats", stat_rows[i:i+500], on_conflict="tg_id")

        _stats_dirty = False
        log.info(f"tests_stats: {len(metas)} test saqlandi")
        return True
    except Exception as e:
        log.error(f"save_tests_stats: {e}")
        return False


async def _load_tests_stats():
    """Bot startida chaqirilardi — endi _load_tests_meta_to_ram bilan
    birlashtirilgan, shu uchun no-op sifatida saqlanadi (moslik uchun)."""
    return


# ══════════════════════════════════════════════════════════════
# LEADERBOARD
# ══════════════════════════════════════════════════════════════

async def save_leaderboard():
    if not ready():
        return False
    try:
        from utils import ram_cache as ram
        data = ram.get_global_leaderboard()
        await sb.upsert("leaderboard", {"scope": "global", "data": data}, on_conflict="scope")
        return True
    except Exception as e:
        log.error(f"save_leaderboard: {e}")
        return False


async def _load_leaderboard():
    if not ready():
        return
    try:
        row = await sb.select_one("leaderboard", "scope", "global")
        if row:
            from utils import ram_cache as ram
            ram.set_global_leaderboard(row.get("data") or [])
    except Exception as e:
        log.error(f"_load_leaderboard: {e}")


async def save_group_leaderboard(chat_id=None, data=None):
    """Guruh leaderboard'i kunlik bo'lib, ram_cache da bitta 'bugungi'
    ro'yxat sifatida saqlanadi. chat_id berilmasa, joriy guruh
    leaderboard'ini scope='group_today' ostida saqlaymiz."""
    if not ready():
        return False
    try:
        from utils import ram_cache as ram
        payload = data if data is not None else ram.get_group_leaderboard()
        scope = f"group_{chat_id}" if chat_id is not None else "group_today"
        await sb.upsert("leaderboard", {"scope": scope, "data": payload}, on_conflict="scope")
        return True
    except Exception as e:
        log.error(f"save_group_leaderboard: {e}")
        return False


async def load_group_leaderboard(chat_id=None):
    if not ready():
        return []
    try:
        scope = f"group_{chat_id}" if chat_id is not None else "group_today"
        row = await sb.select_one("leaderboard", "scope", scope)
        return (row or {}).get("data") or []
    except Exception as e:
        log.error(f"load_group_leaderboard({chat_id}): {e}")
        return []


# ══════════════════════════════════════════════════════════════
# AUTO FLUSH LOOP
# ══════════════════════════════════════════════════════════════

async def auto_flush_loop():
    """Har bir bosqich alohida try/except bilan — bittasi xato bersa
    ham loop davom etadi (crash yo'q, eski xulq-atvor saqlanadi)."""
    await asyncio.sleep(60)
    last_hourly = datetime.now(UTC)

    while True:
        try:
            await asyncio.sleep(300)
            now = datetime.now(UTC)

            try:
                import bot as _bot_mod
                if hasattr(_bot_mod, "_beat"):
                    _bot_mod._beat("auto_flush", "ok")
            except Exception:
                pass

            if _stats_dirty:
                try:
                    await save_tests_stats()
                except Exception as e:
                    log.error(f"auto_flush stats: {e}")

            if _users_dirty:
                try:
                    await _flush_users_list()
                except Exception as e:
                    log.error(f"auto_flush users: {e}")

            if (now - last_hourly).total_seconds() >= 3600:
                last_hourly = now
                log.info("Soatlik flush...")
                for fn in (flush_dirty_user_stats, save_leaderboard,
                           save_group_leaderboard, save_known_groups):
                    try:
                        await fn()
                    except Exception as e:
                        log.error(f"auto_flush hourly {fn.__name__}: {e}")
                log.info("Soatlik flush tugadi")

        except asyncio.CancelledError:
            break
        except Exception as e:
            try:
                import bot as _bot_mod
                if hasattr(_bot_mod, "_beat"):
                    _bot_mod._beat("auto_flush", "error", str(e))
            except Exception:
                pass
            log.error(f"auto_flush_loop: {e}")


# ══════════════════════════════════════════════════════════════
# OTP — Web App login kodlari (RAM, qisqa umrli — DB shart emas)
# ══════════════════════════════════════════════════════════════

def generate_otp(test_id: str, uid: int = 0) -> str:
    import random, string, time
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    _otp_store[code] = {"test_id": test_id, "uid": uid,
                        "expires_at": time.time() + 600, "used": False}
    now = time.time()
    for k in list(_otp_store):
        if _otp_store[k]["expires_at"] < now:
            del _otp_store[k]
    return code


def verify_otp(code: str) -> dict:
    import time
    entry = _otp_store.get(code.upper().strip())
    if not entry:
        return {"ok": False, "error": "Kod topilmadi"}
    if entry["expires_at"] < time.time():
        del _otp_store[code]
        return {"ok": False, "error": "Kod muddati tugagan"}
    if entry["used"]:
        return {"ok": False, "error": "Kod ishlatilgan"}
    entry["used"] = True
    return {"ok": True, "test_id": entry["test_id"], "uid": entry["uid"]}


def get_otp_info(code: str) -> dict:
    import time
    entry = _otp_store.get(code.upper().strip())
    if not entry or entry["expires_at"] < time.time():
        return {}
    return entry


# ══════════════════════════════════════════════════════════════
# WEB SYNC — Supabase'da DEYARLI KERAK EMAS
# ══════════════════════════════════════════════════════════════
# Eski versiyada bot va Telegram Web App ikkita alohida joyga
# (kanal pin xabari) yozardi, shuning uchun har 60 soniyada
# "pin o'zgardimi" deb tekshirish kerak edi.
#
# Endi ikkalasi ham BITTA Postgres bazasiga yozadi — demak
# bot tomoni har doim eng so'nggi holatni to'g'ridan-to'g'ri
# o'qiy oladi. Bu loop endi faqat RAM cache'ni vaqti-vaqti bilan
# yangilab turish uchun qoldirilgan (masalan boshqa joydan —
# web paneldan — qo'shilgan testlar botning RAM cache'iga ham
# kirib kelishi uchun).

async def web_sync_loop():
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.sleep(60)
            if not ready():
                continue
            await _sync_new_tests_from_db()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"web_sync_loop: {e}")
            await asyncio.sleep(60)


async def _sync_new_tests_from_db():
    from utils import ram_cache as ram
    try:
        rows = await sb.select("tests", columns="test_id,title,meta,question_count,"
                                                  "is_active,is_paused,solve_count,avg_score")
    except Exception as e:
        log.error(f"_sync_new_tests_from_db: {e}")
        return

    ram_ids = {t.get("test_id") for t in ram.get_all_tests_meta()}
    added = 0
    for r in rows:
        tid = r["test_id"]
        if tid in ram_ids:
            old_meta = next((m for m in ram.get_all_tests_meta() if m.get("test_id") == tid), {})
            new_qc   = r.get("question_count", 0)
            if old_meta and old_meta.get("question_count", 0) != new_qc:
                _tests_cache.pop(tid, None)
                ram.invalidate_cached_questions(tid)
                meta = dict(r.get("meta") or {})
                meta.update({
                    "test_id": tid, "title": r.get("title", ""),
                    "question_count": new_qc,
                    "is_active": r.get("is_active", True),
                    "is_paused": r.get("is_paused", False),
                })
                ram.update_test_meta(tid, meta)
            continue

        meta = dict(r.get("meta") or {})
        meta.update({
            "test_id":        tid,
            "title":          r.get("title", ""),
            "question_count": r.get("question_count", 0),
            "is_active":      r.get("is_active", True),
            "is_paused":      r.get("is_paused", False),
            "solve_count":    r.get("solve_count", 0),
            "avg_score":      float(r.get("avg_score") or 0),
        })
        ram.add_test_meta(meta)
        added += 1
        if meta.get("source", "") in ("web", "web_split"):
            asyncio.create_task(_notify_web_test(meta, tid))

    if added:
        log.info(f"web_sync: {added} yangi test RAM ga qo'shildi")


_global_bot_ref = None

def set_bot_instance(bot):
    """bot.py main() ichida tg_db.init() orqali avtomatik chaqiriladi —
    notify funksiyalari (_notify_web_test) uchun bot referensi saqlanadi."""
    global _global_bot_ref
    _global_bot_ref = bot


def _get_aiogram_bot():
    return _global_bot_ref


async def get_or_create_bot():
    """
    Streamlit tomoni (alohida prosess/thread) uchun: agar asosiy bot
    instansiyasi shu prosessda mavjud bo'lmasa (masalan Streamlit
    botdan butunlay alohida ishga tushgan bo'lsa), BOT_TOKEN orqali
    vaqtinchalik aiogram.Bot yaratadi. Bu faqat xabar yuborish kabi
    bir martalik amallar uchun ishlatiladi — ma'lumotlar bazasi bilan
    ishlash uchun emas (u Supabase orqali to'g'ridan-to'g'ri amalga
    oshadi).
    """
    if _global_bot_ref:
        return _global_bot_ref
    from config import BOT_TOKEN
    if not BOT_TOKEN:
        return None
    from aiogram import Bot as _BotClass
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    return _BotClass(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


async def _notify_web_test(meta: dict, tid: str):
    """Web orqali yaratilgan test haqida foydalanuvchiga xabar beradi."""
    if not meta.get("creator_id"):
        return
    bot_obj = _get_aiogram_bot()
    if not bot_obj:
        return
    try:
        from keyboards.keyboards import test_created_kb
        bu    = (await bot_obj.get_me()).username
        title = meta.get("title", tid)
        qc    = meta.get("question_count", 0)
        lines = [
            "\u2705 <b>Yangi test saqlandi!</b>",
            "\u2501" * 24,
            "\U0001f4dd <b>" + title + "</b>",
            "\U0001f4cb " + str(qc) + " ta savol | \U0001f194 <code>" + tid + "</code>",
            "",
            "\U0001f447 Boshlash usulini tanlang:",
        ]
        await bot_obj.send_message(
            meta["creator_id"], "\n".join(lines),
            reply_markup=test_created_kb(tid, bu)
        )
        try:
            from utils.baza_publisher import publish_to_baza
            full = await get_test_full(tid)
            if full and full.get("questions"):
                await publish_to_baza(
                    bot=bot_obj, tid=tid, title=meta.get("title", tid),
                    questions=full["questions"],
                    creator_id=int(meta.get("creator_id") or 0),
                    creator_name=meta.get("creator_name", ""),
                    bot_username=bu, category=meta.get("category", ""),
                    difficulty=meta.get("difficulty", "medium"),
                    passing_score=int(meta.get("passing_score") or 60),
                )
        except Exception as _bp:
            log.warning(f"_notify_web_test baza: {_bp}")
    except Exception as e:
        log.warning(f"_notify_web_test {tid}: {e}")


async def _notify_updated_test(meta: dict, tid: str, old_qc: int, new_qc: int):
    bot_obj = _get_aiogram_bot()
    if not bot_obj or not meta.get("creator_id"):
        return
    try:
        diff = new_qc - old_qc
        if diff > 0:
            change = f"\U0001f4c8 +{diff} ta savol qo\u2018shildi"
        elif diff < 0:
            change = f"\U0001f4c9 {abs(diff)} ta savol o\u2018chirildi"
        else:
            change = "\u270f\ufe0f Savol matnlari / javoblari yangilandi"
        NL    = "\n"
        title = meta.get("title", tid)
        txt   = (
            "\u270f\ufe0f <b>Test tahrirlandi!</b>" + NL
            + "\u2501" * 24 + NL
            + "\U0001f4dd <b>" + title + "</b>" + NL
            + "\U0001f194 <code>" + tid + "</code>" + NL + NL
            + change + NL
            + "\U0001f4cb Jami: " + str(new_qc) + " ta savol" + NL + NL
            + "\u2139\ufe0f Yangilangan test keyingi yechishdan kuchga kiradi."
        )
        await bot_obj.send_message(meta["creator_id"], txt)
        log.info(f"_notify_updated_test: {tid} → {meta['creator_id']}")
    except Exception as e:
        log.warning(f"_notify_updated_test {tid}: {e}")


# ══════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════

async def save_settings(settings_dict: dict) -> bool:
    if not ready():
        return False
    try:
        await sb.upsert("app_settings", {"id": 1, "data": settings_dict}, on_conflict="id")
        return True
    except Exception as e:
        log.error(f"save_settings: {e}")
        return False


async def get_settings_tg() -> dict:
    if not ready():
        return {}
    try:
        row = await sb.select_one("app_settings", "id", 1)
        return (row or {}).get("data") or {}
    except Exception as e:
        log.error(f"get_settings_tg: {e}")
        return {}


# ══════════════════════════════════════════════════════════════
# BLOCKED USERS
# ══════════════════════════════════════════════════════════════

async def save_blocked_users(blocked_ids: set) -> bool:
    if not ready():
        return False
    try:
        rows = [{"tg_id": int(uid), "is_blocked": True} for uid in blocked_ids]
        if rows:
            for i in range(0, len(rows), 500):
                await sb.upsert_many("users", rows[i:i+500], on_conflict="tg_id")
        log.info(f"Bloklangan IDlar saqlandi: {len(blocked_ids)} ta")
        return True
    except Exception as e:
        log.error(f"save_blocked_users: {e}")
        return False


async def load_blocked_users() -> set:
    if not ready():
        return set()
    try:
        rows = await sb.select("users", columns="tg_id", filters={"is_blocked": True})
        result = {int(r["tg_id"]) for r in rows}
        log.info(f"Bloklangan IDlar yuklandi: {len(result)} ta")
        return result
    except Exception as e:
        log.error(f"load_blocked_users: {e}")
        return set()


# ══════════════════════════════════════════════════════════════
# KNOWN GROUPS
# ══════════════════════════════════════════════════════════════

async def save_known_groups() -> bool:
    if not ready():
        return False
    from utils import ram_cache as ram
    groups = ram.get_known_groups()
    if not groups:
        return True
    try:
        rows = [{"chat_id": int(cid), "data": gdata} for cid, gdata in groups.items()]
        for i in range(0, len(rows), 500):
            await sb.upsert_many("known_groups", rows[i:i+500], on_conflict="chat_id")
        log.info(f"known_groups saqlandi: {len(groups)} ta")
        return True
    except Exception as e:
        log.error(f"save_known_groups: {e}")
        return False


async def load_known_groups():
    if not ready():
        return
    from utils import ram_cache as ram
    try:
        rows = await sb.select("known_groups")
        groups = {str(r["chat_id"]): dict(r.get("data") or {}) for r in rows}
        if groups:
            ram.set_known_groups(groups)
            log.info(f"known_groups yuklandi: {len(groups)} ta guruh")
    except Exception as e:
        log.error(f"load_known_groups: {e}")


# ══════════════════════════════════════════════════════════════
# BACKUP
# ══════════════════════════════════════════════════════════════

async def upload_backup(daily_data, date_str) -> bool:
    if not ready():
        return False
    try:
        r_count = sum(len(v) for v in daily_data.values() if isinstance(v, dict))
        await sb.upsert("backups", {
            "date_str": date_str,
            "data": {"users": len(daily_data), "results": r_count, "data": daily_data},
        }, on_conflict="date_str")
        log.info(f"Backup: {date_str}")
        return True
    except Exception as e:
        log.error(f"upload_backup: {e}")
        return False


async def get_backup(date_str) -> dict:
    if not ready():
        return {}
    try:
        row = await sb.select_one("backups", "date_str", date_str)
        d = (row or {}).get("data") or {}
        return d.get("data", {})
    except Exception as e:
        log.error(f"get_backup({date_str}): {e}")
        return {}


def get_backup_dates() -> list:
    """Eski versiya sinxron edi — endi bo'sh ro'yxat qaytaradi (moslik uchun).
    Haqiqiy ro'yxat uchun get_backup_dates_async() ishlatilsin."""
    return []


async def get_backup_dates_async() -> list:
    if not ready():
        return []
    try:
        rows = await sb.select("backups", columns="date_str")
        return sorted([r["date_str"] for r in rows], reverse=True)
    except Exception as e:
        log.error(f"get_backup_dates_async: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# MANUAL FLUSH
# ══════════════════════════════════════════════════════════════

async def manual_flush(daily_data, users, settings=None) -> list:
    results = []
    if not ready():
        return ["❌ Supabase ulanmagan"]

    ok = await save_tests_stats()
    results.append(f"{'✅' if ok else '❌'} Tests stats")

    await _flush_users_list()
    results.append(f"✅ Users: {len(users)} ta")

    await flush_dirty_user_stats()
    results.append("✅ User stats")

    await save_leaderboard()
    results.append("✅ Leaderboard")

    if settings:
        ok = await save_settings(settings)
        results.append(f"{'✅' if ok else '❌'} Settings")

    if daily_data:
        today = str(date.today())
        ok = await upload_backup(daily_data, f"{today}_manual")
        results.append(f"{'✅' if ok else '❌'} Backup: {len(daily_data)} user")

    return results


def get_index_info() -> dict:
    from utils import ram_cache as ram
    return {
        "tests_count":  len(ram.get_all_tests_meta()),
        "cached_tests": len(_tests_cache),
        "backend":      "supabase",
        "ready":        _ready,
        "stats_dirty":  _stats_dirty,
        "users_dirty":  _users_dirty,
    }
