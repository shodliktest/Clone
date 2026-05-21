"""
💾 STORE — barcha ma'lumotlar shu modulda
RAM + Telegram kanal (STORAGE_CHANNEL_ID)

Ma'lumotlar:
  tests     : {tid: test_dict}   — savollar bilan birga
  users     : {uid: user_dict}
  results   : {uid: [result]}
  sessions  : {chat_id: session} — guruh test sessiyalari
"""
import json, io, logging, threading, time
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)
UTC = timezone.utc
_lk = threading.Lock()

# ── RAM ───────────────────────────────────────────────────
_tests    : dict = {}   # tid  -> test (questions bilan)
_users    : dict = {}   # uid  -> user
_results  : dict = {}   # uid  -> [result, ...]
_sessions : dict = {}   # chat_id -> session

# ── TG kanal ──────────────────────────────────────────────
_bot = None
_cid = None
_idx : dict = {}        # {test_TID: msg_id, users_msg_id, ...}
_dirty_users = False


# ═══════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════

async def startup(bot, channel_id: int):
    global _bot, _cid, _idx
    _bot, _cid = bot, channel_id
    _idx = await _load_index()
    if not _idx:
        _idx = {}
        log.info("Yangi baza boshlandi")
        return

    # Testlarni yuklash
    for key, msg_id in list(_idx.items()):
        if key.startswith("test_"):
            tid  = key[5:]
            data = await _fetch(msg_id)
            if data and data.get("questions"):
                _tests[tid] = data
    log.info(f"✅ {len(_tests)} test yuklandi")

    # Userlarni yuklash
    uid_mid = _idx.get("users_msg_id")
    if uid_mid:
        data = await _fetch(uid_mid)
        if isinstance(data, dict):
            _users.update(data.get("users", {}))
    log.info(f"✅ {len(_users)} user yuklandi")

    # Natijalarni yuklash
    res_mid = _idx.get("results_msg_id")
    if res_mid:
        data = await _fetch(res_mid)
        if isinstance(data, dict):
            _results.update(data.get("results", {}))
    log.info(f"✅ Startup yakunlandi")


def tg_ready():
    return _bot is not None and bool(_cid)


# ═══════════════════════════════════════════════════════════
# TESTLAR
# ═══════════════════════════════════════════════════════════

def get_all_tests() -> list:
    with _lk:
        return [t for t in _tests.values() if t.get("is_active", True)]

def get_public_tests() -> list:
    return [t for t in get_all_tests() if t.get("visibility") == "public"]

def get_my_tests(creator_id) -> list:
    return [t for t in get_all_tests() if t.get("creator_id") == creator_id]

def get_test(tid: str) -> dict:
    with _lk:
        return _tests.get(tid.upper(), {})

def add_test(test: dict) -> str:
    """Test RAM ga qo'shadi, keyin TG kanalga saqlaydi."""
    tid = test["test_id"]
    with _lk:
        _tests[tid] = test
    return tid

async def save_test_tg(test: dict) -> bool:
    """Testni TG kanalga JSON fayl sifatida saqlaydi."""
    if not tg_ready():
        return False
    tid = test["test_id"]
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf(test, f"test_{tid}.json"),
            caption=f"📝 {test.get('title','?')} | {test.get('category','')} | "
                    f"{len(test.get('questions',[]))} savol | {tid}"
        )
        _idx[f"test_{tid}"] = msg.message_id
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_test_tg: {e}")
        return False

async def delete_test(tid: str):
    with _lk:
        t = _tests.get(tid)
        if t:
            t["is_active"] = False
    if tg_ready():
        try:
            await _save_index()
        except Exception as e:
            log.error(f"delete_test: {e}")


# ═══════════════════════════════════════════════════════════
# USERLAR
# ═══════════════════════════════════════════════════════════

def get_user(uid) -> dict:
    with _lk:
        return _users.get(str(uid), {})

def upsert_user(uid, data: dict):
    global _dirty_users
    with _lk:
        _users[str(uid)] = data
        _dirty_users = True

def get_all_users() -> list:
    with _lk:
        return list(_users.values())

