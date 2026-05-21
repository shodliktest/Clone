"""
RAM CACHE — Mukammal arxitektura

FAYLLAR (TG kanalda):
  index.json              ← pinned, barcha meta
  users_list_N.json       ← 10MB gacha, uid+ism+role (lazy load emas, startup da)
  user_stats_N.json       ← 50 userdan stats (1 soatda o'zgarganlar)
  user_analysis_{uid}.json← max 30 test tahlil (lazy, 2 soat TTL RAMda)
  leaderboard.json        ← global top 20 (1 soatda)
  group_lb_{date}.json    ← guruh top 20, kunlik (1 soatda)
  tests_stats.json        ← test meta stats (2 daqiqada)

RAM QOIDALARI:
  - Users ro'yxati: doim RAM (kichik)
  - User stats: lazy (kimdir kirsa yuklanadi, 2 soat TTL)
  - User tahlil: lazy (test yechilsa, 2 soat TTL)
  - Guruh natijalari: e'lon qilingach darhol o'chadi
  - Test savollari: 48 soat TTL
  - Global leaderboard: startup da yuklanadi
"""
import threading, logging, sys
from datetime import datetime, timezone, timedelta

log  = logging.getLogger(__name__)
UTC  = timezone.utc
_lck = threading.Lock()
_RAM: dict = {}

RAM_LIMIT       = 450 * 1024 * 1024
ANALYSIS_TTL_H  = 2    # 2 soat
STATS_TTL_H     = 2    # 2 soat (user stats RAMda)
CACHE_TTL_HOURS = 48   # test savollari

DEFAULT_SETTINGS = "uz_1_1"
LANGS   = ["uz", "ru", "en"]
THEMES  = ["light", "dark"]
NOTIFS  = ["off", "on"]

MAX_ANALYSIS_PER_USER = 30   # Max 30 test tahlil per user


def _get(k, d=None):
    with _lck: return _RAM.get(k, d)

def _set(k, v):
    with _lck: _RAM[k] = v

def _pop(k):
    with _lck: return _RAM.pop(k, None)


# ══ SETTINGS ══════════════════════════════════════════════════

def decode_settings(code):
    try:
        p = (code or DEFAULT_SETTINGS).split("_")
        lang   = p[0] if p[0] in LANGS else "uz"
        theme  = int(p[1]) if len(p) > 1 else 1
        notify = int(p[2]) if len(p) > 2 else 1
        return {
            "lang":   lang,
            "theme":  THEMES[min(theme, 1)],
            "notify": NOTIFS[min(notify, 1)],
        }
    except Exception:
        return {"lang": "uz", "theme": "dark", "notify": "on"}

def get_settings(uid):
    return decode_settings(_get("settings", {}).get(str(uid), DEFAULT_SETTINGS))

def set_settings(uid, lang=None, theme=None, notify=None):
    s   = _get("settings", {})
    cur = decode_settings(s.get(str(uid), DEFAULT_SETTINGS))
    l   = lang   if lang   is not None else cur["lang"]
    t   = theme  if theme  is not None else THEMES.index(cur["theme"])
    n   = notify if notify is not None else NOTIFS.index(cur["notify"])
    s[str(uid)] = f"{l}_{t}_{n}"
    _set("settings", s)

def get_all_settings():  return _get("settings", {})
def set_all_settings(d): _set("settings", d)


# ══ TEST META ══════════════════════════════════════════════════

def get_tests_meta():
    return [t for t in _get("tests_meta", []) if t.get("is_active", True)]

def get_all_tests_meta():
    return _get("tests_meta", [])

def set_tests_meta(m):
    _set("tests_meta", m)

def get_test_meta(tid):
    return next((t for t in _get("tests_meta", [])
                 if t.get("test_id") == tid), {})

def add_test_meta(meta):
    m = [x for x in _get("tests_meta", []) if x.get("test_id") != meta.get("test_id")]
    m.insert(0, meta)
    _set("tests_meta", m)

