"""
🗄 TESTLAR ARXIVI — savollar Telegram "Testlar" kanalida, Supabase'da faqat INDEKS + META
======================================================================================
• Har test yaratilganda/tahrirlanganda to'liq JSON (meta + savollar) Testlar kanaliga yoziladi
  (test_<id>.json, har test uchun BITTA xabar, tahrirlansa o'sha xabar yangilanadi).
• 14 kun (ARCHIVE_AFTER_DAYS) hech kim ochmagan/yechmagan test Supabase'dan "sovutiladi":
  `tests.questions` bo'shatiladi, lekin QATOR, test_id, title, question_count, solve_count,
  avg_score va barcha meta SAQLANADI (inline qidiruv, ro'yxatlar, statistika buzilmaydi).
• Sovutilgan testga qayta murojaat bo'lsa (bot yoki web) — kanaldagi JSON dan o'qilib,
  Supabase'ga QAYTARILADI (va RAM ga olinadi); test yana 14 kun "issiq" qoladi.
• XAVFSIZLIK: savollar Supabase'dan faqat kanal fayli yuklab olinib, o'qib TEKSHIRILGANDAN
  (savollar soni mos) keyingina o'chiriladi. Kanal xato bersa — hech narsa o'chirilmaydi.
• Indeks jadvali: test_archive_index (test_id → message_id, file_id, savollar soni, vaqtlar, holat).
Hamma funksiya xato bersa ham asosiy oqimni BUZMAYDI.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

TABLE         = "test_archive_index"
TOUCH_EVERY   = 6 * 3600        # "oxirgi murojaat" Supabase'ga ko'pi bilan 6 soatda bir yoziladi
SCAN_EVERY    = 600             # yangi/o'zgargan testlarni kanalga yozish uchun skan (soniya)
SWEEP_EVERY   = 6 * 3600        # sovutish tekshiruvi
MAX_MIRRORS_PER_SCAN = 40
MAX_FILE_BYTES = 19 * 1024 * 1024   # Telegram yuklab olish chegarasi (20 MB) dan past

_touch_ts: dict = {}
_restoring: dict = {}           # tid -> asyncio.Future (bir vaqtda ikki marta tiklamaslik)
_bg_task = None
_flags_task = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt=None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _parse(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00").replace(" ", "T")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def channel_id() -> int:
    try:
        from config import TESTS_CHANNEL_ID
        return int(TESTS_CHANNEL_ID or 0)
    except Exception:
        return 0


def archive_days() -> int:
    try:
        from config import ARCHIVE_AFTER_DAYS
        return max(1, int(ARCHIVE_AFTER_DAYS or 14))
    except Exception:
        return 14


def enabled() -> bool:
    try:
        from utils import tg_db, stats_store
        return bool(channel_id()) and tg_db.ready() and stats_store._bot is not None
    except Exception:
        return False


async def _row(tid: str):
    from utils import supabase_client as sb
    try:
        rows = await sb.select(TABLE, filters={"test_id": tid}, limit=1)
        return rows[0] if rows else None
    except Exception as e:
        log.error("test_archive _row(%s): %s", tid, e)
        return None


async def _download(bot, file_id: str):
    from utils import stats_store as ss
    return await ss._download_json(bot, file_id)


# ── Murojaat vaqtini qayd etish ─────────────────────────────
def touch(tid: str):
    """Test ochildi/yechildi. Supabase'ga ko'pi bilan 6 soatda bir marta yoziladi (throttle)."""
    try:
        if not tid or not channel_id():
            return
        now = time.time()
        if now - _touch_ts.get(tid, 0) < TOUCH_EVERY:
            return
        _touch_ts[tid] = now
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _go():
        try:
            from utils import supabase_client as sb
            await sb.upsert(TABLE, {"test_id": tid, "last_access_at": _iso()}, on_conflict="test_id")
        except Exception as e:
            log.debug("test_archive touch(%s): %s", tid, e)
    loop.create_task(_go())


# ── Kanalga yozish (nusxa) ──────────────────────────────────
async def on_saved(test: dict):
    """Test yaratildi/tahrirlandi (bot). Kanalga yozish navbatga qo'yiladi."""
    try:
        tid = str((test or {}).get("test_id") or "")
        if not tid or not enabled():
            return
        from utils import stats_store
        await stats_store.enqueue_job({"k": "test_mirror", "tid": tid, "test": test})
    except Exception as e:
        log.error("test_archive on_saved: %s", e)


async def _load_full(tid: str):
    from utils import supabase_client as sb
    row = await sb.select_one("tests", "test_id", tid)
    if not row:
        return None
    full = dict(row.get("meta") or {})
    full["test_id"] = row["test_id"]
    full["title"] = row.get("title", full.get("title", ""))
    full["questions"] = row.get("questions") or []
    return full


