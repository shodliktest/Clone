"""
📋 "KIM YECHGAN" — har test uchun JSON Statistika kanalida; Supabase'da faqat INDEKS va META
====================================================================================
• Kanalda: solvers_<test_id>.json — testni boshlagan/yechgan har bir user (bot + web), urinishlar,
  eng yaxshi / o'rtacha foiz, oxirgi vaqt. Har test uchun BITTA xabar (har safar o'sha xabar yangilanadi).
• Supabase'da:
    - test_solvers_index  — test_id → kanal xabari (message_id, file_id) + tezkor sanoqlar
                            (yechganlar soni, urinishlar, o'rtacha foiz, oxirgi vaqt)
    - tests.solve_count / tests.avg_score — test META si, har yangilanishda snapshotdan YANGILANADI
      (bot va web ikkalasining natijalari birga hisoblanadi)
• Manba (xom yozuvlar): bot — user_stats (har user o'z statistikasi), web — results. Snapshot
  ulardan olingan HOSIL ma'lumot: yo'qolsa `/rebuild_solvers` bilan to'liq qayta tiklanadi.
• Yozish: hodisalar 6 soniya yig'iladi (bir test uchun ko'p natija = bitta tahrir), stats_store navbati
  orqali kanal limitiga mos tezlikda yuboriladi. Webdagi natijalar har 90 soniyada o'qib olinadi.
Hamma funksiya xato bersa ham asosiy oqimni BUZMAYDI.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

TABLE       = "test_solvers_index"
SYNC_ROW    = "__web_sync__"
CACHE_TTL   = 120
FLUSH_DELAY = 6
WEB_POLL    = 90

_pending: dict = {}         # tid -> {uid}            (bot hodisalari)
_pending_web: dict = {}     # tid -> {uid: {...}}      (web natijalari)
_scheduled: set = set()
_cache: dict = {}           # tid -> (vaqt, snapshot)
_web_task = None
_last_web_sync = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def active() -> bool:
    """Kanal sozlangan va Supabase tayyor bo'lsa — snapshot rejimi yoqilgan."""
    try:
        from utils import stats_store
        return stats_store.enabled() and stats_store._bot is not None
    except Exception:
        return False


def _title(tid: str) -> str:
    try:
        from utils import ram_cache as ram
        return (ram.get_test_meta(tid) or {}).get("title", "") or ""
    except Exception:
        return ""


def _empty(tid: str) -> dict:
    return {"v": 1, "test_id": tid, "title": _title(tid), "updated_at": _now(), "users": {}}


def _bot_compact(entry: dict) -> dict:
    return {
        "attempts": int(entry.get("attempts", 0)), "best_score": float(entry.get("best_score", 0.0)),
        "avg_score": float(entry.get("avg_score", 0.0)), "last_at": str(entry.get("last_at", "")),
        "passed": bool(entry.get("passed", False)),
        "ever_passed": bool(entry.get("ever_passed", False) or entry.get("passed", False)),
        "pcts": list(entry.get("all_pcts", []))[-10:],
    }


def _web_entry(rows: list, passing: float) -> dict:
    pcts = [float(r.get("percentage") or 0) for r in rows]
    last = max((str(r.get("completed_at") or "") for r in rows), default="")
    return {
        "attempts": len(rows), "best_score": max(pcts) if pcts else 0.0,
        "avg_score": (sum(pcts) / len(pcts)) if pcts else 0.0, "last_at": last[:16].replace("T", " "),
        "passed": bool(pcts and pcts[-1] >= passing), "ever_passed": any(p >= passing for p in pcts),
    }


# ── Hodisalar ───────────────────────────────────────────────
async def record(uid, tid):
    """Bot: user testni boshladi yoki tugatdi → snapshot yangilanishi navbatga qo'yiladi."""
    try:
        if not tid or not active():
            return
        _pending.setdefault(str(tid), set()).add(str(uid))
        _schedule(str(tid))
    except Exception as e:
        log.debug("solvers record: %s", e)