def update_test_meta(tid, updates):
    m = _get("tests_meta", [])
    for i, t in enumerate(m):
        if t.get("test_id") == tid:
            m[i].update(updates)
            break
    _set("tests_meta", m)

def delete_test_from_ram(tid):
    m = [t for t in _get("tests_meta", []) if t.get("test_id") != tid]
    _set("tests_meta", m)
    _pop(f"qcache_{tid}")
    log.info(f"RAM: test_{tid} o'chirildi")

def pause_test(tid, paused: bool):
    update_test_meta(tid, {"is_paused": paused})

def is_test_paused(tid):
    return get_test_meta(tid).get("is_paused", False)

def get_tests():       return get_tests_meta()
def get_test_by_id(tid):
    meta = get_test_meta(tid)
    if meta and not meta.get("is_active", True):
        return {}
    full = get_cached_questions(tid)
    if full is not None:
        return full
    return meta or {}

def set_tests(tests):
    metas = []
    for t in tests:
        meta = {k: v for k, v in t.items() if k != "questions"}
        meta["question_count"] = len(t.get("questions", []))
        metas.append(meta)
        if t.get("is_active", True) and t.get("questions"):
            cache_questions(t["test_id"], t)
    _set("tests_meta", metas)

def add_test(test):
    meta = {k: v for k, v in test.items() if k != "questions"}
    meta["question_count"] = len(test.get("questions", []))
    add_test_meta(meta)
    if test.get("questions"):
        cache_questions(test["test_id"], test)

def update_test_meta_full(test):
    tid  = test.get("test_id")
    meta = {k: v for k, v in test.items() if k != "questions"}
    update_test_meta(tid, meta)

def refresh_tests():
    _set("tests_meta", [])


# ══ SAVOLLAR CACHE (48 soat) ═══════════════════════════════════

def cache_questions(tid, test_full):
    now = datetime.now(UTC)
    _set(f"qcache_{tid}", {
        "test":        test_full,
        "loaded_at":   now,
        "last_access": now,
    })

def get_cached_questions(tid):
    e = _get(f"qcache_{tid}")
    if not e: return None
    e["last_access"] = datetime.now(UTC)
    _set(f"qcache_{tid}", e)
    return e["test"]

def touch_test_access(tid):
    e = _get(f"qcache_{tid}")
    if e:
        e["last_access"] = datetime.now(UTC)
        _set(f"qcache_{tid}", e)

def clear_expired_cache():
    now      = datetime.now(UTC)
    deadline = now - timedelta(hours=CACHE_TTL_HOURS)
    removed  = []
    with _lck:
        keys = [k for k in list(_RAM)
                if k.startswith("qcache_")
                and _RAM[k].get("last_access", now) < deadline]
        for k in keys:
            del _RAM[k]
            removed.append(k.replace("qcache_", ""))
    if removed:
        log.info(f"RAM: {len(removed)} test qcache o'chirildi")
    return removed

def get_cache_stats():
    now   = datetime.now(UTC)
    items = []
    with _lck:
        for k, v in _RAM.items():
            if not k.startswith("qcache_"): continue
            tid = k.replace("qcache_", "")
            la  = v.get("last_access", now)
            ago = int((now - la).total_seconds() / 3600)
            items.append({"tid": tid, "last_access_hours_ago": ago})
    return items


# ══ USERLAR ════════════════════════════════════════════════════

def get_users():         return _get("users_cache", {})
def set_users(u):        _set("users_cache", u)
def get_user(tg_id):     return get_users().get(str(tg_id))

def upsert_user(tg_id, data):
    u = get_users()
    u[str(tg_id)] = data
    set_users(u)
    _set("users_dirty", True)

def is_users_dirty():    return _get("users_dirty", False)
def mark_users_dirty():  _set("users_dirty", True)
def clear_users_dirty(): _set("users_dirty", False)