async def do_mirror(bot, tid: str, test: dict = None):
    """Navbat vazifasi: testni kanalga yozadi (yoki mavjud xabarni yangilaydi) va indeksni yangilaydi."""
    from utils import stats_store as ss, supabase_client as sb
    test = test or await _load_full(tid)
    if not test or not test.get("questions"):
        return                                  # savollar yo'q (sovutilgan yoki bo'sh) — nusxalanmaydi
    payload = {"v": 1, "test_id": tid, "saved_at": _iso(),
               "question_count": len(test["questions"]), "test": test}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_FILE_BYTES:
        log.error("test_archive: %s juda katta (%.1f MB) — kanalga yozilmadi, Supabase'da qoladi", tid, len(raw) / 1e6)
        return
    existing = await _row(tid)
    mid, fid = await ss._put_json(bot, existing, f"test_{tid}.json", payload,
                                  f"test={tid} | savol={payload['question_count']}", channel=channel_id())
    await sb.upsert(TABLE, {
        "test_id": tid, "message_id": mid, "file_id": fid,
        "question_count": payload["question_count"], "size_bytes": len(raw),
        "saved_at": payload["saved_at"], "archived": False,
        "last_access_at": (existing or {}).get("last_access_at") or _iso()}, on_conflict="test_id")


async def scan_mirror(bot, limit: int = MAX_MIRRORS_PER_SCAN) -> dict:
    """Kanalda yo'q yoki o'zgargan testlarni topib, navbatga qo'yadi (mavjud testlarni ham o'z-o'zidan yig'adi)."""
    from utils import supabase_client as sb, stats_store
    tests = await sb.select("tests", columns="test_id,updated_at,question_count")
    idx = {r["test_id"]: r for r in await sb.select(TABLE)}
    need = []
    for t in tests:
        tid = t["test_id"]
        if int(t.get("question_count") or 0) <= 0:
            continue
        r = idx.get(tid)
        if r is None or not r.get("file_id"):
            need.append(tid)
        elif not r.get("archived"):
            upd, saved = _parse(t.get("updated_at")), _parse(r.get("saved_at"))
            if upd and (saved is None or upd > saved + timedelta(seconds=5)):
                need.append(tid)
    queued = 0
    for tid in need[:limit]:
        await stats_store.enqueue_job({"k": "test_mirror", "tid": tid})
        queued += 1
    return {"total": len(tests), "need": len(need), "queued": queued}


# ── Sovutish (Supabase'dan savollarni olib tashlash) ────────
async def sweep(bot, days: int = None, dry: bool = False) -> dict:
    """`days` kundan beri murojaat bo'lmagan testlarni sovutadi. Faqat kanal fayli TEKSHIRILGANDAN keyin."""
    from utils import supabase_client as sb, stats_store
    days = days or archive_days()
    cutoff = _now() - timedelta(days=days)
    tests = {t["test_id"]: t for t in await sb.select("tests", columns="test_id,updated_at,question_count")}
    if not tests:
        return {"error": "tests jadvali bo'sh yoki o'qilmadi", "archived": 0}
    rows = [r for r in await sb.select(TABLE) if not r.get("archived") and r.get("file_id")]
    res = {"candidates": 0, "archived": 0, "remirror": 0, "skipped": 0, "freed_bytes": 0, "days": days}
    for r in rows:
        tid = r["test_id"]
        la = _parse(r.get("last_access_at"))
        t = tests.get(tid)
        if not t or la is None or la >= cutoff:
            continue
        res["candidates"] += 1
        upd, saved = _parse(t.get("updated_at")), _parse(r.get("saved_at"))
        if upd and (saved is None or upd > saved + timedelta(seconds=5)):
            res["remirror"] += 1                    # kanaldagi nusxa eskirgan — avval yangilanadi
            if not dry:
                await stats_store.enqueue_job({"k": "test_mirror", "tid": tid})
            continue
        if dry:
            res["freed_bytes"] += int(r.get("size_bytes") or 0)
            continue
        try:
            data = await _download(bot, r["file_id"])
            qs = ((data or {}).get("test") or {}).get("questions") or []
            if str((data or {}).get("test_id")) != str(tid) or not qs or len(qs) != int(t.get("question_count") or 0):
                log.error("test_archive sweep: %s fayli mos emas (kanal %s, bazada %s) — o'chirilmadi",
                          tid, len(qs), t.get("question_count"))
                res["skipped"] += 1
                continue
            await sb.upsert(TABLE, {"test_id": tid, "archived": True, "archived_at": _iso()}, on_conflict="test_id")
            try:
                await sb.upsert("tests", {"test_id": tid, "questions": []}, on_conflict="test_id")
            except Exception:
                await sb.upsert(TABLE, {"test_id": tid, "archived": False}, on_conflict="test_id")   # qaytaramiz
                raise
            _forget_ram(tid)
            res["archived"] += 1
            res["freed_bytes"] += int(r.get("size_bytes") or 0)
        except Exception as e:
            log.error("test_archive sweep(%s): %s", tid, e)
            res["skipped"] += 1
    return res


def _forget_ram(tid: str):
    try:
        from utils import tg_db
        tg_db._tests_cache.pop(tid, None)
    except Exception:
        pass


