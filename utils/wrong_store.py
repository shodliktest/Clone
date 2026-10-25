"""
❌ XATO JAVOBLAR OMBORI
=======================
• Xato savollar JSON fayl sifatida Telegram kanaliga (config.USER_FALSE_ID) tashlanadi.
• Qaysi xabar (message_id/file_id) qaysi user + testga tegishli ekani Supabase'dagi
  `user_wrong_answers` jadvalida (indeks) turadi — kanal faqat "arzon saqlash joyi".
• Bitta (user, test) juftligi uchun bitta yozuv: qayta yechilganda yangilanadi.
• Har user uchun oxirgi WRONG_KEEP_PER_USER ta test saqlanadi, eskilari o'chadi.
Barcha funksiyalar xato bersa ham asosiy oqimni BUZMAYDI (False/None qaytaradi).
"""
import io
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)
TABLE = "user_wrong_answers"


def channel_id() -> int:
    try:
        from config import USER_FALSE_ID
        return int(USER_FALSE_ID or 0)
    except Exception:
        return 0


def enabled() -> bool:
    from utils import tg_db
    return bool(channel_id()) and tg_db.ready()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def wrong_indexes(scored: dict) -> list:
    """Javob BERILGAN, lekin noto'g'ri savollar indekslari."""
    out = []
    for r in scored.get("detailed_results", []) or []:
        ua = r.get("user_answer")
        answered = ua is not None and str(ua).strip() != ""
        if answered and not r.get("is_correct"):
            out.append(int(r.get("question_index", -1)))
    return [i for i in out if i >= 0]


def _clean_question(q: dict, user_answer=None) -> dict:
    keep = ("question", "text", "type", "options", "correct", "explanation",
            "points", "photo", "image", "accepted_answers")
    d = {k: q[k] for k in keep if k in q}
    if user_answer is not None:
        d["user_answer"] = user_answer
    return d


# ── Supabase indeks ─────────────────────────────────────────
async def list_wrong(uid: int) -> list:
    """Userning xatolari bor testlari (eng yangisi birinchi)."""
    from utils import supabase_client as sb, tg_db
    if not tg_db.ready():
        return []
    try:
        return await sb.select(TABLE, filters={"user_id": int(uid)},
                               order="updated_at", desc=True)
    except Exception as e:
        log.error("wrong list_wrong(%s): %s", uid, e)
        return []


async def _get_row(uid: int, tid: str):
    from utils import supabase_client as sb
    try:
        rows = await sb.select(TABLE, filters={"user_id": int(uid), "test_id": tid}, limit=1)
        return rows[0] if rows else None
    except Exception as e:
        log.error("wrong _get_row: %s", e)
        return None


async def _delete_msg(bot, message_id):
    if not message_id:
        return
    try:
        await bot.delete_message(channel_id(), int(message_id))
    except Exception as e:
        log.debug("wrong kanal xabarini o'chirib bo'lmadi %s: %s", message_id, e)


async def delete_wrong(bot, uid: int, tid: str) -> bool:
    from utils import supabase_client as sb
    row = await _get_row(uid, tid)
    try:
        await sb.delete_where(TABLE, {"user_id": int(uid), "test_id": tid})
    except Exception as e:
        log.error("wrong delete_wrong: %s", e)
        return False
    if row:
        await _delete_msg(bot, row.get("message_id"))
    return True