# ══ USER STATS (lazy, 2 soat TTL) ══════════════════════════════
#
# stats_{uid} = {
#   "data": {tid: {attempts, all_pcts, best_score, avg_score, last_at, passed}},
#   "loaded_at": datetime,
#   "dirty": bool,   ← o'zgardimi
# }

def _stats_key(uid): return f"stats_{uid}"

def get_user_stats_cache(uid):
    """User stats RAMda bormi — bor bo'lsa qaytaradi"""
    e = _get(_stats_key(str(uid)))
    if not e: return None
    e["last_access"] = datetime.now(UTC)
    _set(_stats_key(str(uid)), e)
    return e.get("data", {})

def set_user_stats_cache(uid, data, dirty=False):
    """User stats ni RAMga yozish"""
    _set(_stats_key(str(uid)), {
        "data":        data,
        "loaded_at":   datetime.now(UTC),
        "last_access": datetime.now(UTC),
        "dirty":       dirty,
    })

def mark_user_stats_dirty(uid):
    e = _get(_stats_key(str(uid)))
    if e:
        e["dirty"] = True
        _set(_stats_key(str(uid)), e)

def get_dirty_user_stats():
    """O'zgargan user stats larni qaytaradi → TG ga yozish uchun"""
    result = {}
    with _lck:
        for k, v in _RAM.items():
            if not k.startswith("stats_"): continue
            if v.get("dirty"):
                uid = k[6:]
                result[uid] = v.get("data", {})
    return result

def clear_stats_dirty(uid):
    e = _get(_stats_key(str(uid)))
    if e:
        e["dirty"] = False
        _set(_stats_key(str(uid)), e)

def clear_expired_stats():
    """2 soat ishlatilmagan user stats larni RAMdan o'chirish"""
    now      = datetime.now(UTC)
    deadline = now - timedelta(hours=STATS_TTL_H)
    removed  = 0
    with _lck:
        keys = [k for k in list(_RAM)
                if k.startswith("stats_")
                and not _RAM[k].get("dirty", False)
                and _RAM[k].get("last_access", now) < deadline]
        for k in keys:
            del _RAM[k]
            removed += 1
    if removed:
        log.info(f"RAM: {removed} user stats o'chirildi (2 soat TTL)")
    return removed


# ══ NATIJALAR ══════════════════════════════════════════════════

def save_result_to_ram(user_id, test_id, result, via_link=False):
    """
    Natijani RAMga saqlash.
    - Stats (foiz, attempts): doim RAM, TG ga 1 soatda
    - Tahlil: 2 soat TTL, max 30 test
    """
    uid_str = str(user_id)
    rid     = f"{uid_str}_{test_id}"
    now_str = str(datetime.now(UTC))[:16]

    # ── Stats (lazy cache) ──
    stats = get_user_stats_cache(uid_str) or {}
    e     = stats.get(test_id, {
        "attempts":   0,
        "all_pcts":   [],
        "best_score": 0.0,
        "avg_score":  0.0,
        "last_at":    now_str,
        "passed":     False,
    })
    pct   = float(result.get("percentage", 0))
    att   = e["attempts"] + 1
    all_p = e["all_pcts"] + [pct]
    best  = max(e["best_score"], pct)
    avg   = round(sum(all_p) / len(all_p), 1)
    ps    = float(result.get("passing_score", 60))

    stats[test_id] = {
        "attempts":   att,
        "all_pcts":   all_p,
        "best_score": best,
        "avg_score":  avg,
        "last_at":    now_str,
        "passed":     pct >= ps,
    }
    set_user_stats_cache(uid_str, stats, dirty=True)

    # ── Tahlil (2 soat TTL, max 30) ──
    ana_key  = f"analysis_{uid_str}"
    analyses = _get(ana_key, {})

    # Max 30 — eng eskisini o'chirish
    if test_id not in analyses and len(analyses) >= MAX_ANALYSIS_PER_USER:
        oldest = min(analyses.items(), key=lambda x: x[1].get("saved_at_ts", 0))
        analyses.pop(oldest[0], None)

    analyses[test_id] = {
        "data":        result.get("detailed_results", []),
        "last_result": {
            **result,
            "result_id":    rid,
            "test_id":      test_id,
            "user_id":      user_id,
            "attempt_num":  att,
            "completed_at": now_str,
        },
        "saved_at":    now_str,
        "saved_at_ts": datetime.now(UTC).timestamp(),
    }
    _set(ana_key, analyses)
    _set(f"ana_access_{uid_str}", datetime.now(UTC))

    _set("users_dirty", True)
    return rid

