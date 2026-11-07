"""
📦 STATISTIKA KANALI — xatolar va batafsil tahlil Telegram'da, Supabase'da faqat indeks
======================================================================================
• Test tugagach bot ikkita JSON faylni Statistika kanaliga yozadi:
    1) BATAFSIL TAHLIL  — har (user, test) uchun bitta xabar (qayta yechilsa o'sha xabar yangilanadi)
    2) XATO JAVOBLAR    — har user uchun FAQAT BITTA xabar: oxirgi yechilgan (xatosi bor) test.
                          Yangi testda xato bo'lmasa — eski xatolar ham o'chiriladi.
• Supabase'da faqat ko'rsatkich qatorlari: user_wrong_answers (user_id — yagona kalit)
  va user_analysis (user_id + test_id). Fayl mazmuni Telegram'da.
• Yozish NAVBAT (queue) orqali, kanal limitiga mos tezlikda; RAM faqat 5 daqiqalik tezkor kesh.
• Fayl xabarlari `editMessageMedia` bilan YANGILANADI (o'chirilmaydi) — kanalda xabarlar soni
  userlar/testlar sonidan oshmaydi.
Hamma funksiya xato bersa ham asosiy oqimni BUZMAYDI.
"""
import asyncio
import io
import json
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

WRONG_TABLE = "user_wrong_answers"
ANA_TABLE   = "user_analysis"

CACHE_TTL            = 300     # RAM keshi (soniya) — 5 daqiqa
MAX_ANALYSIS_PER_USER = 30     # har user uchun nechta test tahlili saqlanadi
_SPACING             = 1.6     # kanalga ketma-ket yozish orasidagi pauza (soniya)
_QUEUE_MAX           = 1000

_cache_wrong: dict = {}        # uid -> (vaqt, payload)
_cache_ana: dict = {}          # (uid, tid) -> (vaqt, payload)
_queue = None
_worker_task = None
_warned_disabled = False
_bot = None                    # start da bot.py beradi (navbat vazifalari va "kim yechgan" o'qishi uchun)


def set_bot(bot):
    global _bot
    _bot = bot


# ── Sozlama ─────────────────────────────────────────────────
def channel_id() -> int:
    try:
        from config import STATS_CHANNEL_ID
        return int(STATS_CHANNEL_ID or 0)
    except Exception:
        return 0


def enabled() -> bool:
    global _warned_disabled
    from utils import tg_db
    ok = bool(channel_id()) and tg_db.ready()
    if not channel_id() and not _warned_disabled:
        _warned_disabled = True
        log.warning("STATISTIKA_ID sozlanmagan — xatolar/tahlil kanalga yozilmaydi (faqat RAM)")
    return ok


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Yordamchi: ma'lumot tayyorlash ──────────────────────────
def wrong_indexes(scored: dict) -> list:
    """Javob BERILGAN, lekin noto'g'ri savollar indekslari."""
    out = []
    for r in scored.get("detailed_results", []) or []:
        ua = r.get("user_answer")
        if ua is not None and str(ua).strip() != "" and not r.get("is_correct"):
            out.append(int(r.get("question_index", -1)))
    return [i for i in out if i >= 0]


def attach_question_text(qs: list, scored: dict):
    """
    Tahlil elementlariga savol matnini yozib qo'yadi. Avval tahlil savolni test asl tartibidagi
    ro'yxatdan indeks bilan olardi, savollar esa ARALASHTIRILGAN bo'ladi — shuning uchun
    ba'zan boshqa savol matni ko'rinardi.
    """
    for r in scored.get("detailed_results", []) or []:
        i = r.get("question_index", -1)
        if isinstance(i, int) and 0 <= i < len(qs):
            q = qs[i]
            r["question"] = str(q.get("question", q.get("text", "")))[:600]
            opts = q.get("options")
            if isinstance(opts, list):
                r["options"] = [str(o)[:300] for o in opts][:12]      # webda variantlar bilan ko'rsatish uchun
            if q.get("type"):
                r["type"] = q.get("type")
            if not r.get("explanation"):
                r["explanation"] = q.get("explanation", "")


def _clean_question(q: dict, user_answer=None) -> dict:
    keep = ("question", "text", "type", "options", "correct", "explanation",
            "points", "photo", "image", "accepted_answers")
    d = {k: q[k] for k in keep if k in q}
    if user_answer is not None:
        d["user_answer"] = user_answer
    return d


