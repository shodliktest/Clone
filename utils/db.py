"""DB — CRUD operatsiyalar"""
import uuid, logging
from datetime import datetime, timezone
from utils import ram_cache as ram

log = logging.getLogger(__name__)
UTC = timezone.utc


# ══ USERS ══════════════════════════════════════════════════════

def get_user(tg_id):
    return ram.get_user(tg_id)

async def get_or_create_user(tg_id, name, username=None):
    user = ram.get_user(tg_id)
    now  = str(datetime.now(UTC))
    if user:
        user["last_active"] = now
        ram.upsert_user(tg_id, user)
        return user
    # Yangi user
    user = {
        "telegram_id": tg_id, "name": name, "username": username,
        "role": "user", "is_blocked": False,
        "total_tests": 0, "total_score": 0.0, "avg_score": 0.0,
        "created_at": now, "last_active": now,
        "_just_created": True,
    }
    ram.upsert_user(tg_id, user)
    # Yangi user — dirty flag, auto_flush da yoziladi
    ram.mark_users_dirty()
    from utils import tg_db
    tg_db.mark_users_dirty_tg()
    return user

def update_user(tg_id, data):
    user = ram.get_user(tg_id) or {}
    user.update(data)
    user["last_active"] = str(datetime.now(UTC))
    ram.upsert_user(tg_id, user)

def block_user(tg_id, blocked=True):
    update_user(tg_id, {"is_blocked": blocked})

def get_all_users():
    return list(ram.get_users().values())

async def _flush_users_to_tg():
    """Users JSON ni TG ga yuborish — yangi user kelganda chaqiriladi"""
    from utils import tg_db
    if tg_db.ready():
        await tg_db.save_users(ram.get_users())
        ram.clear_users_dirty()
        log.info("Users TG ga yuborildi")


# ══ TESTS ══════════════════════════════════════════════════════

def get_test(tid):
    return ram.get_test_by_id(tid)

async def get_test_full(tid):
    """
    To'liq test (savollar bilan):
    1. 12 soat RAM cache
    2. TG kanaldan yuklab oladi + cache qiladi
    3. Web testlar uchun index qayta tekshiriladi
    """
    cached = ram.get_cached_questions(tid)
    if cached:
        return cached
    from utils import tg_db
    if tg_db.ready():
        full = await tg_db.get_test_full(tid)
        if full and full.get("questions"):
            ram.cache_questions(tid, full)
            return full
        else:
            log.warning(f"get_test_full: {tid} uchun savollar topilmadi (web test bo'lishi mumkin, 60s kuting)")
    # Meta bor bo'lsa qaytaramiz (savollarsiz)
    meta = ram.get_test_meta(tid)
    return meta if meta else {}

def get_all_tests():
    return [t for t in ram.get_tests_meta() if t.get("is_active", True)]

def get_public_tests():
    return [t for t in get_all_tests() if t.get("visibility") == "public"]

def get_link_tests():
    return [t for t in get_all_tests() if t.get("visibility") == "link"]

def get_my_tests(creator_id):
    return [t for t in get_all_tests() if t.get("creator_id") == creator_id]

async def create_test(creator_id, data, creator_name="", creator_username=""):
    tid  = str(uuid.uuid4())[:8].upper()
    test = {
        "test_id":          tid,
        "creator_id":       creator_id,
        "creator_name":     creator_name or f"User{creator_id}",
        "creator_username": creator_username or "",
        "title":            data.get("title", "Nomsiz"),
        "category":         data.get("category", "Boshqa"),
        "difficulty":       data.get("difficulty", "medium"),
        "visibility":       data.get("visibility", "public"),
        "time_limit":       data.get("time_limit", 0),
        "poll_time":        data.get("poll_time", 30),
        "passing_score":    data.get("passing_score", 60),
        "max_attempts":     data.get("max_attempts", 0),
        "questions":        data.get("questions", []),
        "question_count":   len(data.get("questions", [])),
        "solve_count":      0,
        "avg_score":        0.0,
        "is_active":        True,
        "is_paused":        False,
        "created_at":       str(datetime.now(UTC)),
    }
    # RAMga qo'shamiz
    ram.add_test(test)
    # TG kanalga darhol to'liq yuboramiz (JSON fayl)
    from utils import tg_db
    if tg_db.ready():
        ok = await tg_db.save_test_full(test)
        if ok:
            log.info(f"Yangi test TG ga yuborildi: {tid}")
    return tid

