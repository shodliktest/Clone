"""
SUPABASE_DB_SYNC — Streamlit uchun SINXRON Supabase yordamchisi
==================================================================
Streamlit skripti async emas (oddiy sinxron Python), shuning uchun
bot tomonidagi `utils/supabase_client.py` (asyncio executor bilan
o'ralgan) o'rniga bu yerda supabase-py ning o'zini TO'G'RIDAN-TO'G'RI
chaqiramiz — hech qanday HTTP-relay, forward, polling kerak emas.

Bot (aiogram, async) va Streamlit (sinxron) endi BIR XIL Postgres
bazasiga ikkita mustaqil yo'l bilan kirishadi — bu eng oddiy va eng
ishonchli arxitektura.
"""

import streamlit as st


@st.cache_resource
def _get_client():
    from supabase import create_client
    from config import SUPABASE_URL, SUPABASE_KEY
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_test_full_sync(tid: str) -> dict:
    """Bitta testni (meta + savollar) to'g'ridan-to'g'ri Supabase'dan o'qiydi."""
    client = _get_client()
    if not client:
        return {}
    try:
        res = client.table("tests").select("*").eq("test_id", tid).limit(1).execute()
        rows = res.data or []
        if not rows:
            return {}
        row = rows[0]
        full = dict(row.get("meta") or {})
        full["test_id"]   = row["test_id"]
        full["title"]     = row.get("title", full.get("title", ""))
        full["questions"] = row.get("questions") or []
        return full
    except Exception:
        return {}


def save_test_full_sync(test: dict) -> bool:
    """Streamlit tomonidan test yaratish/tahrirlash uchun (agar kerak bo'lsa)."""
    client = _get_client()
    if not client:
        return False
    tid = test.get("test_id", "")
    if not tid:
        return False
    try:
        qc   = len(test.get("questions", []))
        meta = {k: v for k, v in test.items() if k not in ("questions", "test_id", "title")}
        row = {
            "test_id":        tid,
            "title":          test.get("title", ""),
            "questions":      test.get("questions", []),
            "meta":           meta,
            "question_count": qc,
            "is_active":      test.get("is_active", True),
            "is_paused":      test.get("is_paused", False),
            "solve_count":    test.get("solve_count", 0),
            "avg_score":      float(test.get("avg_score") or 0),
        }
        client.table("tests").upsert(row, on_conflict="test_id").execute()
        return True
    except Exception:
        return False


def get_tests_meta_sync() -> list:
    """Barcha faol testlar ro'yxati (savollarsiz)."""
    client = _get_client()
    if not client:
        return []
    try:
        res = client.table("tests").select(
            "test_id,title,meta,question_count,is_active,is_paused,solve_count,avg_score"
        ).eq("is_active", True).execute()
        rows = res.data or []
        out = []
        for r in rows:
            m = dict(r.get("meta") or {})
            m.update({
                "test_id":        r["test_id"],
                "title":          r.get("title", ""),
                "question_count": r.get("question_count", 0),
                "is_active":      r.get("is_active", True),
                "is_paused":      r.get("is_paused", False),
                "solve_count":    r.get("solve_count", 0),
                "avg_score":      float(r.get("avg_score") or 0),
            })
            out.append(m)
        return out
    except Exception:
        return []


def upload_backup_sync(daily_data: dict, date_str: str) -> bool:
    """Admin panel 'Kanalga yuborish' tugmasi uchun — kunlik natijalarni
    Supabase'ga to'g'ridan-to'g'ri (sinxron) yozadi."""
    client = _get_client()
    if not client:
        return False
    try:
        r_count = sum(len(v.get("by_test", {})) for v in daily_data.values())
        client.table("backups").upsert({
            "date_str": date_str,
            "data": {"users": len(daily_data), "results": r_count, "data": daily_data},
        }, on_conflict="date_str").execute()
        return True
    except Exception:
        return False