def get_user_results(uid):
    """History ro'yxati — user stats dan"""
    stats   = get_user_stats_cache(str(uid)) or {}
    history = []
    for tid, e in stats.items():
        history.append({
            "test_id":      tid,
            "result_id":    f"{uid}_{tid}",
            "last_pct":     e["all_pcts"][-1] if e["all_pcts"] else 0,
            "best_pct":     e["best_score"],
            "attempts":     e["attempts"],
            "all_pcts":     e["all_pcts"],
            "passed":       e["passed"],
            "completed_at": e["last_at"],
        })
    history.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
    return history

def get_test_entry(uid, tid):
    stats = get_user_stats_cache(str(uid)) or {}
    return stats.get(tid, {})

def get_user_stat(uid, tid):
    return get_test_entry(uid, tid)

def get_all_user_stats(uid):
    return get_user_stats_cache(str(uid)) or {}

def get_analysis(uid, rid):
    parts = str(rid).split("_", 1)
    if len(parts) < 2: return []
    tid      = parts[1]
    analyses = _get(f"analysis_{uid}", {})
    return analyses.get(tid, {}).get("data", [])

def get_last_result(uid, tid):
    analyses = _get(f"analysis_{uid}", {})
    return analyses.get(tid, {}).get("last_result", {})

def get_test_stats_for_user(uid, tid):
    return get_test_entry(uid, tid)

def clear_expired_analysis():
    """2 soat ishlatilmagan tahlillarni RAMdan o'chirish"""
    now      = datetime.now(UTC)
    deadline = now - timedelta(hours=ANALYSIS_TTL_H)
    removed  = 0
    with _lck:
        keys = [k for k in list(_RAM)
                if k.startswith("ana_access_")]
        for k in keys:
            uid_str = k[11:]
            if _RAM[k] < deadline:
                del _RAM[k]
                _RAM.pop(f"analysis_{uid_str}", None)
                removed += 1
    if removed:
        log.info(f"RAM: {removed} user tahlili o'chirildi (2 soat TTL)")
    return removed

def get_all_solvers_for_test(tid):
    """Test yechgan barcha userlar — stats cache dan"""
    users  = get_users()
    result = []
    with _lck:
        keys = [k for k in _RAM if k.startswith("stats_")]
    for key in keys:
        uid_str = key[6:]
        e       = _get(key, {})
        entry   = e.get("data", {}).get(tid)
        if not entry or entry.get("attempts", 0) == 0:
            continue
        user = users.get(uid_str, {})
        result.append({
            "uid":        uid_str,
            "name":       user.get("name", f"User {uid_str}"),
            "username":   user.get("username", ""),
            "attempts":   entry["attempts"],
            "all_pcts":   entry["all_pcts"],
            "best_score": entry["best_score"],
            "avg_score":  entry["avg_score"],
            "last_at":    entry.get("last_at", ""),
        })
    result.sort(key=lambda x: x["best_score"], reverse=True)
    return result


# ══ GLOBAL LEADERBOARD (top 20) ═══════════════════════════════

def get_global_leaderboard():
    """Startup da TG dan yuklanadi, keyin RAMda"""
    return _get("global_leaderboard", [])

