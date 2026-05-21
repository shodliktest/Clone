"""
TG_DB — Chunked Index + Xavfsiz Saqlash
=========================================

ASOSIY QOIDALAR:
  1. AVVAL YOZ, KEYIN O'CHIR  — hech qachon ma'lumot yo'qolmasin
  2. _save_meta() faqat barcha chunklar muvaffaqiyatli bo'lganda chaqiriladi
  3. auto_flush_loop — faqat stats va users, INDEX ga tegmaydi
  4. _save_index() faqat test qo'shilganda / o'zgartirilganda chaqiriladi
  5. Debounce: _index_dirty flag — keraksiz yozuvlar oldini oladi

ARXITEKTURA:
  index_meta.json  (pinned, ~5KB)
    index_chunks:      [{n, msg_id, fid, count}]
    users_list_chunks: [{n, msg_id, fid, count}]
    user_stats_chunks: [{n, msg_id, fid, uids}]
    tests_stats_msg_id, leaderboard_msg_id, ...
    backups: {date: msg_id}

  index_chunk_N.json  (har biri ~100 test)
    tests_meta: [...]
    test_{tid}: msg_id
    fid_{msg_id}: file_id
"""

import json, logging, io, asyncio
from datetime import datetime, timezone, date

log      = logging.getLogger(__name__)
UTC      = timezone.utc
_bot     = None
_cid     = None
_can_pin = True

_meta:  dict = {}
_index: dict = {"tests_meta": []}

_tests_cache: dict = {}
_stats_dirty       = False
_users_dirty       = False
_index_dirty       = False   # Index o'zgarganda True — keyingi flush da saqlanadi

INDEX_CHUNK_SIZE = 100
_save_lock = None   # asyncio.Lock — parallel yozuvni oldini oladi


def _get_lock():
    global _save_lock
    if _save_lock is None:
        _save_lock = asyncio.Lock()
    return _save_lock


# ══════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════

async def init(bot, channel_id):
    global _bot, _cid, _meta, _index, _tests_cache
    global _stats_dirty, _users_dirty, _index_dirty

    _cid         = int(channel_id)
    _meta        = {}
    _index       = {"tests_meta": []}
    _tests_cache = {}
    _stats_dirty = False
    _users_dirty = False
    _index_dirty = False

    from aiogram import Bot as _BotClass
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    _bot = _BotClass(
        token=bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, protect_content=False)
    )

    _meta = await _load_meta()
    if not _meta:
        # Yangi meta topilmadi — eski index.json formatini tekshirish
        log.info("index_meta topilmadi — eski format tekshirilmoqda...")
        _meta = await _migrate_from_old_index()
        if _meta:
            log.info("✅ Eski format migratsiya qilindi!")
        else:
            log.info("Yangi baza yaratilmoqda...")
            _meta = {
                "index_chunks":      [],
                "users_list_chunks": [],
                "user_stats_chunks": [],
                "backups":           {},
            }
            await _save_meta()
            return

    log.info(f"Meta yuklandi: {len(_meta.get('index_chunks',[]))} index chunk")

    # Tezkor yuklash — faqat fid orqali (kanal skanerlashsiz)
    # Bot polling shu qadar tezroq boshlanadi
    await _load_all_index_chunks_fast()
    await _load_tests_stats()

    # Users va guruhlar — background da yuklanadi (bot allaqachon ishlaydi)
    asyncio.create_task(_load_users_list())
    asyncio.create_task(load_known_groups())
    asyncio.create_task(_load_leaderboard())

    log.info(f"Tayyor (tez): {len(_index.get('tests_meta',[]))} test meta yuklandi")
    log.info("Users, guruhlar va leaderboard background da yuklanmoqda...")


def ready():
    return _bot is not None and bool(_cid)

def mark_stats_dirty():
    global _stats_dirty
    _stats_dirty = True

def mark_index_dirty():
    global _index_dirty
    _index_dirty = True

def mark_users_dirty_tg():
    global _users_dirty
    _users_dirty = True

def is_dirty():
    return _stats_dirty or _users_dirty or _index_dirty


# ══════════════════════════════════════════════════════════════
# INDEX META — pinned kichik fayl
# ══════════════════════════════════════════════════════════════