# ── Saqlash ─────────────────────────────────────────────────
async def _store(bot, uid: int, tid: str, title: str, questions: list,
                 total: int, pct, poll_time: int = 30) -> bool:
    """Savollarni kanalga tashlaydi va indeksni yangilaydi."""
    from aiogram.types import BufferedInputFile
    from utils import supabase_client as sb
    payload = {
        "v": 1, "user_id": int(uid), "test_id": tid, "title": title,
        "saved_at": _now(), "percentage": pct, "total": total,
        "poll_time": poll_time, "questions": questions,
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    old = await _get_row(uid, tid)
    try:
        msg = await bot.send_document(
            channel_id(),
            BufferedInputFile(raw, filename=f"{uid}_{tid}.json"),
            caption=f"uid={uid} | test={tid} | xato={len(questions)}",
            disable_notification=True, protect_content=False,
        )
    except Exception as e:
        log.error("wrong: kanalga yuborilmadi (bot kanalda ADMIN ekanini va USER_FALSE_ID ni tekshiring): %s", e)
        return False
    row = {
        "user_id": int(uid), "test_id": tid, "title": (title or tid)[:200],
        "message_id": msg.message_id,
        "file_id": msg.document.file_id if msg.document else None,
        "wrong_count": len(questions), "total": total, "updated_at": _now(),
    }
    try:
        await sb.upsert(TABLE, row, on_conflict="user_id,test_id")
    except Exception as e:
        log.error("wrong: indeks yozilmadi (supabase_patch_v16.sql ishga tushirilganmi?): %s", e)
        await _delete_msg(bot, msg.message_id)
        return False
    if old:
        await _delete_msg(bot, old.get("message_id"))
    await _trim(bot, uid)
    return True


async def _trim(bot, uid: int):
    """Har user uchun faqat oxirgi N ta test xatolari qoladi."""
    try:
        from config import WRONG_KEEP_PER_USER
        keep = int(WRONG_KEEP_PER_USER or 0)
    except Exception:
        keep = 0
    if keep <= 0:
        return
    rows = await list_wrong(uid)
    from utils import supabase_client as sb
    for r in rows[keep:]:
        try:
            await sb.delete_where(TABLE, {"user_id": int(uid), "test_id": r["test_id"]})
            await _delete_msg(bot, r.get("message_id"))
        except Exception as e:
            log.debug("wrong trim: %s", e)


async def save_after_test(bot, uid: int, test: dict, qs: list, scored: dict) -> bool:
    """Test yakunlangach chaqiriladi (fon vazifasi sifatida). Xato bo'lmasa eski yozuvni tozalaydi."""
    try:
        if not enabled() or test.get("is_retry"):
            return False
        tid = str(test.get("test_id") or "")
        if not tid:
            return False
        idxs = wrong_indexes(scored)
        if not idxs:
            await delete_wrong(bot, uid, tid)     # hammasi to'g'ri — xatolar qolmadi
            return True
        det = {int(r["question_index"]): r for r in scored.get("detailed_results", [])}
        questions = [_clean_question(qs[i], det.get(i, {}).get("user_answer"))
                     for i in idxs if i < len(qs)]
        return await _store(bot, uid, tid, test.get("title", tid), questions,
                            total=len(qs), pct=scored.get("percentage", 0),
                            poll_time=int(test.get("poll_time", 30) or 30))
    except Exception as e:
        log.error("wrong save_after_test uid=%s: %s", uid, e)
        return False


async def load_wrong(bot, uid: int, tid: str):
    """Kanal faylini o'qib, {title, questions, ...} qaytaradi (yo'q bo'lsa None)."""
    row = await _get_row(uid, tid)
    if not row or not row.get("file_id"):
        return None
    try:
        buf = await bot.download(row["file_id"])
        data = json.loads(buf.read().decode("utf-8"))
        if int(data.get("user_id", uid)) != int(uid):      # begona fayl bo'lib qolmasin
            return None
        return data
    except Exception as e:
        log.error("wrong load_wrong(%s,%s): %s", uid, tid, e)
        return None


async def update_after_retry(bot, uid: int, orig_tid: str, base: dict, remaining: list) -> bool:
    """Qayta yechilgach: hali xato qolganlarini yozadi, qolmagan bo'lsa yozuvni o'chiradi."""
    try:
        if not remaining:
            return await delete_wrong(bot, uid, orig_tid)
        clean = [_clean_question(q) for q in remaining]
        return await _store(bot, uid, orig_tid, base.get("title", orig_tid), clean,
                            total=int(base.get("total", len(clean))),
                            pct=base.get("percentage", 0),
                            poll_time=int(base.get("poll_time", 30) or 30))
    except Exception as e:
        log.error("wrong update_after_retry: %s", e)
        return False