def _schedule(tid: str, delay: float = FLUSH_DELAY):
    if tid in _scheduled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _scheduled.add(tid)

    async def later():
        await asyncio.sleep(delay)
        _scheduled.discard(tid)
        from utils import stats_store
        await stats_store.enqueue_job({"k": "solvers", "tid": tid})
    loop.create_task(later())


# ── Snapshot o'qish / yozish ────────────────────────────────
async def _load(bot, tid: str, use_cache: bool = True):
    from utils import stats_store as ss
    now = time.time()
    hit = _cache.get(tid)
    if use_cache and hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    row = await ss._get_row(TABLE, {"test_id": tid})
    if not row or not row.get("file_id"):
        return None
    try:
        data = await ss._download_json(bot, row["file_id"])
        if str(data.get("test_id")) != str(tid):
            return None
        _cache[tid] = (now, data)
        return data
    except Exception as e:
        log.error("solvers _load(%s): %s", tid, e)
        return None


def _totals(snap: dict) -> dict:
    solvers = attempts = 0
    wsum = 0.0
    last = ""
    for rec in snap.get("users", {}).values():
        n = 0
        for src in ("bot", "web"):
            s = rec.get(src) or {}
            a = int(s.get("attempts", 0))
            n += a
            attempts += a
            wsum += float(s.get("avg_score", 0.0)) * a
            last = max(last, str(s.get("last_at", "")))
        if n > 0 or rec.get("started"):
            solvers += 1
    return {"solver_count": solvers, "attempts_total": attempts,
            "avg_score": round(wsum / attempts, 1) if attempts else 0.0, "last_solved_at": last}


async def save_snapshot(bot, tid: str, snap: dict):
    """Kanalga yozadi, Supabase indeksini va test META sini (solve_count, avg_score) yangilaydi."""
    from utils import stats_store as ss, supabase_client as sb, tg_db, ram_cache as ram
    snap["updated_at"] = _now()
    existing = await ss._get_row(TABLE, {"test_id": tid})
    t = _totals(snap)
    mid, fid = await ss._put_json(bot, existing, f"solvers_{tid}.json", snap,
                                  f"test={tid} | yechganlar={t['solver_count']} | urinish={t['attempts_total']}")
    await sb.upsert(TABLE, {
        "test_id": tid, "message_id": mid, "file_id": fid,
        "solver_count": t["solver_count"], "attempts_total": t["attempts_total"],
        "avg_score": t["avg_score"], "last_solved_at": t["last_solved_at"] or None,
        "updated_at": _now()}, on_conflict="test_id")
    _cache[tid] = (time.time(), snap)
    # META: bot va web natijalari birga hisoblangan to'g'ri qiymatlar (RAM va Supabase `tests` jadvali)
    try:
        ram.update_test_meta(tid, {"solve_count": t["attempts_total"], "avg_score": t["avg_score"]})
        await tg_db.write_test_stats_now(tid, t["attempts_total"], t["avg_score"])
    except Exception as e:
        log.error("solvers meta yozilmadi (%s): %s", tid, e)


def _apply_bot(snap: dict, uid: str, users_ram: dict):
    from utils import ram_cache as ram
    tid = snap["test_id"]
    entry = (ram.get_user_stats_cache(uid) or {}).get(tid)
    if entry is None:
        return
    rec = snap["users"].setdefault(uid, {})
    u = users_ram.get(uid, {})
    rec["name"] = u.get("name") or rec.get("name") or f"User {uid}"
    rec["username"] = u.get("username") or rec.get("username", "")
    rec["bot"] = _bot_compact(entry)
    rec["started"] = True