async def _migrate_from_old_index() -> dict:
    """
    TO'LIQ KANAL SKANERLASH:
    Kanaldan barcha JSON fayllarni topib ma'lumotlarni tiklaydi.

    Tartib:
      1. index_meta.json  → chunk msg_id lar → har chunk dan tests_meta
      2. index_chunk_N    → test_{tid}: msg_id → barcha testlar
      3. index.json (eski)→ tests_meta + test_{tid} msg_id lar
      4. users_list_N     → foydalanuvchilar
      5. known_groups     → guruhlar
      6. test_XXX.json    → to'g'ridan savollar (zaxira)
    """
    if not ready(): return {}

    log.info("TO'LIQ kanal skanerlash boshlandi (3000 xabar)...")

    # === 1-QADAM: Kanal tarixini skanerlash ===
    all_json_files = {}  # {msg_id: {file_name, file_id}}
    try:
        probe = await _bot.send_message(_cid, ".", protect_content=False)
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)

        for mid in range(cur - 1, max(1, cur - 3000), -1):
            try:
                fwd = await _bot.forward_message(_cid, _cid, mid)
                doc = getattr(fwd, "document", None)
                try:
                    await _bot.delete_message(_cid, fwd.message_id)
                except: pass
                if doc and doc.file_name and doc.file_name.endswith(".json"):
                    all_json_files[mid] = {
                        "name": doc.file_name.lower(),
                        "fid":  doc.file_id,
                    }
                await asyncio.sleep(0.05)
            except: pass

        log.info(f"Topilgan JSON fayllar: {len(all_json_files)} ta")
    except Exception as e:
        log.warning(f"Kanal skanerlash xato: {e}")
        return {}

    if not all_json_files:
        return {}

    # === 2-QADAM: Fayllarni turkumlash ===
    index_meta_files  = []   # index_meta.json
    index_chunk_files = []   # index_chunk_N.json
    index_old_files   = []   # index.json (eski format)
    test_full_files   = []   # test_XXX.json
    users_list_files  = []   # users_list_N.json
    group_files       = []   # known_groups.json
    stats_files       = []   # tests_stats.json
    settings_files    = []   # settings.json
    leaderboard_files = []   # leaderboard.json

    for mid, info in sorted(all_json_files.items(), reverse=True):
        name = info["name"]
        if "index_meta" in name:
            index_meta_files.append((mid, info))
        elif "index_chunk" in name:
            index_chunk_files.append((mid, info))
        elif name == "index.json":
            index_old_files.append((mid, info))
        elif (name.startswith("test_") and "deleted" not in name
              and "stats" not in name and "backup" not in name
              and "meta" not in name and "chunk" not in name):
            test_full_files.append((mid, info))
        elif "users_list" in name:
            users_list_files.append((mid, info))
        elif "known_groups" in name:
            group_files.append((mid, info))
        elif "tests_stats" in name:
            stats_files.append((mid, info))
        elif "settings" in name:
            settings_files.append((mid, info))
        elif "leaderboard" in name and "group" not in name:
            leaderboard_files.append((mid, info))

    log.info(f"  index_meta: {len(index_meta_files)}, "
             f"index_chunk: {len(index_chunk_files)}, "
             f"index_old: {len(index_old_files)}, "
             f"test_full: {len(test_full_files)}, "
             f"users_list: {len(users_list_files)}")

    global _index
    recovered_tids = set()
    new_meta = {
        "index_chunks":      [],
        "users_list_chunks": [],
        "user_stats_chunks": [],
        "backups":           {},
    }

    # === 3-QADAM: index_meta.json dan chunk ma'lumotlarini olish ===
    for mid, info in index_meta_files[:1]:   # eng yangi bitta
        data = await _read_file(info["fid"])
        if not isinstance(data, dict): continue
        if "index_chunks" in data:
            log.info(f"index_meta topildi: {len(data.get('index_chunks',[]))} chunk")
            # Meta ma'lumotlarini ko'chirish
            for key in ("leaderboard_msg_id","leaderboard_fid","tests_stats_msg_id",
                        "tests_stats_fid","settings_msg_id","settings_fid",
                        "group_lb_msg_id","group_lb_fid","group_lb_date",
                        "known_groups_msg_id","known_groups_fid","backups"):
                if data.get(key):
                    new_meta[key] = data[key]

    # === 4-QADAM: index_chunk_N.json dan tests_meta va msg_id lar ===
    for mid, info in index_chunk_files:
        data = await _read_file(info["fid"])
        if not isinstance(data, dict): continue
        for m in data.get("tests_meta", []):
            tid = m.get("test_id")
            if tid and tid not in recovered_tids:
                recovered_tids.add(tid)
                _index.setdefault("tests_meta", []).append(m)
        for k, v in data.items():
            if k.startswith("test_") or k.startswith("fid_"):
                _index[k] = v
        log.info(f"  chunk yukl: {len(data.get('tests_meta',[]))} test")

    # === 5-QADAM: Eski index.json dan (chunk da bo'lmaganlar) ===
    for mid, info in index_old_files[:1]:
        data = await _read_file(info["fid"])
        if not isinstance(data, dict): continue
        for m in data.get("tests_meta", []):
            tid = m.get("test_id")
            if tid and tid not in recovered_tids:
                recovered_tids.add(tid)
                _index.setdefault("tests_meta", []).append(m)
        for k, v in data.items():
            if k.startswith("test_") or k.startswith("fid_"):
                if k not in _index:
                    _index[k] = v
        # Eski users, settings saqlab olish
        for key in ("leaderboard_msg_id","leaderboard_fid","tests_stats_msg_id",
                    "tests_stats_fid","settings_msg_id"):
            if data.get(key) and not new_meta.get(key):
                new_meta[key] = data[key]
        if data.get("users_list_chunks") and not new_meta.get("users_list_chunks"):
            new_meta["users_list_chunks"] = data["users_list_chunks"]
        log.info(f"  eski index yukl: {len(data.get('tests_meta',[]))} test")

    # === 6-QADAM: test_XXX.json dan to'g'ridan (hali topilmaganlar) ===
    new_from_files = 0
    for mid, info in test_full_files:
        data = await _read_file(info["fid"])
        if not isinstance(data, dict): continue
        tid = data.get("test_id")
        if not tid or not data.get("questions"): continue
        # msg_id ni saqlash (har doim yangilash — eng yangi versiya)
        _index[f"test_{tid}"] = mid
        _index[f"fid_{mid}"]  = info["fid"]
        _tests_cache[tid]     = data
        if tid not in recovered_tids:
            recovered_tids.add(tid)
            meta = {k: v for k, v in data.items() if k != "questions"}
            meta["question_count"] = len(data["questions"])
            meta.setdefault("is_active", True)
            _index.setdefault("tests_meta", []).append(meta)
            new_from_files += 1
            log.info(f"  + test fayl: {data.get('title','?')} [{tid}]")
    if new_from_files:
        log.info(f"test fayl skanidan {new_from_files} yangi test tiklandi")

    # === 7-QADAM: Users list ===
    if users_list_files and not new_meta.get("users_list_chunks"):
        from utils import ram_cache as ram
        all_users = {}
        sorted_ulf = sorted(users_list_files, key=lambda x: x[0], reverse=True)
        # Har bir chunk faylini yukla (nomi bo'yicha ajrat)
        chunk_map = {}
        for mid, info in sorted_ulf:
            n = info["name"]  # users_list_1.json, users_list_2.json ...
            if n not in chunk_map:  # faqat eng yangi versiyasini ol
                chunk_map[n] = (mid, info)
        new_ul_chunks = []
        for name, (mid, info) in sorted(chunk_map.items()):
            data = await _read_file(info["fid"])
            if isinstance(data, dict) and data.get("users"):
                all_users.update(data["users"])
                new_ul_chunks.append({"n": len(new_ul_chunks)+1,
                                      "msg_id": mid, "fid": info["fid"],
                                      "count": len(data["users"])})
        if all_users:
            ram.set_users(all_users)
            new_meta["users_list_chunks"] = new_ul_chunks
            log.info(f"Users tiklandi: {len(all_users)} ta")

    # === 8-QADAM: Known groups ===
    if group_files and not new_meta.get("known_groups_msg_id"):
        mid, info = group_files[0]
        data = await _read_file(info["fid"])
        if isinstance(data, dict) and data.get("groups"):
            from utils import ram_cache as ram
            ram.set_known_groups(data["groups"])
            new_meta["known_groups_msg_id"] = mid
            new_meta["known_groups_fid"]    = info["fid"]
            log.info(f"Guruhlar tiklandi: {len(data['groups'])} ta")

    # === 9-QADAM: Stats va Settings ===
    if stats_files and not new_meta.get("tests_stats_msg_id"):
        mid, info = stats_files[0]
        new_meta["tests_stats_msg_id"] = mid
        new_meta["tests_stats_fid"]    = info["fid"]
    if settings_files and not new_meta.get("settings_msg_id"):
        mid, info = settings_files[0]
        new_meta["settings_msg_id"] = mid
        new_meta["settings_fid"]    = info["fid"]
    if leaderboard_files and not new_meta.get("leaderboard_msg_id"):
        mid, info = leaderboard_files[0]
        new_meta["leaderboard_msg_id"] = mid
        new_meta["leaderboard_fid"]    = info["fid"]

    _meta.update(new_meta)

    total = len(_index.get("tests_meta", []))
    log.info(f"✅ To'liq skanerlash tugadi: {total} test meta tiklandi")

    # Yangi chunked formatda saqlash
    await _save_index_chunks()
    log.info("✅ Migratsiya yakunlandi!")
    return new_meta