def set_global_leaderboard(data):
    _set("global_leaderboard", data)

def update_global_leaderboard():
    """RAM dagi user stats dan top 20 ni hisoblash"""
    users = get_users()
    rows  = []
    with _lck:
        keys = [k for k in _RAM if k.startswith("stats_")]
    for key in keys:
        uid_str = key[6:]
        e       = _get(key, {})
        data    = e.get("data", {})
        if not data: continue
        all_scores = [v["best_score"] for v in data.values() if v.get("attempts", 0) > 0]
        if not all_scores: continue
        avg   = round(sum(all_scores) / len(all_scores), 1)
        total = len(all_scores)
        user  = users.get(uid_str, {})
        rows.append({
            "uid":         uid_str,
            "name":        user.get("name", f"User {uid_str}")[:20],
            "avg_score":   avg,
            "total_tests": total,
        })
    rows.sort(key=lambda x: x["avg_score"], reverse=True)
    top20 = rows[:20]
    set_global_leaderboard(top20)
    return top20


# ══ GURUH LEADERBOARD (kunlik top 20) ══════════════════════════

def get_group_leaderboard():
    """Bugungi guruh leaderboard"""
    return _get("group_leaderboard", [])

def update_group_leaderboard(uid_str, name, score, correct, total):
    """Guruhda test yechilganda yangilanadi"""
    lb = _get("group_leaderboard", [])
    # Mavjud yozuvni yangilash
    found = False
    for row in lb:
        if row["uid"] == uid_str:
            if score > row["best_score"]:
                row["best_score"] = score
                row["correct"]    = correct
                row["total"]      = total
            row["attempts"] = row.get("attempts", 0) + 1
            found = True
            break
    if not found:
        lb.append({
            "uid":        uid_str,
            "name":       name[:20],
            "best_score": score,
            "correct":    correct,
            "total":      total,
            "attempts":   1,
        })
    lb.sort(key=lambda x: x["best_score"], reverse=True)
    _set("group_leaderboard", lb[:20])
    _set("group_lb_dirty", True)

def clear_group_leaderboard():
    """Kun o'zgarganda tozalanadi"""
    _set("group_leaderboard", [])
    _set("group_lb_dirty", False)

def is_group_lb_dirty():
    return _get("group_lb_dirty", False)

def clear_group_lb_dirty():
    _set("group_lb_dirty", False)


# ══ MOSLIK — eski daily_results formati ═══════════════════════

def get_daily():
    """Moslik uchun — stats cache dan daily format"""
    daily = {}
    with _lck:
        keys = [k for k in _RAM if k.startswith("stats_")]
    for key in keys:
        uid_str = key[6:]
        e       = _get(key, {})
        data    = e.get("data", {})
        by_test = {}
        for tid, s in data.items():
            by_test[tid] = {
                "attempts":      s["attempts"],
                "all_pcts":      s["all_pcts"],
                "best_score":    s["best_score"],
                "avg_score":     s["avg_score"],
                "last_at":       s.get("last_at", ""),
                "last_analysis": [],
                "last_result":   {},
                "first_result":  None,
                "accessed_link": False,
            }
        if by_test:
            daily[uid_str] = {"by_test": by_test, "history": []}
    return daily

def clear_daily():
    with _lck:
        keys = [k for k in list(_RAM)
                if k.startswith("stats_") or k.startswith("analysis_")
                or k.startswith("ana_access_")]
        for k in keys:
            del _RAM[k]
    log.info("RAM natijalar tozalandi")

def load_solvers_to_ram(tid, solvers_dict):
    """TG dan yuklangan solvers → stats cache"""
    for uid_str, s in solvers_dict.items():
        stats = get_user_stats_cache(uid_str) or {}
        if tid not in stats:
            stats[tid] = {
                "attempts":   s.get("attempts", 0),
                "all_pcts":   s.get("all_pcts", []),
                "best_score": s.get("best_score", 0.0),
                "avg_score":  s.get("avg_score", 0.0),
                "last_at":    s.get("last_at", ""),
                "passed":     s.get("best_score", 0) >= 60,
            }
            set_user_stats_cache(uid_str, stats, dirty=False)