# ── Tiklash (sovutilgan testga murojaat) ────────────────────
async def restore(tid: str):
    """Kanaldagi JSON dan testni o'qib, Supabase'ga qaytaradi. → to'liq test dict yoki None."""
    fut = _restoring.get(tid)
    if fut is not None:
        return await fut                       # boshqa murojaat allaqachon tiklayapti
    from utils import stats_store, supabase_client as sb
    bot = stats_store._bot
    if bot is None:
        return None
    fut = asyncio.get_running_loop().create_future()
    _restoring[tid] = fut
    result = None
    try:
        r = await _row(tid)
        if not r or not r.get("file_id"):
            log.error("test_archive restore(%s): indeksda fayl yo'q", tid)
        else:
            data = await _download(bot, r["file_id"])
            t = (data or {}).get("test") or {}
            qs = t.get("questions") or []
            if str((data or {}).get("test_id")) == str(tid) and qs:
                await sb.upsert("tests", {"test_id": tid, "questions": qs,
                                          "question_count": len(qs)}, on_conflict="test_id")
                await sb.upsert(TABLE, {"test_id": tid, "archived": False,
                                        "last_access_at": _iso(), "saved_at": _iso()}, on_conflict="test_id")
                result = t
                log.info("test_archive: %s kanaldan tiklandi (%d savol)", tid, len(qs))
            else:
                log.error("test_archive restore(%s): fayl noto'g'ri", tid)
    except Exception as e:
        log.error("test_archive restore(%s): %s", tid, e)
    finally:
        fut.set_result(result)
        _restoring.pop(tid, None)
    return result


async def status() -> dict:
    from utils import supabase_client as sb
    tests = await sb.select("tests", columns="test_id,question_count")
    idx = await sb.select(TABLE)
    arch = [r for r in idx if r.get("archived")]
    cutoff = _now() - timedelta(days=archive_days())
    stale = [r for r in idx if not r.get("archived") and r.get("file_id")
             and (_parse(r.get("last_access_at")) or _now()) < cutoff]
    return {"tests": len(tests), "mirrored": len([r for r in idx if r.get("file_id")]),
            "archived": len(arch), "stale_candidates": len(stale), "days": archive_days(),
            "archived_mb": round(sum(int(r.get("size_bytes") or 0) for r in arch) / 1e6, 2),
            "channel": bool(channel_id())}


def cleanup() -> int:
    """`touch` throttle belgilari: muddati o'tganlari o'chiriladi."""
    now = time.time()
    dead = [k for k, ts in _touch_ts.items() if now - ts > TOUCH_EVERY]
    for k in dead:
        _touch_ts.pop(k, None)
    return len(dead)


# ── Fon vazifasi ────────────────────────────────────────────
async def _loop(bot):
    await asyncio.sleep(60)
    last_sweep = 0.0
    while True:
        try:
            if enabled():
                await scan_mirror(bot)
                if time.time() - last_sweep >= SWEEP_EVERY:
                    last_sweep = time.time()
                    r = await sweep(bot)
                    if r.get("archived"):
                        log.info("test_archive sweep: %s", r)
        except Exception as e:
            log.error("test_archive loop: %s", e)
        await asyncio.sleep(SCAN_EVERY)


def start_background(bot):
    global _bg_task, _flags_task
    try:
        loop = asyncio.get_running_loop()
        if _bg_task is None or _bg_task.done():
            _bg_task = loop.create_task(_loop(bot))
        if _flags_task is None or _flags_task.done():
            _flags_task = loop.create_task(_flags_loop())
    except RuntimeError:
        pass


# ── O'CHIRISH BELGISINI SINXRONLASH (web'dan o'chirilgan testlar botda tezda yo'qolsin) ──
FLAGS_EVERY = 120          # soniya

async def sync_deleted_flags() -> int:
    """Supabase'dagi meta.is_deleted / is_active ni RAM ga o'tkazadi (faqat belgilar, savollar emas).
    Web'da egasi o'chirgan test 2 daqiqa ichida botda ham yashiriladi. → o'zgargan testlar soni."""
    from utils import supabase_client as sb, ram_cache as ram
    rows = await sb.select("tests", columns="test_id,meta,is_active")
    changed = 0
    for r in rows or []:
        tid = r.get("test_id")
        meta = r.get("meta") or {}
        cur = ram.get_test_meta_any(tid) or {}
        want_deleted = bool(meta.get("is_deleted", False))
        want_active = bool(r.get("is_active", True))
        if cur and (bool(cur.get("is_deleted", False)) != want_deleted
                    or bool(cur.get("is_active", True)) != want_active):
            ram.update_test_meta(tid, {"is_deleted": want_deleted, "is_active": want_active})
            changed += 1
    return changed


async def _flags_loop():
    await asyncio.sleep(90)
    while True:
        try:
            if enabled():
                n = await sync_deleted_flags()
                if n:
                    log.info("test_archive: %d ta test belgisi yangilandi (web)", n)
        except Exception as e:
            log.debug("test_archive flags: %s", e)
        await asyncio.sleep(FLAGS_EVERY)