async def _load_meta() -> dict:
    if not ready(): return {}

    # 1. Pin dan o'qi
    try:
        chat = await _bot.get_chat(_cid)
        pin  = getattr(chat, "pinned_message", None)
        if pin:
            doc = getattr(pin, "document", None)
            if doc and "index_meta" in (doc.file_name or "").lower():
                data = await _read_file(doc.file_id)
                if isinstance(data, dict) and "index_chunks" in data:
                    log.info("index_meta pindan yuklandi")
                    return data
    except Exception as e:
        log.warning(f"Pin o'qish: {e}")

    # 2. Oxirgi 100 xabarni skanerlash
    try:
        probe = await _bot.send_message(_cid, ".", protect_content=False)
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)
        for mid in range(cur - 1, max(1, cur - 100), -1):
            try:
                fwd = await _bot.forward_message(_cid, _cid, mid)
                doc = getattr(fwd, "document", None)
                try:
                    await _bot.delete_message(_cid, fwd.message_id)
                except: pass
                if doc and "index_meta" in (doc.file_name or "").lower():
                    data = await _read_file(doc.file_id)
                    if isinstance(data, dict) and "index_chunks" in data:
                        log.info(f"index_meta topildi (msg {mid})")
                        await _pin_msg(mid)
                        return data
                await asyncio.sleep(0.05)
            except: pass
    except Exception as e:
        log.warning(f"Meta qidirish: {e}")
    return {}


async def _save_meta():
    """
    index_meta.json ni TG ga yuboradi va pin qiladi.
    AVVAL yangi xabar yuboradi, KEYIN eskisini o'chiradi.
    """
    global _can_pin
    if not ready(): return False
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

    old_msg_id = _meta.get("_last_meta_msg_id")
    try:
        # 1. AVVAL yangi xabar yuborish
        msg = await _bot.send_document(
            _cid,
            document=_buf(_meta, "index_meta.json"),
            caption=f"INDEX_META | {ts}",
            protect_content=False
        )
        # 2. Pin qilish
        if _can_pin:
            try:
                await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
            except:
                _can_pin = False

        # 3. KEYIN eskisini o'chirish
        if old_msg_id and old_msg_id != msg.message_id:
            try:
                await _bot.delete_message(_cid, old_msg_id)
            except: pass

        _meta["_last_meta_msg_id"] = msg.message_id
        _meta["_last_meta_fid"]    = msg.document.file_id
        return True
    except Exception as e:
        log.error(f"_save_meta: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# INDEX CHUNKS — xavfsiz saqlash
# ══════════════════════════════════════════════════════════════

async def _load_all_index_chunks_fast():
    """
    TEZKOR yuklash — faqat mavjud fid/msg_id dan o'qiydi.
    Kanal skanerlashsiz. Bot polling tezroq boshlanadi.
    Agar ma'lumotlar to'liq bo'lmasa — background da to'liq skan ishga tushadi.
    """
    chunks    = _meta.get("index_chunks", [])
    all_metas = []

    for ch in chunks:
        fid = ch.get("fid")
        mid = ch.get("msg_id")
        data = {}
        if fid:
            data = await _read_file(fid)
        if not data and mid:
            data = await _download_doc(mid)
        if not data:
            continue
        for m in data.get("tests_meta", []):
            if not any(x.get("test_id") == m.get("test_id") for x in all_metas):
                all_metas.append(m)
        for k, v in data.items():
            if k.startswith("test_") or k.startswith("fid_"):
                _index[k] = v

    _index["tests_meta"] = all_metas

    # Kutilgan va yuklangan sonini solishtirish
    expected = sum(ch.get("count", 0) for ch in chunks)
    actual   = len(all_metas)
    log.info(f"Tezkor yuklash: {actual} test meta (kutilgan: {expected})")

    # Agar to'liq emas — background da to'liq skanerlash
    need_full = (
        not all_metas
        or (expected > 0 and actual < expected * 0.5)
        or (expected == 0 and actual <= 1 and chunks)
    )
    if need_full:
        log.warning(f"Ma'lumotlar to'liq emas — background skanerlash boshlanadi...")
        asyncio.create_task(_background_full_rescan())


async def _background_full_rescan():
    """
    Background da to'liq kanal skanerlash.
    Bot polling ishlayotgan paytda amalga oshadi.
    """
    await asyncio.sleep(3)   # Polling boshlangandan keyin
    log.info("⬇️ Background to'liq skanerlash boshlandi...")
    result = await _migrate_from_old_index()
    if result:
        log.info(f"✅ Background skanerlash tugadi: "
                 f"{len(_index.get('tests_meta',[]))} test meta tiklandi")
    else:
        log.warning("Background skanerlash natija bermadi")


async def _load_all_index_chunks():
    chunks    = _meta.get("index_chunks", [])
    all_metas = []
    meta_updated = False

    for ch in chunks:
        fid  = ch.get("fid")
        mid  = ch.get("msg_id")
        data = {}

        # 1. fid orqali o'qi
        if fid:
            data = await _read_file(fid)
            if data and len(data.get("tests_meta", [])) == 0 and mid:
                # fid ishlamoqda lekin bo'sh natija — msg_id orqali ham tekshir
                data2 = await _download_doc(mid)
                if data2 and len(data2.get("tests_meta", [])) > 0:
                    data = data2
                    # fid ni yangilash
                    ch["fid"] = ""
                    meta_updated = True

        # 2. fid ishlamadi — msg_id orqali
        if not data or len(data.get("tests_meta", [])) == 0:
            if mid:
                data = await _download_doc(mid)
                if data:
                    # Yangi fid ni saqlash
                    ch["fid"] = ""
                    meta_updated = True

        if not data or not data.get("tests_meta"):
            log.warning(f"Index chunk {ch.get('n')} yuklanmadi yoki bo'sh")
            continue

        loaded = 0
        for m in data.get("tests_meta", []):
            if not any(x.get("test_id") == m.get("test_id") for x in all_metas):
                all_metas.append(m)
                loaded += 1
        for k, v in data.items():
            if k.startswith("test_") or k.startswith("fid_"):
                _index[k] = v
        log.info(f"  chunk {ch.get('n')}: {loaded} yangi + "
                 f"{len(data.get('tests_meta',[]))-loaded} mavjud test meta")

    # Kutilgan test soni bilan solishtirish
    expected_total = sum(ch.get("count", 0) for ch in chunks)
    actual_total   = len(all_metas)

    # Kanal skanerlash kerak bo'lgan holatlar:
    # 1. Hech narsa yuklanmadi
    # 2. Yuklanganlar kutilgandan 2x kam (chunk eskirgan)
    need_rescan = (
        not all_metas
        or (expected_total > 0 and actual_total < expected_total * 0.5)
        or (expected_total == 0 and actual_total <= 1 and chunks)
    )

    if need_rescan:
        log.warning(
            f"Chunk ma'lumotlari to'liq emas "
            f"(yuklandi: {actual_total}, kutilgan: {expected_total}) "
            f"— kanaldan qayta skanerlash..."
        )
        all_metas = await _recover_index_from_channel()
        meta_updated = True

    _index["tests_meta"] = all_metas
    log.info(f"Index chunks yuklandi: {len(all_metas)} test meta")


async def _recover_index_from_channel() -> list:
    """
    Kanaldan index_chunk_N.json fayllarini topib meta va msg_id larni tiklaydi.
    """
    if not ready(): return []
    log.info("Kanaldan index_chunk fayllar qidirilmoqda...")
    all_metas    = []
    new_chunks   = []
    seen_tids    = set()
    chunk_names  = {}   # {name: (mid, fid)}

    try:
        probe = await _bot.send_message(_cid, ".", protect_content=False)
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)

        for mid in range(cur - 1, max(1, cur - 2000), -1):
            try:
                fwd = await _bot.forward_message(_cid, _cid, mid)
                doc = getattr(fwd, "document", None)
                try:
                    await _bot.delete_message(_cid, fwd.message_id)
                except: pass
                if doc and doc.file_name:
                    fname = doc.file_name.lower()
                    if "index_chunk" in fname and fname.endswith(".json"):
                        if fname not in chunk_names:
                            chunk_names[fname] = (mid, doc.file_id)
                            log.info(f"  index_chunk topildi: {doc.file_name} (msg {mid})")
                await asyncio.sleep(0.05)
            except: pass

        # Har bir chunk ni yuklash
        for fname, (mid, fid) in sorted(chunk_names.items()):
            data = await _read_file(fid)
            if not data:
                data = await _download_doc(mid)
            if not data: continue

            # Chunk raqami
            import re as _re
            m = _re.search(r'(\d+)', fname)
            n = int(m.group(1)) if m else len(new_chunks) + 1

            for meta in data.get("tests_meta", []):
                tid = meta.get("test_id")
                if tid and tid not in seen_tids:
                    seen_tids.add(tid)
                    all_metas.append(meta)
            for k, v in data.items():
                if k.startswith("test_") or k.startswith("fid_"):
                    _index[k] = v

            new_chunks.append({
                "n":      n,
                "msg_id": mid,
                "fid":    fid,
                "count":  len(data.get("tests_meta", [])),
            })
            log.info(f"  chunk {n}: {len(data.get('tests_meta',[]))} test meta yuklandi")

        if new_chunks:
            _meta["index_chunks"] = sorted(new_chunks, key=lambda x: x["n"])
            log.info(f"✅ Kanaldan {len(all_metas)} test meta tiklandi "
                     f"({len(new_chunks)} chunk)")

    except Exception as e:
        log.error(f"_recover_index_from_channel: {e}")

    return all_metas


