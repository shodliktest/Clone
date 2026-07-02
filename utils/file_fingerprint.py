"""
FILE_FINGERPRINT — avval yuklangan fayllarni tanish
======================================================
Maqsad: kimdir (yoki hatto boshqa foydalanuvchi) bir xil faylni
qaytadan botga yuklasa, bot uni tanib "bu fayl allaqachon test
sifatida saqlangan, o'shani ishlataymi?" deb so'raydi — AI/parse
qayta ishlamaydi, vaqt va so'rov tejaladi.

Tanish MATN MAZMUNIGA qarab ishlaydi (fayl nomiga emas), shuning
uchun fayl boshqa nom bilan qayta yuklansa ham tanib oladi.
"""

import hashlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def compute_file_hash(path: str) -> str:
    """
    Fayl matn mazmuniga asoslangan barqaror hash.
    Binary bайtlarga emas — parse qilingan matn/savollarga qaraymiz,
    chunki bitta xil savollar boshqa fayl formatida (masalan PDF
    o'rniga DOCX) yuklansa ham tanilishi kerak bo'lishi mumkin.
    Hozircha oddiy va ishonchli variant — xom fayl bytelarining SHA-256.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_questions_hash(questions: list) -> str:
    """
    Parse qilingan SAVOLLAR asosidagi hash — fayl formati boshqa
    bo'lsa ham (masalan avval .docx, endi shu savollar .pdf sifatida),
    agar savol matnlari bir xil bo'lsa, baribir tanib oladi.
    Bu compute_file_hash dan ko'ra ko'proq "aqlli" taqqoslash.
    """
    h = hashlib.sha256()
    for q in questions:
        text = (q.get("question") or q.get("text") or "").strip().lower()
        opts = "|".join(str(o).strip().lower() for o in (q.get("options") or []))
        h.update(f"{text}::{opts}".encode("utf-8"))
    return h.hexdigest()


async def find_existing_by_hash(file_hash: str) -> dict:
    """Bazadan shu hash bo'yicha avval saqlangan testni qidiradi."""
    from utils import supabase_client as sb
    from utils import tg_db

    if not tg_db.ready():
        return {}
    try:
        row = await sb.select_one("file_fingerprints", "file_hash", file_hash)
        if not row:
            return {}
        tid = row.get("test_id")
        test = await tg_db.get_test_full(tid) if tid else {}
        if not test:
            return {}
        return {
            "test_id":        tid,
            "title":          test.get("title", ""),
            "question_count": len(test.get("questions", [])),
            "upload_count":   row.get("upload_count", 1),
            "original_name":  row.get("original_name", ""),
        }
    except Exception as e:
        log.warning(f"find_existing_by_hash: {e}")
        return {}


async def register_fingerprint(file_hash: str, test_id: str, file_name: str,
                                uploaded_by: int, file_size: int = 0):
    """Yangi test yaratilgandan keyin, uning fayl-hashini bazaga yozadi."""
    from utils import supabase_client as sb
    from utils import tg_db

    if not tg_db.ready():
        return
    try:
        await sb.upsert("file_fingerprints", {
            "file_hash":     file_hash,
            "test_id":       test_id,
            "original_name": file_name,
            "uploaded_by":   int(uploaded_by) if uploaded_by else None,
            "file_size":     file_size,
        }, on_conflict="file_hash")
    except Exception as e:
        log.warning(f"register_fingerprint: {e}")


async def bump_fingerprint_seen(file_hash: str):
    """Fayl qaytadan yuklanganda upload_count va last_seen_at ni oshiradi."""
    from utils import supabase_client as sb
    from utils import tg_db
    from datetime import datetime, timezone

    if not tg_db.ready():
        return
    try:
        row = await sb.select_one("file_fingerprints", "file_hash", file_hash)
        if not row:
            return
        await sb.update("file_fingerprints", "file_hash", file_hash, {
            "upload_count": int(row.get("upload_count", 1)) + 1,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        log.warning(f"bump_fingerprint_seen: {e}")