async def save_users_tg() -> bool:
    global _dirty_users
    if not tg_ready():
        return False
    try:
        with _lk:
            snapshot = dict(_users)
        msg = await _bot.send_document(
            _cid,
            document=_buf({"users": snapshot, "at": str(datetime.now(UTC))}, "users.json"),
            caption=f"👥 USERLAR | {len(snapshot)} ta"
        )
        _idx["users_msg_id"] = msg.message_id
        await _save_index()
        _dirty_users = False
        return True
    except Exception as e:
        log.error(f"save_users_tg: {e}")
        return False

def is_users_dirty() -> bool:
    return _dirty_users


# ═══════════════════════════════════════════════════════════
# NATIJALAR
# ═══════════════════════════════════════════════════════════

def save_result(uid, result: dict) -> str:
    """Natijani RAM ga saqlaydi. rid qaytaradi."""
    import uuid
    rid = str(uuid.uuid4())[:8].upper()
    result["rid"] = rid
    result["saved_at"] = str(datetime.now(UTC))
    with _lk:
        key = str(uid)
        if key not in _results:
            _results[key] = []
        _results[key].insert(0, result)
        # Faqat oxirgi 50 ta natija
        _results[key] = _results[key][:50]
    return rid

def get_results(uid) -> list:
    with _lk:
        return list(_results.get(str(uid), []))

def get_result(uid, rid) -> dict:
    for r in get_results(uid):
        if r.get("rid") == rid:
            return r
    return {}

async def save_results_tg() -> bool:
    if not tg_ready():
        return False
    try:
        with _lk:
            snapshot = dict(_results)
        msg = await _bot.send_document(
            _cid,
            document=_buf({"results": snapshot, "at": str(datetime.now(UTC))}, "results.json"),
            caption=f"📊 NATIJALAR | {len(snapshot)} user"
        )
        _idx["results_msg_id"] = msg.message_id
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_results_tg: {e}")
        return False

def get_leaderboard(limit=20) -> list:
    """Global reyting — o'rtacha ball bo'yicha."""
    with _lk:
        rows = []
        for uid, res_list in _results.items():
            if not res_list:
                continue
            scores = [r.get("percentage", 0) for r in res_list]
            avg    = round(sum(scores) / len(scores), 1)
            name   = res_list[0].get("user_name", f"User{uid}")
            rows.append({"uid": uid, "name": name,
                         "avg": avg, "total": len(scores)})
        rows.sort(key=lambda x: x["avg"], reverse=True)
        return rows[:limit]


# ═══════════════════════════════════════════════════════════
# GURUH SESSIYALARI
# ═══════════════════════════════════════════════════════════

def create_session(chat_id, tid, test, qs, mode, host_id, poll_time) -> dict:
    sess = {
        "tid": tid, "test": test, "qs": qs, "idx": 0,
        "mode": mode, "host_id": host_id, "poll_time": poll_time,
        "msg_id": None, "task": None, "is_active": True,
        "started_at": time.time(),
        "participants": {},   # {str(uid): {name, score, answers}}
        "answered": set(),    # inline: joriy savolda javob berganlar
        "q_answers": {},      # inline: {str(uid): letter}
        "poll_map": {},       # poll: {poll_id: q_idx}
        "poll_msg_ids": [],
    }
    _sessions[chat_id] = sess
    return sess

def get_session(chat_id) -> dict:
    return _sessions.get(chat_id)

def has_session(chat_id) -> bool:
    return chat_id in _sessions

def delete_session(chat_id):
    sess = _sessions.pop(chat_id, None)
    if sess:
        t = sess.get("task")
        if t:
            try: t.cancel()
            except: pass

def set_session_task(chat_id, task):
    sess = _sessions.get(chat_id)
    if sess:
        old = sess.get("task")
        if old:
            try: old.cancel()
            except: pass
        sess["task"] = task

def record_answer(sess, uid, name, q_idx, letter) -> bool:
    """Inline javob. True=yangi, False=allaqachon."""
    if uid in sess.get("answered", set()):
        return False
    _ensure_participant(sess, uid, name)
    p = sess["participants"][str(uid)]
    p["answers"][str(q_idx)] = letter
    sess.setdefault("q_answers", {})[str(uid)] = letter
    sess.setdefault("answered", set()).add(uid)
    # Ball
    q = sess["qs"][q_idx] if q_idx < len(sess["qs"]) else {}
    if _is_correct(q, letter):
        p["score"] += 1
    return True