async def _save_index_chunks():
    """
    XAVFSIZ saqlash:
    1. Yangi chunk yuboriladi
    2. Faqat muvaffaqiyatli bo'lsa new_chunks ga qo'shiladi
    3. Barcha chunklar muvaffaqiyatli bo'lgandan keyin _save_meta()
    4. Faqat shundan keyin eski chunk o'chiriladi
    """
    async with _get_lock():
        from utils import ram_cache as ram

        # RAM dan yangilangan meta ni _index ga o'tkaz
        for m in _index.get("tests_meta", []):
            tid = m.get("test_id")
            if not tid: continue
            rm = ram.get_test_meta(tid)
            if not rm: continue
            for key in ("solve_count", "avg_score", "is_paused", "is_active",
                        "poll_time", "allowed_users", "title", "max_attempts"):
                if key in rm:
                    m[key] = rm[key]

        metas      = _index.get("tests_meta", [])
        groups     = [metas[i:i+INDEX_CHUNK_SIZE]
                      for i in range(0, max(len(metas), 1), INDEX_CHUNK_SIZE)]
        old_chunks = _meta.get("index_chunks", [])
        new_chunks = []
        ts         = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        all_ok     = True

        for i, group in enumerate(groups):
            chunk_data = {"n": i+1, "saved_at": ts, "tests_meta": group}
            for m in group:
                tid = m.get("test_id")
                if tid and _index.get(f"test_{tid}"):
                    msg_id = _index[f"test_{tid}"]
                    chunk_data[f"test_{tid}"] = msg_id
                    fk = f"fid_{msg_id}"
                    if _index.get(fk):
                        chunk_data[fk] = _index[fk]

            try:
                # 1. AVVAL yangi chunk yuborish
                msg = await _bot.send_document(
                    _cid,
                    document=_buf(chunk_data, f"index_chunk_{i+1}.json"),
                    caption=f"INDEX_CHUNK_{i+1} | {len(group)} test | {ts}",
                    protect_content=False
                )
                new_chunks.append({
                    "n":      i + 1,
                    "msg_id": msg.message_id,
                    "fid":    msg.document.file_id,
                    "count":  len(group),
                    "_old_mid": old_chunks[i]["msg_id"] if i < len(old_chunks) else None,
                })
                await asyncio.sleep(0.3)
            except Exception as e:
                log.error(f"index chunk {i+1} yuborish xato: {e}")
                all_ok = False
                # Eski chunkni saqlab qolish
                if i < len(old_chunks):
                    old = dict(old_chunks[i])
                    old["_old_mid"] = None   # o'chirmaslik uchun
                    new_chunks.append(old)

        # 2. _save_meta() — yangi chunk msg_id lar bilan
        meta_chunks = [
            {"n": c["n"], "msg_id": c["msg_id"], "fid": c["fid"], "count": c.get("count", 0)}
            for c in new_chunks
        ]
        _meta["index_chunks"] = meta_chunks
        meta_ok = await _save_meta()

        # 3. Faqat meta muvaffaqiyatli bo'lganda eski chunklar o'chiriladi
        if meta_ok:
            for c in new_chunks:
                old_mid = c.get("_old_mid")
                if old_mid and old_mid != c["msg_id"]:
                    try:
                        await _bot.delete_message(_cid, old_mid)
                        await asyncio.sleep(0.1)
                    except: pass

        log.info(f"Index chunks saqlandi: {len(new_chunks)} chunk, "
                 f"{len(metas)} test, ok={all_ok}, meta_ok={meta_ok}")
        return all_ok and meta_ok


async def _save_index():
    """Index ni saqlash — faqat o'zgarish bo'lganda"""
    global _index_dirty
    _index_dirty = False
    return await _save_index_chunks()


# ══════════════════════════════════════════════════════════════
# USERS LIST
# ══════════════════════════════════════════════════════════════

