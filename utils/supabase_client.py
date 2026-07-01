"""
SUPABASE_CLIENT — yengil REST client (PostgREST orqali)
=========================================================
supabase-py kutubxonasi ichki HTTP so'rovlarni sinxron bajaradi.
aiogram butunlay async bo'lgani uchun, har bir chaqiruvni
thread executor'da ishga tushiramiz — bu event loop'ni blok qilmaydi.

Nega alohida fayl: tg_db.py faqat yuqori darajadagi (business logic)
funksiyalarni saqlaydi, "qanday ulanish" tafsilotlari shu yerda.
"""

import asyncio
import logging
import functools

log = logging.getLogger(__name__)

_client = None
_executor_lock = None


def init_client(url: str, key: str):
    """Supabase client ni bir marta yaratadi (lazy singleton)."""
    global _client
    if _client is not None:
        return _client
    from supabase import create_client
    _client = create_client(url, key)
    log.info("Supabase client tayyor")

    # ── AVTOMATIK JADVALLARNI TEKSHIRISH VA YARATISH ──
    try:
        _client.rpc("create_missing_tables", {}).execute()
        log.info("✅ Jadvallar avtomatik tekshirildi va yetishmaydiganlari yaratildi.")
    except Exception as e:
        log.warning(f"⚠️ Jadvallarni avto-yaratish RPC xatosi (SQL Editor'ga kod yozilganini tekshiring): {e}")
    # ──────────────────────────────────────────────────

    return _client


def get_client():
    if _client is None:
        raise RuntimeError("Supabase client init qilinmagan — avval init_client() chaqiring")
    return _client


async def _run(fn, *args, **kwargs):
    """Sinxron supabase-py chaqiruvini executor'da bajaradi."""
    loop = asyncio.get_event_loop()
    call = functools.partial(fn, *args, **kwargs)
    return await loop.run_in_executor(None, call)


# ══════════════════════════════════════════════════════════════
# GENERIC CRUD YORDAMCHILARI
# ══════════════════════════════════════════════════════════════

async def select(table: str, columns: str = "*", filters: dict | None = None,
                  order: str | None = None, desc: bool = False, limit: int | None = None):
    def _do():
        q = get_client().table(table).select(columns)
        if filters:
            for k, v in filters.items():
                q = q.eq(k, v)
        if order:
            q = q.order(order, desc=desc)
        if limit:
            q = q.limit(limit)
        return q.execute()
    res = await _run(_do)
    return res.data or []


async def select_one(table: str, pk_col: str, pk_val):
    def _do():
        return get_client().table(table).select("*").eq(pk_col, pk_val).limit(1).execute()
    res = await _run(_do)
    rows = res.data or []
    return rows[0] if rows else None


async def upsert(table: str, row: dict, on_conflict: str | None = None):
    def _do():
        q = get_client().table(table)
        if on_conflict:
            return q.upsert(row, on_conflict=on_conflict).execute()
        return q.upsert(row).execute()
    res = await _run(_do)
    return res.data or []


async def upsert_many(table: str, rows: list, on_conflict: str | None = None):
    if not rows:
        return []
    def _do():
        q = get_client().table(table)
        if on_conflict:
            return q.upsert(rows, on_conflict=on_conflict).execute()
        return q.upsert(rows).execute()
    res = await _run(_do)
    return res.data or []


async def update(table: str, pk_col: str, pk_val, patch: dict):
    def _do():
        return get_client().table(table).update(patch).eq(pk_col, pk_val).execute()
    res = await _run(_do)
    return res.data or []


async def delete(table: str, pk_col: str, pk_val):
    def _do():
        return get_client().table(table).delete().eq(pk_col, pk_val).execute()
    res = await _run(_do)
    return res.data or []


async def delete_where(table: str, filters: dict):
    def _do():
        q = get_client().table(table).delete()
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute()
    res = await _run(_do)
    return res.data or []


async def count(table: str, filters: dict | None = None) -> int:
    def _do():
        q = get_client().table(table).select("*", count="exact")
        if filters:
            for k, v in filters.items():
                q = q.eq(k, v)
        return q.limit(1).execute()
    res = await _run(_do)
    return res.count or 0
