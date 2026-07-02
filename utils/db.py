"""DB — CRUD operatsiyalar"""
import uuid, logging, asyncio
from datetime import datetime, timezone
from utils import ram_cache as ram

log = logging.getLogger(__name__)
UTC = timezone.utc


def _fire_and_forget_user_write(tg_id):
    """
    RAM'dagi foydalanuvchini DARHOL Supabase'ga background'da yozadi —
    chaqiruvchi funksiya kutmaydi (await shart emas), lekin yozuv
    milliseкundlar ichida boshlanadi. Shu tufayli update_user() sinxron
    qolaveradi (7+ chaqiruvchi joyni async qilish shart emas), lekin
    "faqat RAM'da turib 5 daqiqa kutish" muammosi yo'qoladi.

    Agar hech qanday asyncio event loop ishlamayotgan bo'lsa (masalan
    skript kontekstida), jim o'tkazib yuboriladi — xato bermaydi.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            async def _write():
                try:
                    from utils import tg_db
                    u = ram.get_user(tg_id)
                    if u:
                        await tg_db.write_user_now(int(tg_id), u)
                except Exception as e:
                    log.warning(f"_fire_and_forget_user_write({tg_id}): {e}")
            loop.create_task(_write())
    except RuntimeError:
        # Event loop yo'q — dirty flag orqali keyingi flush'da yoziladi
        pass


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
    # DARHOL Supabase'ga ham yoziladi (bu funksiya async, to'g'ridan await qilamiz)
    from utils import tg_db
    try:
        await tg_db.write_user_now(int(tg_id), user)
    except Exception as e:
        log.warning(f"get_or_create_user: darhol yozishda xato: {e}")
        ram.mark_users_dirty()
        tg_db.mark_users_dirty_tg()
    return user

def update_user(tg_id, data, _skip_immediate_write=False):
    user = ram.get_user(tg_id) or {}
    user.update(data)
    user["last_active"] = str(datetime.now(UTC))
    ram.upsert_user(tg_id, user)
    # DARHOL background'da Supabase'ga yozish (rol, blok, referal,
    # statistika o'zgarishlari — hech biri bot o'chsa yo'qolmasin).
    # _skip_immediate_write=True bo'lsa (masalan save_result ichida,
    # u allaqachon o'zi kafolatlangan await yozuv qiladi) — ortiqcha
    # ikkilanmasin deb background yozuv o'tkazib yuboriladi.
    if not _skip_immediate_write:
        _fire_and_forget_user_write(tg_id)
    from utils import tg_db
    tg_db.mark_users_dirty_tg()  # fallback — agar background yozuv sekinlasa/tushib qolsa

def block_user(tg_id, blocked=True):
    update_user(tg_id, {"is_blocked": blocked})
    # RAM set da ham yangilash — middleware tez topsin
    from utils import ram_cache as ram
    ram.set_blocked(tg_id, blocked)

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
        # Referal tizimi
        "ref_required":     data.get("ref_required", False),
        "ref_count":        int(data.get("ref_count", 0)),
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

            # ── Fayl-tanish: agar bu test fayldan yaratilgan bo'lsa,
            #    uning hashini ro'yxatga olamiz — keyingi safar xuddi
            #    shu fayl yuklansa, bot uni tanib qayta parse qilmaydi.
            file_hash = data.get("_source_file_hash", "")
            file_name = data.get("_source_file_name", "")
            file_size = data.get("_source_file_size", 0)
            if file_hash:
                try:
                    from utils import file_fingerprint as fp
                    await fp.register_fingerprint(
                        file_hash=file_hash, test_id=tid,
                        file_name=file_name, uploaded_by=creator_id,
                        file_size=file_size,
                    )
                except Exception as _fp_e:
                    log.warning(f"fingerprint ro'yxatga olish xato: {_fp_e}")
    return tid

async def delete_test(tid):
    """
    ADMIN o'chirganda — butunlay o'chiriladi.
    TG dan ham o'chiriladi (is_active=False + backup).
    """
    from utils import tg_db
    test = ram.get_cached_questions(tid) or ram.get_test_meta_any(tid) or {}
    if tg_db.ready() and test:
        await tg_db.save_deleted_test_backup(test)
    ram.delete_test_from_ram(tid)
    if tg_db.ready():
        await tg_db.delete_test_tg(tid)


async def creator_delete_test(tid):
    """
    YARATUVCHI o'chirganda — soft delete.
    Test is_deleted=True bo'ladi, foydalanuvchilar ko'rmaydi.
    Admin ko'ra oladi va TXT yuklab olishi mumkin.
    TG bazada saqlanib turadi.
    """
    from utils import tg_db
    ram.soft_delete_test(tid)
    if tg_db.ready():
        await tg_db.update_test_meta_tg(tid, {"is_deleted": True})

def pause_test(tid, paused: bool):
    ram.update_test_meta(tid, {"is_paused": paused})
    from utils import tg_db
    tg_db.mark_stats_dirty()
    # Darhol yozish — pauza holati bot o'chganda yo'qolmasin
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            async def _write():
                try:
                    await tg_db.update_test_meta_tg(tid, {"is_paused": paused})
                except Exception as e:
                    log.warning(f"pause_test darhol yozish xato: {e}")
            loop.create_task(_write())
    except RuntimeError:
        pass

def get_all_tests_admin():
    """Admin uchun — o'chirilganlarni ham ko'rsatadi"""
    return ram.get_all_tests_meta()


# ══ NATIJALAR ══════════════════════════════════════════════════

async def save_result(user_id, test_id, result, via_link=False):
    # Test yechildi — last_access yangilanadi (48h TTL uzayadi)
    ram.touch_test_access(test_id)
    """
    Natija RAMga DARHOL saqlanadi VA Supabase'ga ham DARHOL yoziladi
    (avvalgi versiyada faqat RAM'da turib, 5 daqiqada bir marta yoki
    tungi flush'da bazaga tushardi — bot shu oraliqda qayta ishga
    tushsa yoki qulasa, o'sha natijalar yo'qolib qolardi).

    Endi: RAM cache hali ham bor (tezkor o'qish uchun), lekin
    ma'lumot yo'qolmasligi endi Supabase yozuviga bog'liq, RAM'ga emas.
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
        }, _skip_immediate_write=True)  # pastda kafolatlangan await yozuv bor

    # ── DARHOL Supabase'ga yozish (RAM emas, asosiy manba) ──
    from utils import tg_db
    try:
        uid_str = str(user_id)
        stats   = ram.get_user_stats_cache(uid_str) or {}
        await tg_db.write_user_stats_now(int(user_id), stats)
    except Exception as e:
        log.error(f"save_result: user_stats darhol yozishda xato: {e}")
        # RAM'da baribir bor, keyingi flush urinib ko'radi
        tg_db.mark_stats_dirty()

    try:
        if meta:
            await tg_db.write_test_stats_now(
                test_id, meta.get("solve_count", 0), meta.get("avg_score", 0)
            )
    except Exception as e:
        log.error(f"save_result: test stats darhol yozishda xato: {e}")
        tg_db.mark_stats_dirty()

    try:
        u = ram.get_user(user_id)
        if u:
            await tg_db.write_user_now(int(user_id), u)
    except Exception as e:
        log.error(f"save_result: user darhol yozishda xato: {e}")
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
    Yangi chunked arxitektura bilan ishlaydi.
    """
    from utils import tg_db
    if not tg_db.ready():
        return 0

    try:
        # Yangi tg_db da _load_index yo'q — get_tests_meta() ishlatamiz
        # (u _index["tests_meta"] ni qaytaradi, init da chunklar yuklanadi)
        fresh_metas = tg_db.get_tests_meta()
        if not fresh_metas:
            return 0

        ram_ids = {t.get("test_id") for t in ram.get_all_tests_meta()}
        added = 0
        for meta in fresh_metas:
            tid = meta.get("test_id")
            if tid and tid not in ram_ids:
                clean = {k: v for k, v in meta.items() if k != "questions"}
                ram.add_test_meta(clean)
                added += 1
                log.info(f"_sync_from_tg: {tid} qo'shildi")
        return added
    except Exception as e:
        log.error(f"_sync_from_tg xato: {e}")
        return 0