async def _load_users_list():
    global _users_dirty
    from utils import ram_cache as ram
    chunks = _meta.get("users_list_chunks", [])
    total  = 0

    if not chunks:
        # Chunk yo'q — kanaldan users_list fayllarni qidirish
        log.info("users_list_chunks yo'q — kanaldan qidirilmoqda...")
        await _recover_users_from_channel()
        return

    for chunk in chunks:
        fid  = chunk.get("fid")
        mid  = chunk.get("msg_id")
        data = {}
        if fid:
            data = await _read_file(fid)
        if not data and mid:
            data = await _download_doc(mid)
        if not data:
            _users_dirty = True
            log.warning(f"users_list chunk yuklanmadi: msg_id={mid}")
            continue
        users = data.get("users", {})
        cur   = ram.get_users()
        cur.update(users)
        ram.set_users(cur)
        total += len(users)

    if total == 0 and chunks:
        # Chunklar bor lekin yuklanmadi — kanaldan qidirish
        log.warning("users_list chunklar yuklanmadi — kanaldan qidirilmoqda...")
        await _recover_users_from_channel()
        return

    log.info(f"Users: {total} ta ({len(chunks)} chunk)")


async def _recover_users_from_channel():
    """Kanaldan users_list fayllarni topib yuklaydi"""
    global _users_dirty
    from utils import ram_cache as ram
    try:
        probe = await _bot.send_message(_cid, ".", protect_content=False)
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)
        all_users = {}
        new_chunks = []
        chunk_names_seen = set()

        for mid in range(cur - 1, max(1, cur - 3000), -1):
            try:
                fwd = await _bot.forward_message(_cid, _cid, mid)
                doc = getattr(fwd, "document", None)
                try:
                    await _bot.delete_message(_cid, fwd.message_id)
                except: pass
                if doc and doc.file_name:
                    fname = doc.file_name.lower()
                    if "users_list" in fname and fname.endswith(".json"):
                        if fname not in chunk_names_seen:
                            chunk_names_seen.add(fname)
                            data = await _read_file(doc.file_id)
                            if isinstance(data, dict) and data.get("users"):
                                all_users.update(data["users"])
                                new_chunks.append({
                                    "n":     len(new_chunks) + 1,
                                    "msg_id": mid,
                                    "fid":   doc.file_id,
                                    "count": len(data["users"]),
                                })
                                log.info(f"  users_list topildi: {len(data['users'])} user")
                await asyncio.sleep(0.05)
            except: pass

        if all_users:
            ram.set_users(all_users)
            _meta["users_list_chunks"] = new_chunks
            log.info(f"Kanaldan users tiklandi: {len(all_users)} ta, {len(new_chunks)} chunk")
        else:
            log.warning("Kanaldan users topilmadi")
            _users_dirty = True
    except Exception as e:
        log.error(f"_recover_users_from_channel: {e}")
        _users_dirty = True


async def _flush_users_list():
    """XAVFSIZ: avval yoz, keyin o'chir"""
    global _users_dirty
    from utils import ram_cache as ram
    users = ram.get_users()
    if not users: return

    async with _get_lock():
        chunks     = _meta.get("users_list_chunks", [])
        all_uids   = list(users.keys())
        uid_groups = [all_uids[i:i+500] for i in range(0, len(all_uids), 500)]
        new_chunks = []
        ts         = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

        for i, group in enumerate(uid_groups):
            chunk_users = {uid: users[uid] for uid in group if uid in users}
            old_mid     = chunks[i]["msg_id"] if i < len(chunks) else None
            try:
                msg = await _bot.send_document(
                    _cid,
                    document=_buf({"users": chunk_users, "count": len(chunk_users),
                                   "saved_at": ts}, f"users_list_{i+1}.json"),
                    caption=f"USERS_LIST_{i+1} | {len(chunk_users)} user | {ts}",
                    protect_content=False
                )
                new_chunks.append({
                    "n": i+1, "msg_id": msg.message_id,
                    "fid": msg.document.file_id, "count": len(chunk_users),
                    "_old_mid": old_mid
                })
                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"users_list chunk {i+1}: {e}")
                if i < len(chunks):
                    old = dict(chunks[i])
                    old["_old_mid"] = None
                    new_chunks.append(old)

        _meta["users_list_chunks"] = [
            {"n": c["n"], "msg_id": c["msg_id"], "fid": c["fid"], "count": c.get("count", 0)}
            for c in new_chunks
        ]
        meta_ok = await _save_meta()

        if meta_ok:
            for c in new_chunks:
                old_mid = c.get("_old_mid")
                if old_mid and old_mid != c["msg_id"]:
                    try:
                        await _bot.delete_message(_cid, old_mid)
                    except: pass

        _users_dirty = False
        log.info(f"Users saqlandi: {len(users)} ta, {len(new_chunks)} chunk")


# ══════════════════════════════════════════════════════════════
# USER STATS
# ══════════════════════════════════════════════════════════════

async def flush_dirty_user_stats():
    from utils import ram_cache as ram
    dirty_stats = ram.get_dirty_user_stats()
    if not dirty_stats: return

    chunks          = _meta.get("user_stats_chunks", [])
    dirty_chunk_ids = set()
    for uid_str in dirty_stats:
        for i, chunk in enumerate(chunks):
            if uid_str in chunk.get("uids", []):
                dirty_chunk_ids.add(i)
                break
        else:
            if chunks and len(chunks[-1].get("uids", [])) < 50:
                chunks[-1]["uids"].append(uid_str)
                dirty_chunk_ids.add(len(chunks) - 1)
            else:
                chunks.append({
                    "n": len(chunks)+1, "msg_id": None,
                    "fid": None, "uids": [uid_str]
                })
                dirty_chunk_ids.add(len(chunks) - 1)

    ts    = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    saved = False

    for i in dirty_chunk_ids:
        if i >= len(chunks): continue
        chunk       = chunks[i]
        chunk_stats = {}
        for uid_str in chunk.get("uids", []):
            s = ram.get_user_stats_cache(uid_str)
            if s:
                chunk_stats[uid_str] = s
        if not chunk_stats: continue

        old_mid = chunk.get("msg_id")
        try:
            # AVVAL yangi chunk
            msg = await _bot.send_document(
                _cid,
                document=_buf({"stats": chunk_stats, "saved_at": ts},
                              f"user_stats_{i+1}.json"),
                caption=f"USER_STATS_{i+1} | {len(chunk_stats)} user | {ts}",
                protect_content=False
            )
            # Muvaffaqiyatli bo'lsa eski ni o'chirish
            if old_mid and old_mid != msg.message_id:
                try:
                    await _bot.delete_message(_cid, old_mid)
                except: pass
            chunk["msg_id"] = msg.message_id
            chunk["fid"]    = msg.document.file_id
            saved = True
            for uid_str in chunk.get("uids", []):
                ram.clear_stats_dirty(uid_str)
            await asyncio.sleep(1)
        except Exception as e:
            log.error(f"user_stats chunk {i}: {e}")

    _meta["user_stats_chunks"] = chunks
    if saved:
        await _save_meta()
        log.info(f"User stats saqlandi")