# ── Supabase indeks (kichik so'rovlar) ──────────────────────
async def _get_row(table: str, key: dict):
    from utils import supabase_client as sb
    try:
        rows = await sb.select(table, filters=key, limit=1)
        return rows[0] if rows else None
    except Exception as e:
        log.error("stats_store _get_row(%s): %s", table, e)
        return None


# ── Kanalga yozish: mavjud xabarni yangilaydi, yo'q bo'lsa yangisini yuboradi ──
async def _put_json(bot, existing, filename: str, payload: dict, caption: str, channel: int = None) -> tuple:
    """→ (message_id, file_id). TelegramRetryAfter yuqoriga ko'tariladi (navbat qayta uradi)."""
    from aiogram.types import BufferedInputFile, InputMediaDocument
    from aiogram.exceptions import TelegramBadRequest
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ch = channel or channel_id()
    mid = (existing or {}).get("message_id")
    if mid:
        try:
            res = await bot.edit_message_media(
                chat_id=ch, message_id=int(mid),
                media=InputMediaDocument(media=BufferedInputFile(raw, filename=filename),
                                         caption=caption))
            doc = getattr(res, "document", None)
            return int(mid), (doc.file_id if doc else (existing or {}).get("file_id"))
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return int(mid), (existing or {}).get("file_id")
            log.warning("kanal xabari yangilanmadi (%s) — yangisi yuboriladi: %s", mid, e)
    sent = await bot.send_document(
        ch, BufferedInputFile(raw, filename=filename), caption=caption,
        disable_notification=True, protect_content=False)
    return sent.message_id, (sent.document.file_id if sent.document else None)


async def _download_json(bot, file_id: str):
    buf = await bot.download(file_id)
    return json.loads(buf.read().decode("utf-8"))


# ── NAVBAT ──────────────────────────────────────────────────
def _ensure_worker():
    global _queue, _worker_task
    if _queue is None:
        _queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.get_running_loop().create_task(_worker())


async def enqueue_job(job: dict):
    """Boshqa modullar (solvers_store) uchun: bot start da berilgan bot orqali navbatga qo'yadi."""
    if _bot is None:
        log.debug("stats_store: bot berilmagan, vazifa tashlandi: %s", job.get("k"))
        return
    await _enqueue(_bot, job)


async def _enqueue(bot, job: dict):
    _ensure_worker()
    job["bot"] = bot
    try:
        _queue.put_nowait(job)
    except asyncio.QueueFull:
        log.error("stats_store navbati to'la — vazifa tashlab yuborildi: %s", job.get("k"))


async def _worker():
    from aiogram.exceptions import TelegramRetryAfter
    while True:
        job = await _queue.get()
        try:
            for attempt in range(4):
                try:
                    await _run_job(job)
                    break
                except TelegramRetryAfter as e:
                    wait = int(getattr(e, "retry_after", 5)) + 1
                    log.warning("stats_store flood: %ss kutamiz", wait)
                    await asyncio.sleep(wait)
                except Exception as e:
                    log.error("stats_store vazifa xato (%s): %s", job.get("k"), e)
                    break
        finally:
            _queue.task_done()
        await asyncio.sleep(_SPACING)


async def _run_job(job: dict):
    k, bot = job["k"], job["bot"]
    if k == "wrong":
        await _do_wrong(bot, job["uid"], job["payload"])
    elif k == "wrong_clear":
        await _do_wrong_clear(bot, job["uid"])
    elif k == "ana":
        await _do_ana(bot, job["uid"], job["payload"])
    elif k == "test_mirror":
        from utils import test_archive
        await test_archive.do_mirror(bot, job["tid"], job.get("test"))
    elif k == "solvers":
        from utils import solvers_store
        await solvers_store.flush_test(bot, job["tid"])
    elif k == "solvers_snap":
        from utils import solvers_store
        await solvers_store.save_snapshot(bot, job["tid"], job["snap"])