async def flush_test(bot, tid: str):
    """Navbat vazifasi: shu test uchun yig'ilgan hodisalarni snapshotga qo'shadi va yozadi."""
    from utils import ram_cache as ram
    uids = _pending.pop(tid, set())
    web = _pending_web.pop(tid, {})
    if not uids and not web:
        return
    try:
        snap = await _load(bot, tid)
        if snap is None:
            snap = await _bootstrap(tid)         # birinchi marta: mavjud barcha ma'lumotdan boshlanadi
        users_ram = ram.get_users()
        for uid in uids:
            _apply_bot(snap, uid, users_ram)
        for uid, w in web.items():
            rec = snap["users"].setdefault(uid, {})
            if w.get("name") and not rec.get("name"):
                rec["name"], rec["username"] = w["name"], w.get("username", "")
            rec["web"] = w["entry"]
            rec["started"] = True
        snap["title"] = _title(tid) or snap.get("title", "")
        await save_snapshot(bot, tid, snap)
    except Exception as e:
        # yozilmadi — hodisalar qaytariladi, keyinroq qayta uriniladi
        _pending.setdefault(tid, set()).update(uids)
        for uid, w in web.items():
            _pending_web.setdefault(tid, {})[uid] = w
        from aiogram.exceptions import TelegramRetryAfter
        if isinstance(e, TelegramRetryAfter):
            raise                                  # navbat kutib, shu vazifani qayta bajaradi
        log.error("solvers flush(%s): %s — 60s dan keyin qayta uriniladi", tid, e)
        _schedule(tid, delay=60)


# ── Boshlang'ich yig'ish (xom yozuvlardan) ──────────────────
async def _raw_sources():
    from utils import supabase_client as sb, ram_cache as ram
    us = await sb.select("user_stats", columns="tg_id,data")
    try:
        res = await sb.select("results", columns="user_id,user_name,user_username,test_id,percentage,completed_at")
    except Exception as e:
        log.warning("results o'qilmadi: %s", e)
        res = []
    return us, res


def _build_all(us: list, res: list, only_tid: str = None) -> dict:
    """{tid: snapshot} — user_stats (bot) va results (web) dan."""
    from utils import ram_cache as ram
    users_ram = ram.get_users()
    snaps: dict = {}

    def snap_of(tid):
        if tid not in snaps:
            snaps[tid] = _empty(tid)
        return snaps[tid]

    for row in us:
        uid = str(row.get("tg_id"))
        for tid, entry in (row.get("data") or {}).items():
            if only_tid and str(tid) != str(only_tid):
                continue
            rec = snap_of(str(tid))["users"].setdefault(uid, {})
            u = users_ram.get(uid, {})
            rec["name"] = u.get("name") or f"User {uid}"
            rec["username"] = u.get("username", "")
            rec["bot"] = _bot_compact(ram.normalize_stat_entry(entry))
            rec["started"] = True
    groups: dict = {}
    for r in res:
        tid = str(r.get("test_id"))
        if only_tid and tid != str(only_tid):
            continue
        groups.setdefault((tid, str(r.get("user_id"))), []).append(r)
    for (tid, uid), rows in groups.items():
        ps = float((ram.get_test_meta(tid) or {}).get("passing_score", 60) or 60)
        rec = snap_of(tid)["users"].setdefault(uid, {})
        if not rec.get("name"):
            rec["name"] = (rows[0].get("user_name") or users_ram.get(uid, {}).get("name") or f"User {uid}")
            rec["username"] = rows[0].get("user_username") or users_ram.get(uid, {}).get("username", "")
        rec["web"] = _web_entry(rows, ps)
        rec["started"] = True
    return snaps


async def _bootstrap(tid: str) -> dict:
    us, res = await _raw_sources()
    return _build_all(us, res, only_tid=tid).get(tid) or _empty(tid)


async def rebuild_all(bot) -> int:
    """Admin: barcha testlar snapshotini xom yozuvlardan qayta quradi (navbat orqali). → testlar soni"""
    from utils import stats_store
    us, res = await _raw_sources()
    snaps = _build_all(us, res)
    for tid, snap in snaps.items():
        await stats_store.enqueue_job({"k": "solvers_snap", "tid": tid, "snap": snap})
    return len(snaps)