async def _load_user_stats(uid_str):
    from utils import ram_cache as ram
    if ram.get_user_stats_cache(uid_str) is not None:
        return
    for chunk in _meta.get("user_stats_chunks", []):
        if uid_str not in chunk.get("uids", []):
            continue
        fid  = chunk.get("fid")
        mid  = chunk.get("msg_id")
        data = {}
        if fid:
            data = await _read_file(fid)
        if not data and mid:
            data = await _download_doc(mid)
        if not data: return
        for uid, s in data.get("stats", {}).items():
            if ram.get_user_stats_cache(uid) is None:
                ram.set_user_stats_cache(uid, s, dirty=False)
        return


# ══════════════════════════════════════════════════════════════
# TESTS STATS
# ══════════════════════════════════════════════════════════════

async def _load_tests_stats():
    global _stats_dirty
    fid = _meta.get("tests_stats_fid")
    mid = _meta.get("tests_stats_msg_id")
    if not mid: return
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)
    if not data:
        _stats_dirty = True
        return
    from utils import ram_cache as ram
    for tid, s in data.get("stats", {}).items():
        ram.update_test_meta(tid, {
            "solve_count": s.get("solve_count", 0),
            "avg_score":   s.get("avg_score", 0.0),
            "is_paused":   s.get("is_paused", False),
            "is_active":   s.get("is_active", True),
        })
        if s.get("solvers"):
            ram.load_solvers_to_ram(tid, s["solvers"])
    log.info(f"tests_stats: {len(data.get('stats',{}))} test yuklandi")


async def save_tests_stats():
    """
    XAVFSIZ: avval yoz, keyin o'chir.
    INDEX GA TEGMAYDI — faqat stats faylini yangilaydi.
    """
    global _stats_dirty
    if not ready(): return False
    from utils import ram_cache as ram
    metas  = ram.get_all_tests_meta()
    daily  = ram.get_daily()
    stats  = {}
    for m in metas:
        tid = m.get("test_id", "")
        if not tid: continue
        solvers = {}
        for uid_str, udata in daily.items():
            entry = udata.get("by_test", {}).get(tid)
            if entry and entry.get("attempts", 0) > 0:
                solvers[uid_str] = {
                    "attempts":   entry["attempts"],
                    "best_score": entry["best_score"],
                    "avg_score":  entry["avg_score"],
                    "all_pcts":   entry["all_pcts"],
                    "last_at":    entry.get("last_at", ""),
                }
        stats[tid] = {
            "solve_count": m.get("solve_count", 0),
            "avg_score":   m.get("avg_score", 0.0),
            "is_paused":   m.get("is_paused", False),
            "is_active":   m.get("is_active", True),
            "solvers":     solvers,
        }
    ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid = _meta.get("tests_stats_msg_id")
    try:
        # AVVAL yangi fayl
        msg = await _bot.send_document(
            _cid,
            document=_buf({"stats": stats, "saved_at": ts}, "tests_stats.json"),
            caption=f"TESTS_STATS | {len(stats)} test | {ts}",
            protect_content=False
        )
        _meta["tests_stats_msg_id"] = msg.message_id
        _meta["tests_stats_fid"]    = msg.document.file_id

        # _save_meta — LEKIN index chunk ga tegmaydi
        await _save_meta()

        # Muvaffaqiyatli bo'lgach eski o'chir
        if old_mid and old_mid != msg.message_id:
            try:
                await _bot.delete_message(_cid, old_mid)
            except: pass

        _stats_dirty = False
        log.info(f"tests_stats: {len(stats)} test saqlandi")
        return True
    except Exception as e:
        log.error(f"save_tests_stats: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# LEADERBOARD
# ══════════════════════════════════════════════════════════════

async def _load_leaderboard():
    from utils import ram_cache as ram
    fid = _meta.get("leaderboard_fid")
    mid = _meta.get("leaderboard_msg_id")
    if not mid: return
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)
    if data:
        ram.set_global_leaderboard(data.get("top20", []))
        log.info(f"Leaderboard: {len(data.get('top20',[]))} ta")


async def save_leaderboard():
    from utils import ram_cache as ram
    top20   = ram.update_global_leaderboard()
    if not top20: return
    ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid = _meta.get("leaderboard_msg_id")
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf({"top20": top20, "saved_at": ts}, "leaderboard.json"),
            caption=f"LEADERBOARD | top {len(top20)} | {ts}",
            protect_content=False
        )
        _meta["leaderboard_msg_id"] = msg.message_id
        _meta["leaderboard_fid"]    = msg.document.file_id
        await _save_meta()
        if old_mid and old_mid != msg.message_id:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        log.info(f"Leaderboard saqlandi: {len(top20)} ta")
    except Exception as e:
        log.error(f"save_leaderboard: {e}")


async def save_group_leaderboard():
    from utils import ram_cache as ram
    if not ram.is_group_lb_dirty(): return
    lb    = ram.get_group_leaderboard()
    if not lb: return
    today   = str(date.today())
    ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid = _meta.get("group_lb_msg_id")
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf({"top20": lb, "date": today, "saved_at": ts},
                          f"group_lb_{today}.json"),
            caption=f"GROUP_LB | {today} | top {len(lb)} | {ts}",
            protect_content=False
        )
        _meta["group_lb_msg_id"] = msg.message_id
        _meta["group_lb_fid"]    = msg.document.file_id
        _meta["group_lb_date"]   = today
        await _save_meta()
        if old_mid and old_mid != msg.message_id:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        ram.clear_group_lb_dirty()
        log.info(f"Guruh leaderboard saqlandi: {len(lb)} ta")
    except Exception as e:
        log.error(f"save_group_leaderboard: {e}")


async def load_group_leaderboard():
    from utils import ram_cache as ram
    today   = str(date.today())
    lb_date = _meta.get("group_lb_date", "")
    if lb_date != today:
        ram.clear_group_leaderboard()
        return
    fid = _meta.get("group_lb_fid")
    mid = _meta.get("group_lb_msg_id")
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)
    if data:
        from utils.ram_cache import _set
        _set("group_leaderboard", data.get("top20", []))


# ══════════════════════════════════════════════════════════════
# AUTO FLUSH LOOP — MINIMAL YOZUV
# ══════════════════════════════════════════════════════════════

async def auto_flush_loop():
    """
    QOIDA: auto_flush faqat stats va users ni saqlaydi.
    INDEX ni SAQLAMAYDI — u faqat test qo'shilganda/o'zgartirilganda saqlanadi.
    Soatlik: leaderboard va user_stats.
    Kunlik: backup.
    """
    await asyncio.sleep(60)
    last_hourly = datetime.now(UTC)
    last_index  = datetime.now(UTC)

    while True:
        try:
            await asyncio.sleep(300)   # 5 daqiqa (oldin 2 edi)
            now = datetime.now(UTC)

            # Stats — faqat o'zgarga
            if _stats_dirty:
                log.info("auto_flush: tests_stats...")
                await save_tests_stats()

            # Users — faqat o'zgarga
            if _users_dirty:
                log.info("auto_flush: users_list...")
                await _flush_users_list()

            # Index — faqat o'zgarga VA kamida 10 daqiqa o'tgan bo'lsa
            if _index_dirty and (now - last_index).total_seconds() >= 600:
                log.info("auto_flush: index chunks...")
                await _save_index()
                last_index = now

            # Soatlik
            if (now - last_hourly).total_seconds() >= 3600:
                last_hourly = now
                log.info("Soatlik flush...")
                await flush_dirty_user_stats()
                await save_leaderboard()
                await save_group_leaderboard()
                await save_known_groups()
                log.info("Soatlik flush tugadi")

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"auto_flush: {e}")