# ── XATO JAVOBLAR: har userga bitta qator ───────────────────
async def _do_wrong(bot, uid: int, payload: dict):
    from utils import supabase_client as sb
    existing = await _get_row(WRONG_TABLE, {"user_id": int(uid)})
    mid, fid = await _put_json(bot, existing, f"{uid}_wrong.json", payload,
                               f"uid={uid} | test={payload['test_id']} | xato={len(payload['questions'])}")
    await sb.upsert(WRONG_TABLE, {
        "user_id": int(uid), "test_id": payload["test_id"],
        "title": str(payload.get("title", ""))[:200],
        "message_id": mid, "file_id": fid,
        "wrong_count": len(payload["questions"]), "total": int(payload.get("total", 0)),
        "updated_at": _now()}, on_conflict="user_id")


async def _do_wrong_clear(bot, uid: int):
    """Yangi testda xato yo'q → eski xatolar o'chiriladi (qator qoladi, faylga kirib bo'lmaydi)."""
    from utils import supabase_client as sb
    existing = await _get_row(WRONG_TABLE, {"user_id": int(uid)})
    if not existing or not existing.get("wrong_count"):
        return
    mid = existing.get("message_id")
    if mid:        # kanaldagi eski savollar ham qolib ketmasin — bo'sh fayl bilan almashtiramiz
        try:
            await _put_json(bot, existing, f"{uid}_wrong.json",
                            {"v": 1, "user_id": int(uid), "questions": []}, f"uid={uid} | bo'sh")
        except Exception as e:
            from aiogram.exceptions import TelegramRetryAfter
            if isinstance(e, TelegramRetryAfter):
                raise
            log.debug("bo'sh faylga almashtirilmadi: %s", e)
    await sb.upsert(WRONG_TABLE, {
        "user_id": int(uid), "test_id": None, "title": None, "file_id": None,
        "message_id": mid, "wrong_count": 0, "total": 0, "updated_at": _now()},
        on_conflict="user_id")


async def get_wrong_row(uid: int):
    return await _get_row(WRONG_TABLE, {"user_id": int(uid)})


async def load_wrong(bot, uid: int, tid: str = None):
    """Oxirgi testning xato savollari (RAM 5 daqiqa → keyin kanaldan). Yo'q bo'lsa None."""
    now = time.time()
    hit = _cache_wrong.get(uid)
    if hit and now - hit[0] < CACHE_TTL:
        p = hit[1]
        return p if (not tid or p.get("test_id") == tid) else None
    _cache_wrong.pop(uid, None)
    row = await get_wrong_row(uid)
    if not row or not row.get("file_id") or not row.get("wrong_count"):
        return None
    if tid and row.get("test_id") != tid:
        return None
    try:
        data = await _download_json(bot, row["file_id"])
        if int(data.get("user_id", uid)) != int(uid) or not data.get("questions"):
            return None
        _cache_wrong[uid] = (now, data)
        return data
    except Exception as e:
        log.error("stats_store load_wrong(%s): %s", uid, e)
        return None


# ── BATAFSIL TAHLIL: har (user, test) uchun bitta qator ─────
async def _do_ana(bot, uid: int, payload: dict):
    from utils import supabase_client as sb
    tid = payload["test_id"]
    existing = await _get_row(ANA_TABLE, {"user_id": int(uid), "test_id": tid})
    mid, fid = await _put_json(bot, existing, f"{uid}_{tid}_tahlil.json", payload,
                               f"uid={uid} | test={tid} | {payload.get('percentage', 0)}%")
    await sb.upsert(ANA_TABLE, {
        "user_id": int(uid), "test_id": tid, "result_id": payload.get("result_id"),
        "title": str(payload.get("title", ""))[:200], "message_id": mid, "file_id": fid,
        "correct": int(payload.get("correct", 0)), "total": int(payload.get("total", 0)),
        "percentage": payload.get("percentage", 0), "updated_at": _now()},
        on_conflict="user_id,test_id")
    # Har user uchun oxirgi N ta tahlil qoladi
    try:
        rows = await sb.select(ANA_TABLE, filters={"user_id": int(uid)},
                               order="updated_at", desc=True)
        for r in rows[MAX_ANALYSIS_PER_USER:]:
            await sb.delete_where(ANA_TABLE, {"user_id": int(uid), "test_id": r["test_id"]})
            if r.get("message_id"):
                try:
                    await bot.delete_message(channel_id(), int(r["message_id"]))
                except Exception:
                    pass
    except Exception as e:
        log.debug("tahlil trim: %s", e)