def record_poll_answer(sess, uid, name, poll_id, option_ids) -> bool:
    """Poll javob."""
    if not option_ids:
        return False
    poll_map = sess.get("poll_map", {})
    if poll_id not in poll_map:
        return False
    q_idx = poll_map[poll_id]
    LT    = "ABCDEFGHIJ"
    letter = LT[option_ids[0]] if option_ids[0] < len(LT) else str(option_ids[0])
    _ensure_participant(sess, uid, name)
    p = sess["participants"][str(uid)]
    scored_key = f"_sc{q_idx}"
    # Avvalgi ball bormi?
    old_letter = p["answers"].get(str(q_idx))
    p["answers"][str(q_idx)] = letter
    q = sess["qs"][q_idx] if q_idx < len(sess["qs"]) else {}
    if _is_correct(q, letter):
        if scored_key not in p:
            p[scored_key] = True
            p["score"] += 1
    else:
        if scored_key in p:
            del p[scored_key]
            p["score"] = max(0, p["score"] - 1)
    return True

def get_session_leaderboard(sess) -> list:
    """[(name, score, pct, ans_cnt, uid_str)]"""
    total = len(sess.get("qs", []))
    rows  = []
    for uid_str, p in sess.get("participants", {}).items():
        score   = p.get("score", 0)
        ans_cnt = len(p.get("answers", {}))
        pct     = round(score / total * 100) if total else 0
        rows.append((p.get("name", f"User{uid_str}"), score, pct, ans_cnt, uid_str))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows


# ═══════════════════════════════════════════════════════════
# TG KANAL YORDAMCHILAR
# ═══════════════════════════════════════════════════════════

async def _load_index() -> dict:
    if not tg_ready():
        return {}
    try:
        chat = await _bot.get_chat(_cid)
        pin  = getattr(chat, "pinned_message", None)
        if pin:
            doc = getattr(pin, "document", None)
            if doc and "index" in (doc.file_name or "").lower():
                data = await _fetch_doc(doc.file_id)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        log.warning(f"Index yuklashda xato: {e}")
    return {}

async def _save_index():
    if not tg_ready():
        return
    try:
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(
            _cid,
            document=_buf(_idx, "index.json"),
            caption=f"📋 INDEX | {ts}"
        )
        try:
            await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
        except:
            pass
    except Exception as e:
        log.error(f"Index saqlashda xato: {e}")

async def _fetch(msg_id) -> dict:
    try:
        fwd = await _bot.forward_message(_cid, _cid, msg_id)
        doc = getattr(fwd, "document", None)
        if not doc:
            try: await _bot.delete_message(_cid, fwd.message_id)
            except: pass
            return {}
        data = await _fetch_doc(doc.file_id)
        try: await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        return data
    except Exception as e:
        log.error(f"fetch({msg_id}): {e}")
        return {}

async def _fetch_doc(file_id) -> dict:
    try:
        f   = await _bot.get_file(file_id)
        buf = io.BytesIO()
        await _bot.download_file(f.file_path, destination=buf)
        buf.seek(0)
        return json.loads(buf.read().decode())
    except Exception as e:
        log.error(f"fetch_doc: {e}")
        return {}

def _buf(data, name):
    from aiogram.types import BufferedInputFile
    raw = json.dumps(data, ensure_ascii=False, default=str, indent=2).encode()
    return BufferedInputFile(raw, filename=name)


# ═══════════════════════════════════════════════════════════
# ICHKI YORDAMCHILAR
# ═══════════════════════════════════════════════════════════

def _ensure_participant(sess, uid, name):
    uid_str = str(uid)
    if uid_str not in sess["participants"]:
        sess["participants"][uid_str] = {"name": name, "score": 0, "answers": {}}

def _is_correct(q, letter) -> bool:
    import re
    corr = q.get("correct", "")
    if q.get("type") == "true_false":
        given   = {"A": "Ha", "B": "Yo'q"}.get(letter, letter)
        return str(corr).strip().lower() in given.lower()
    if isinstance(corr, int):
        LT = "ABCDEFGHIJ"
        c_letter = LT[corr] if corr < len(LT) else "A"
    else:
        m = re.match(r"^([A-Za-z])", str(corr).strip())
        c_letter = m.group(1).upper() if m else "A"
    return letter.upper() == c_letter.upper()