# ── Webdagi natijalarni o'qib olish ─────────────────────────
async def ingest_web(bot):
    global _last_web_sync
    from utils import stats_store as ss, supabase_client as sb, ram_cache as ram
    if not _last_web_sync:
        row = await ss._get_row(TABLE, {"test_id": SYNC_ROW})
        _last_web_sync = str((row or {}).get("updated_at") or "1970-01-01T00:00:00+00:00")
    since = _last_web_sync

    def _q():
        return (sb.get_client().table("results")
                .select("user_id,user_name,user_username,test_id,percentage,completed_at")
                .gt("completed_at", since).order("completed_at").limit(1000).execute())
    res = await sb._run(_q)
    rows = res.data or []
    if not rows:
        return
    pairs = {}
    for r in rows:
        pairs[(str(r["test_id"]), str(r["user_id"]))] = r
    for (tid, uid), r in pairs.items():
        allrows = await sb.select("results", columns="percentage,completed_at",
                                  filters={"user_id": uid, "test_id": tid})
        ps = float((ram.get_test_meta(tid) or {}).get("passing_score", 60) or 60)
        _pending_web.setdefault(tid, {})[uid] = {
            "name": r.get("user_name") or "", "username": r.get("user_username") or "",
            "entry": _web_entry(allrows, ps)}
        _schedule(tid)
    newest = max(str(r.get("completed_at") or "") for r in rows)
    if newest and newest > _last_web_sync:
        _last_web_sync = newest
        await sb.upsert(TABLE, {"test_id": SYNC_ROW, "updated_at": newest}, on_conflict="test_id")


async def _web_loop(bot):
    await asyncio.sleep(30)
    while True:
        try:
            if active():
                await ingest_web(bot)
        except Exception as e:
            log.error("solvers web ingest: %s", e)
        await asyncio.sleep(WEB_POLL)


def cleanup() -> int:
    """Snapshot keshi: muddati o'tganlari o'chiriladi, eng ko'pi bilan 100 ta test saqlanadi."""
    now = time.time()
    n = 0
    for k in [k for k, (ts, _) in _cache.items() if now - ts > CACHE_TTL * 3]:
        _cache.pop(k, None)
        n += 1
    if len(_cache) > 100:
        for k in sorted(_cache, key=lambda x: _cache[x][0])[:len(_cache) - 100]:
            _cache.pop(k, None)
            n += 1
    return n


def start_background(bot):
    global _web_task
    try:
        if _web_task is None or _web_task.done():
            _web_task = asyncio.get_running_loop().create_task(_web_loop(bot))
    except RuntimeError:
        pass


# ── O'qish: "Kim yechgan" ro'yxati (eski format bilan bir xil) ──
def _to_legacy(uid: str, rec: dict) -> dict:
    b, w = rec.get("bot") or {}, rec.get("web") or {}
    ba, wa = int(b.get("attempts", 0)), int(w.get("attempts", 0))
    att = ba + wa
    avg = ((float(b.get("avg_score", 0)) * ba + float(w.get("avg_score", 0)) * wa) / att) if att else 0.0
    last_b, last_w = str(b.get("last_at", "")), str(w.get("last_at", ""))
    passed = bool(b.get("passed")) if last_b >= last_w else bool(w.get("passed"))
    return {
        "uid": uid, "name": rec.get("name") or f"User {uid}", "username": rec.get("username", ""),
        "attempts": att, "all_pcts": list(b.get("pcts", [])),
        "best_score": max(float(b.get("best_score", 0)), float(w.get("best_score", 0))),
        "avg_score": round(avg, 1), "last_at": max(last_b, last_w),
        "passed": passed, "ever_passed": bool(b.get("ever_passed") or w.get("ever_passed")),
        "ever_completed": att > 0, "started": bool(rec.get("started")) or att > 0,
    }


async def get_solvers(tid: str):
    """Snapshotdan ro'yxat. Snapshot yo'q yoki kanal sozlanmagan bo'lsa → None (eski usul ishlaydi)."""
    try:
        if not active():
            return None
        from utils import stats_store, ram_cache as ram
        snap = await _load(stats_store._bot, str(tid))
        if snap is None:
            return None
        pend = _pending.get(str(tid), set())
        if pend:                                    # hali yozilmagan yangi natijalar ham darhol ko'rinsin
            snap = json.loads(json.dumps(snap))
            users_ram = ram.get_users()
            for uid in pend:
                _apply_bot(snap, uid, users_ram)
        out = [_to_legacy(uid, rec) for uid, rec in snap.get("users", {}).items()]
        out.sort(key=lambda x: (x["attempts"] > 0, x["best_score"]), reverse=True)
        return out
    except Exception as e:
        log.error("solvers get_solvers(%s): %s", tid, e)
        return None