def load_history_to_ram(history_dict):
    """TG user stats → RAM"""
    for uid_str, by_test in history_dict.items():
        stats = get_user_stats_cache(uid_str) or {}
        for tid, entry in by_test.items():
            if tid not in stats:
                stats[tid] = {
                    "attempts":   entry.get("attempts", 0),
                    "all_pcts":   entry.get("all_pcts", []),
                    "best_score": entry.get("best_score", 0.0),
                    "avg_score":  entry.get("avg_score", 0.0),
                    "last_at":    entry.get("last_at", ""),
                    "passed":     entry.get("best_score", 0) >= 60,
                }
        if stats:
            set_user_stats_cache(uid_str, stats, dirty=False)


# ══ MENYU ══════════════════════════════════════════════════════

def set_menu_msg(uid, cid, msg_id):
    _set(f"menu_msg_{uid}", {"cid": cid, "mid": msg_id})

def get_menu_msg(uid):
    with _lck:
        return _RAM.get(f"menu_msg_{uid}")

def pop_menu_msg(uid):
    with _lck:
        return _RAM.pop(f"menu_msg_{uid}", None)


# ══ STATS ══════════════════════════════════════════════════════

def stats():
    metas = _get("tests_meta", [])
    users = get_users()
    with _lck:
        cq  = sum(1 for k in _RAM if k.startswith("qcache_"))
        ana = sum(1 for k in _RAM if k.startswith("analysis_"))
        sts = sum(1 for k in _RAM if k.startswith("stats_"))
    total = sys.getsizeof(str(metas)) + sys.getsizeof(str(users))
    return {
        "tests":    len(metas),
        "users":    len(users),
        "daily_r":  sts,
        "cached_q": cq,
        "analysis": ana,
        "mb":       round(total / 1024 / 1024, 2),
        "pct":      round(total / RAM_LIMIT * 100, 1),
        "limit_mb": 450,
    }


# ══ FAN NOMLARI ════════════════════════════════════════════════

def get_user_custom_subjects(uid):
    return _get("user_custom_subjects", {}).get(str(uid), [])

def add_user_custom_subject(uid, subject):
    from config import SUBJECTS
    if subject in SUBJECTS: return
    d   = _get("user_custom_subjects", {})
    lst = d.get(str(uid), [])
    if subject not in lst:
        lst.insert(0, subject)
        lst = lst[:10]
    d[str(uid)] = lst
    _set("user_custom_subjects", d)

def get_all_custom_subjects():
    return _get("user_custom_subjects", {})

def set_all_custom_subjects(d):
    _set("user_custom_subjects", d)


# ══ GURUHLAR (bot admin bo'lgan guruhlar) ══════════════════════

def get_known_groups() -> dict:
    """
    {str(chat_id): {chat_id, title, username, type, added_at, active}}
    """
    return _get("known_groups", {})

def add_known_group(chat_id: int, title: str, username: str = "",
                    chat_type: str = "supergroup", member_count: int = 0):
    groups = _get("known_groups", {})
    cid    = str(chat_id)
    groups[cid] = {
        "chat_id":      chat_id,
        "title":        title,
        "username":     username or "",
        "type":         chat_type,
        "member_count": member_count,
        "added_at":     groups.get(cid, {}).get("added_at",
                        datetime.now(UTC).strftime("%Y-%m-%d %H:%M")),
        "active":       True,
    }
    _set("known_groups", groups)

def remove_known_group(chat_id: int):
    groups = _get("known_groups", {})
    cid    = str(chat_id)
    if cid in groups:
        groups[cid]["active"] = False
        _set("known_groups", groups)

def set_known_groups(d: dict):
    _set("known_groups", d)