async def load_analysis(bot, uid: int, tid: str):
    """RAM tahlili yo'q bo'lsa (2 soatdan keyin/restart) — kanaldagi JSON dan o'qiydi."""
    now = time.time()
    hit = _cache_ana.get((uid, tid))
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    if not enabled():
        return None
    row = await _get_row(ANA_TABLE, {"user_id": int(uid), "test_id": tid})
    if not row or not row.get("file_id"):
        return None
    try:
        data = await _download_json(bot, row["file_id"])
        if int(data.get("user_id", uid)) != int(uid):
            return None
        _cache_ana[(uid, tid)] = (now, data)
        return data
    except Exception as e:
        log.error("stats_store load_analysis(%s,%s): %s", uid, tid, e)
        return None


# ── RAM tozalash (bot.py dagi 15 daqiqalik _cache_cleanup_loop chaqiradi) ──
def cleanup() -> int:
    """Muddati o'tgan keshlarni o'chiradi (aks holda ular sekin-asta RAM ni to'ldirardi) va hajmini cheklaydi."""
    now = time.time()
    n = 0
    for cache in (_cache_wrong, _cache_ana):
        for k in [k for k, (ts, _) in cache.items() if now - ts > CACHE_TTL]:
            cache.pop(k, None)
            n += 1
        if len(cache) > 500:                                   # qattiq chegara
            for k in sorted(cache, key=lambda x: cache[x][0])[:len(cache) - 500]:
                cache.pop(k, None)
                n += 1
    return n


# ── Chaqiriladigan joylar ───────────────────────────────────
async def on_test_finished(bot, uid: int, test: dict, qs: list, scored: dict, rid):
    """Test tugagach: tahlil + xatolarni navbatga qo'yadi (tez, kanalga yozishni kutmaydi)."""
    try:
        tid = str(test.get("test_id") or "")
        if not tid or test.get("is_retry") or scored.get("demo") or not enabled():
            return
        det = scored.get("detailed_results", []) or []
        title = test.get("title", tid)
        ana = {
            "v": 1, "user_id": int(uid), "test_id": tid, "title": title, "result_id": rid,
            "saved_at": _now(), "percentage": scored.get("percentage", 0),
            "correct": scored.get("correct_count", 0), "total": len(det),
            "time_spent": scored.get("time_spent", 0), "mode": scored.get("mode", ""),
            "detailed": det,
        }
        await _enqueue(bot, {"k": "ana", "uid": int(uid), "payload": ana})

        idxs = wrong_indexes(scored)
        if idxs:
            by_i = {int(r["question_index"]): r for r in det}
            questions = [_clean_question(qs[i], by_i.get(i, {}).get("user_answer"))
                         for i in idxs if i < len(qs)]
            payload = {"v": 1, "user_id": int(uid), "test_id": tid, "title": title,
                       "saved_at": _now(), "percentage": scored.get("percentage", 0),
                       "total": len(qs), "poll_time": int(test.get("poll_time", 30) or 30),
                       "questions": questions}
            _cache_wrong[int(uid)] = (time.time(), payload)
            await _enqueue(bot, {"k": "wrong", "uid": int(uid), "payload": payload})
        else:
            _cache_wrong.pop(int(uid), None)
            await _enqueue(bot, {"k": "wrong_clear", "uid": int(uid)})
    except Exception as e:
        log.error("stats_store on_test_finished uid=%s: %s", uid, e)


async def on_retry_finished(bot, uid: int, orig_tid: str, title: str, total: int,
                            poll_time: int, remaining: list):
    """Xatolar qayta yechilgach: qolganlarini yangilaydi, qolmasa tozalaydi."""
    try:
        if not enabled():
            return
        if remaining:
            payload = {"v": 1, "user_id": int(uid), "test_id": orig_tid, "title": title,
                       "saved_at": _now(), "total": int(total), "poll_time": int(poll_time),
                       "questions": [_clean_question(q) for q in remaining]}
            _cache_wrong[int(uid)] = (time.time(), payload)
            await _enqueue(bot, {"k": "wrong", "uid": int(uid), "payload": payload})
        else:
            _cache_wrong.pop(int(uid), None)
            await _enqueue(bot, {"k": "wrong_clear", "uid": int(uid)})
    except Exception as e:
        log.error("stats_store on_retry_finished uid=%s: %s", uid, e)