# ══════════════════════════════════════════════════════════════
# OTP
# ══════════════════════════════════════════════════════════════

_otp_store: dict = {}

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
    if not entry: return {"ok": False, "error": "Kod topilmadi"}
    if entry["expires_at"] < time.time():
        del _otp_store[code]
        return {"ok": False, "error": "Kod muddati tugagan"}
    if entry["used"]: return {"ok": False, "error": "Kod ishlatilgan"}
    entry["used"] = True
    return {"ok": True, "test_id": entry["test_id"], "uid": entry["uid"]}

def get_otp_info(code: str) -> dict:
    import time
    entry = _otp_store.get(code.upper().strip())
    if not entry or entry["expires_at"] < time.time(): return {}
    return entry


# ══════════════════════════════════════════════════════════════
# WEB SYNC
# ══════════════════════════════════════════════════════════════

async def web_sync_loop():
    await asyncio.sleep(30)
    consecutive_errors = 0
    while True:
        try:
            await asyncio.sleep(43200)
            if not ready(): continue
            from utils import ram_cache as ram
            try:
                new_meta = await asyncio.wait_for(_load_meta(), timeout=20)
            except asyncio.TimeoutError:
                consecutive_errors += 1
                continue
            if not new_meta: continue
            consecutive_errors = 0

            new_metas    = []
            new_test_ids = {}
            for ch in new_meta.get("index_chunks", []):
                fid  = ch.get("fid")
                mid  = ch.get("msg_id")
                data = {}
                if fid:
                    data = await _read_file(fid)
                if not data and mid:
                    data = await _download_doc(mid)
                for m in data.get("tests_meta", []):
                    if not any(x.get("test_id") == m.get("test_id") for x in new_metas):
                        new_metas.append(m)
                for k, v in data.items():
                    if k.startswith("test_"):
                        new_test_ids[k] = v

            ram_ids = {t.get("test_id") for t in ram.get_all_tests_meta()}
            added   = 0
            for meta in new_metas:
                tid = meta.get("test_id")
                if not tid or tid in ram_ids: continue
                clean = {k: v for k, v in meta.items() if k != "questions"}
                ram.add_test_meta(clean)
                if not any(m.get("test_id") == tid for m in _index.get("tests_meta", [])):
                    _index.setdefault("tests_meta", []).insert(0, clean)
                if new_test_ids.get(f"test_{tid}"):
                    _index[f"test_{tid}"] = new_test_ids[f"test_{tid}"]
                added += 1
            if added:
                log.info(f"Web sync: {added} yangi test")
                mark_index_dirty()

        except asyncio.CancelledError:
            break
        except Exception as e:
            consecutive_errors += 1
            log.error(f"web_sync_loop: {e}")
            if consecutive_errors >= 5:
                await asyncio.sleep(900)
                consecutive_errors = 0


# ══════════════════════════════════════════════════════════════
# TESTLAR
# ══════════════════════════════════════════════════════════════

def get_tests_meta():
    return _index.get("tests_meta", [])

def get_test_meta(tid):
    return next((t for t in get_tests_meta()
                 if t.get("test_id") == tid and t.get("is_active", True)), {})

async def get_test_full(tid):
    from utils import ram_cache as ram

    # 1. RAM cache
    if tid in _tests_cache:
        ram.touch_test_access(tid)
        return _tests_cache[tid]
    cached = ram.get_cached_questions(tid)
    if cached:
        _tests_cache[tid] = cached
        return cached

    # 2. fid orqali (tez)
    msg_id  = _index.get(f"test_{tid}")
    fid_key = f"fid_{msg_id}" if msg_id else None
    if msg_id and fid_key and _index.get(fid_key):
        data = await _read_file(_index[fid_key])
        if data and data.get("questions"):
            _tests_cache[tid] = data
            ram.cache_questions(tid, data)
            return data
        _index.pop(fid_key, None)

    # 3. msg_id orqali
    if msg_id:
        data = await _download_doc(msg_id)
        if data and data.get("questions"):
            _tests_cache[tid] = data
            ram.cache_questions(tid, data)
            return data

    # 4. Barcha chunklarni skan (so'nggi chora)
    log.info(f"{tid} — chunkdan qidirilmoqda...")
    for ch in _meta.get("index_chunks", []):
        fid   = ch.get("fid")
        mid   = ch.get("msg_id")
        cdata = {}
        if fid:
            cdata = await _read_file(fid)
        if not cdata and mid:
            cdata = await _download_doc(mid)
        new_mid = cdata.get(f"test_{tid}")
        if new_mid:
            _index[f"test_{tid}"] = new_mid
            data = await _download_doc(new_mid)
            if data and data.get("questions"):
                _tests_cache[tid] = data
                ram.cache_questions(tid, data)
                log.info(f"{tid} chunk skanidan topildi")
                return data

    log.warning(f"{tid} topilmadi")
    return {}

async def get_tests():
    return _index.get("tests_meta", [])

async def save_test_full(test):
    if not ready(): return False
    tid = test.get("test_id", "")
    try:
        qc  = len(test.get("questions", []))
        msg = await _bot.send_document(
            _cid,
            document=_buf(test, f"test_{tid}.json"),
            caption=f"TEST | {test.get('title','?')} | {qc} savol | {tid}",
            protect_content=False
        )
        _index[f"test_{tid}"]           = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
        _tests_cache[tid] = test

        meta = {k: v for k, v in test.items() if k != "questions"}
        meta["question_count"] = qc
        metas = [m for m in _index.get("tests_meta", []) if m.get("test_id") != tid]
        metas.insert(0, meta)
        _index["tests_meta"] = metas

        from utils import ram_cache as ram
        ram.add_test_meta(meta)
        ram.cache_questions(tid, test)

        # Index ni saqlash + dirty flag
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_test_full: {e}")
        return False

async def save_deleted_test_backup(test):
    if not ready(): return
    tid = test.get("test_id", "NOID")
    _tests_cache.pop(tid, None)
    try:
        await _bot.send_document(
            _cid,
            document=_buf(test, f"DELETED_test_{tid}.json"),
            caption=f"DELETED: {test.get('title','?')} | {tid}",
            protect_content=False
        )
    except Exception as e:
        log.error(f"delete backup: {e}")

async def delete_test_tg(tid):
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m["is_active"] = False
            break
    _tests_cache.pop(tid, None)
    await _save_index()
    mark_stats_dirty()