async def delete_test(tid):
    """
    Test o'chirish tartibi:
      1. RAMda mavjud test — backup (lazy load YO'Q, faqat cache dan)
      2. RAMdan o'chirish
      3. TG indexda is_active=False
    Lazy load QILINMAYDI — sekin va timeout beradi.
    """
    from utils import tg_db

    # Faqat RAM/cache dan olish — TGga bormaslik
    test = ram.get_cached_questions(tid) or ram.get_test_meta(tid) or {}

    # Backup — agar savollar RAM da bo'lsa yuboramiz, bo'lmasa faqat meta
    if tg_db.ready() and test:
        await tg_db.save_deleted_test_backup(test)

    # RAMdan o'chirish
    ram.delete_test_from_ram(tid)

    # TG indexda is_active=False (saqlaydi)
    if tg_db.ready():
        await tg_db.delete_test_tg(tid)

def pause_test(tid, paused: bool):
    ram.update_test_meta(tid, {"is_paused": paused})
    from utils import tg_db
    tg_db.mark_stats_dirty()

def get_all_tests_admin():
    """Admin uchun — o'chirilganlarni ham ko'rsatadi"""
    return ram.get_all_tests_meta()


# ══ NATIJALAR ══════════════════════════════════════════════════

def save_result(user_id, test_id, result, via_link=False):
    # Test yechildi — last_access yangilanadi (48h TTL uzayadi)
    ram.touch_test_access(test_id)
    """
    Natija RAMga saqlanadi (TG ga YUKLANMAYDI).
    TG upload faqat: midnight flush yoki admin buyruq.
    """
    rid = ram.save_result_to_ram(user_id, test_id, result, via_link=via_link)

    # Test meta statistika yangilash
    meta = ram.get_test_meta(test_id)
    if meta:
        sc  = meta.get("solve_count", 0) + 1
        avg = ((meta.get("avg_score", 0) * (sc - 1)) + result.get("percentage", 0)) / sc
        ram.update_test_meta(test_id, {
            "solve_count": sc,
            "avg_score":   round(avg, 1)
        })

    # User statistika yangilash
    user = ram.get_user(user_id)
    if user:
        tt = user.get("total_tests", 0) + 1
        ts = user.get("total_score", 0.0) + result.get("percentage", 0)
        update_user(user_id, {
            "total_tests": tt,
            "total_score": ts,
            "avg_score":   round(ts / tt, 1),
        })
    # Dirty flag — 5 daqiqada TG ga yuklanadi
    from utils import tg_db
    tg_db.mark_stats_dirty()
    tg_db.mark_users_dirty_tg()
    return rid

def get_user_results(user_id):
    return ram.get_user_results(user_id)

def get_analysis(user_id, result_id):
    return ram.get_analysis(user_id, result_id)

def get_test_stats_for_user(user_id, test_id):
    return ram.get_test_entry(user_id, test_id)

def get_test_solvers(test_id):
    """Test yechgan barcha userlar — creator/admin uchun"""
    return ram.get_all_solvers_for_test(test_id)

def get_leaderboard(limit=20):
    users = [u for u in get_all_users() if u.get("total_tests", 0) > 0]
    users.sort(key=lambda x: x.get("avg_score", 0), reverse=True)
    return users[:limit]


# ══ WEB SYNC (tg_db.web_sync_loop uchun) ══════════════════════

async def _sync_from_tg():
    """
    Web orqali qo'shilgan testlarni TG kanaldan RAMga yuklash.
    tg_db.web_sync_loop() tomonidan chaqiriladi.
    To'g'ridan tg_db funksiyalaridan foydalanadi.
    """
    from utils import tg_db
    if not tg_db.ready():
        return 0

    try:
        new_index = await tg_db._load_index()
        if not new_index or "tests_meta" not in new_index:
            return 0

        ram_ids = {t.get("test_id") for t in ram.get_all_tests_meta()}
        added = 0
        for meta in new_index.get("tests_meta", []):
            tid = meta.get("test_id")
            if tid and tid not in ram_ids:
                ram.add_test_meta(meta)
                added += 1
                log.info(f"_sync_from_tg: {tid} qo'shildi")
        return added
    except Exception as e:
        log.error(f"_sync_from_tg xato: {e}")
        return 0