async def update_test_meta_tg(tid: str, updates: dict):
    """Meta yangilash — INDEX ni saqlaydi"""
    from utils import ram_cache as ram

    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m.update(updates)
            break

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

    await _save_index()
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


# ══════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════

async def save_settings(settings_dict):
    if not ready(): return False
    ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid = _meta.get("settings_msg_id")
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf({"settings": settings_dict, "saved_at": ts}, "settings.json"),
            caption=f"SETTINGS | {ts}",
            protect_content=False
        )
        _meta["settings_msg_id"] = msg.message_id
        _meta["settings_fid"]    = msg.document.file_id
        await _save_meta()
        if old_mid and old_mid != msg.message_id:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        return True
    except Exception as e:
        log.error(f"save_settings: {e}")
        return False

async def get_settings_tg():
    fid = _meta.get("settings_fid")
    mid = _meta.get("settings_msg_id")
    if not mid: return {}
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)
    return data.get("settings", {}) if isinstance(data, dict) else {}


# ══════════════════════════════════════════════════════════════
# GURUHLAR
# ══════════════════════════════════════════════════════════════

async def save_known_groups():
    """Bot admin bo'lgan guruhlarni TG ga JSON sifatida saqlaydi."""
    if not ready(): return False
    from utils import ram_cache as ram
    groups  = ram.get_known_groups()
    if not groups: return True
    ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid = _meta.get("known_groups_msg_id")
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf({"groups": groups, "count": len(groups), "saved_at": ts},
                          "known_groups.json"),
            caption=f"KNOWN_GROUPS | {len(groups)} guruh | {ts}",
            protect_content=False
        )
        _meta["known_groups_msg_id"] = msg.message_id
        _meta["known_groups_fid"]    = msg.document.file_id
        await _save_meta()
        if old_mid and old_mid != msg.message_id:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        log.info(f"known_groups saqlandi: {len(groups)} ta")
        return True
    except Exception as e:
        log.error(f"save_known_groups: {e}")
        return False


async def load_known_groups():
    """Bot yoqilganda guruhlarni TG dan yuklaydi.
    known_groups_msg_id yo'q bo'lsa kanaldan qidiradi."""
    from utils import ram_cache as ram
    fid = _meta.get("known_groups_fid")
    mid = _meta.get("known_groups_msg_id")

    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)

    # msg_id yo'q yoki yuklanmadi — kanaldan qidirish
    if not data:
        if not ready(): return
        try:
            probe = await _bot.send_message(_cid, ".", protect_content=False)
            cur   = probe.message_id
            await _bot.delete_message(_cid, cur)
            for scan_mid in range(cur - 1, max(1, cur - 2000), -1):
                try:
                    fwd = await _bot.forward_message(_cid, _cid, scan_mid)
                    doc = getattr(fwd, "document", None)
                    try:
                        await _bot.delete_message(_cid, fwd.message_id)
                    except: pass
                    if doc and doc.file_name and "known_groups" in doc.file_name.lower():
                        data = await _read_file(doc.file_id)
                        if isinstance(data, dict) and data.get("groups"):
                            _meta["known_groups_msg_id"] = scan_mid
                            _meta["known_groups_fid"]    = doc.file_id
                            log.info(f"known_groups kanaldan topildi (msg {scan_mid})")
                            break
                    await asyncio.sleep(0.05)
                except: pass
        except Exception as e:
            log.warning(f"load_known_groups kanal skani: {e}")

    if not data: return
    groups = data.get("groups", {})
    if groups:
        ram.set_known_groups(groups)
        log.info(f"known_groups yuklandi: {len(groups)} ta guruh")


# ══════════════════════════════════════════════════════════════
# BACKUP
# ══════════════════════════════════════════════════════════════

async def upload_backup(daily_data, date_str):
    if not ready(): return 0
    try:
        r_count = sum(len(v.get("by_test", {})) for v in daily_data.values())
        ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg     = await _bot.send_document(
            _cid,
            document=_buf({
                "date": date_str, "saved_at": ts,
                "users": len(daily_data), "results": r_count,
                "data":  daily_data,
            }, f"backup_{date_str}.json"),
            caption=f"BACKUP | {date_str} | {len(daily_data)} user | {r_count} natija",
            protect_content=False
        )
        _meta.setdefault("backups", {})[date_str] = msg.message_id
        await _save_meta()
        log.info(f"Backup: {date_str}")
        return msg.message_id
    except Exception as e:
        log.error(f"backup: {e}")
        return 0

async def get_backup(date_str):
    mid = _meta.get("backups", {}).get(date_str)
    if not mid: return {}
    data = await _download_doc(mid)
    return data.get("data", {}) if isinstance(data, dict) else {}

def get_backup_dates():
    return sorted(_meta.get("backups", {}).keys(), reverse=True)


# ══════════════════════════════════════════════════════════════
# MANUAL FLUSH
# ══════════════════════════════════════════════════════════════

async def manual_flush(daily_data, users, settings=None):
    results = []
    if not ready():
        return ["❌ TG kanal ulanmagan"]
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
        from datetime import date as _date
        today = str(_date.today())
        mid   = await upload_backup(daily_data, f"{today}_manual")
        results.append(f"{'✅' if mid else '❌'} Backup: {len(daily_data)} user")
    return results

def get_index_info():
    return {
        "tests_count":       len(_index.get("tests_meta", [])),
        "cached_tests":      len(_tests_cache),
        "index_chunks":      len(_meta.get("index_chunks", [])),
        "user_list_chunks":  len(_meta.get("users_list_chunks", [])),
        "user_stats_chunks": len(_meta.get("user_stats_chunks", [])),
        "backups":           len(_meta.get("backups", {})),
        "can_pin":           _can_pin,
        "stats_dirty":       _stats_dirty,
        "users_dirty":       _users_dirty,
        "index_dirty":       _index_dirty,
    }


# ══════════════════════════════════════════════════════════════
# YORDAMCHILAR
# ══════════════════════════════════════════════════════════════

async def _pin_msg(msg_id: int):
    global _can_pin
    if not _can_pin: return
    try:
        await _bot.pin_chat_message(_cid, msg_id, disable_notification=True)
    except:
        _can_pin = False


async def _download_doc(msg_id):
    try:
        fwd = await _bot.forward_message(_cid, _cid, int(msg_id))
        doc = getattr(fwd, "document", None)
        try:
            await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        if doc:
            return await _read_file(doc.file_id)
    except Exception as e:
        log.error(f"download_doc {msg_id}: {e}")
    return {}


async def _read_file(file_id):
    try:
        f   = await _bot.get_file(file_id)
        buf = io.BytesIO()
        await _bot.download_file(f.file_path, destination=buf)
        buf.seek(0)
        return json.loads(buf.read().decode())
    except Exception as e:
        log.error(f"read_file: {e}")
        return {}


def _buf(data, name):
    from aiogram.types import BufferedInputFile
    raw = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")).encode()
    return BufferedInputFile(raw, filename=name)
