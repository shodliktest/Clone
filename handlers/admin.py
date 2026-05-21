"""👑 ADMIN PANEL"""
import json, logging
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from config import ADMIN_IDS
from utils import ram_cache as ram
from utils.db import get_all_users, get_all_tests, block_user
from keyboards.keyboards import admin_kb, main_kb, CAT_ICONS, get_cat_icon
from utils.states import AdminPanel

log    = logging.getLogger(__name__)
router = Router()
UTC    = timezone.utc

def is_admin(uid): return uid in ADMIN_IDS


# ══ ADMIN PANEL ASOSIY ════════════════════════════════════════
@router.message(F.text == "👑 Admin Panel")
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id): return
    await _show_admin(message)

@router.callback_query(F.data == "admin_panel")
async def admin_panel_cb(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await _show_admin(callback, edit=True)

async def _show_admin(ev, edit=False):
    st    = ram.stats()
    tests = ram.get_tests_meta()
    users = ram.get_users()
    text  = (
        f"👑 <b>ADMIN PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Testlar: <b>{len(tests)}</b>\n"
        f"👥 Userlar: <b>{len(users)}</b>\n"
        f"📊 Kunlik: <b>{st.get('daily_r',0)}</b>\n"
        f"💾 RAM cache: <b>{st.get('cached_q',0)} test</b>\n"
        f"🧠 RAM: <b>{st.get('mb',0)} MB ({st.get('pct',0)}%)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    try:
        if edit and hasattr(ev, 'message'):
            await ev.message.edit_text(text, reply_markup=admin_kb())
        elif edit:
            await ev.edit_text(text, reply_markup=admin_kb())
        else:
            await ev.answer(text, reply_markup=admin_kb())
    except TelegramBadRequest:
        target = ev.message if hasattr(ev, 'message') else ev
        await target.answer(text, reply_markup=admin_kb())


# ══ STATISTIKA ════════════════════════════════════════════════
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    st    = ram.stats()
    users = ram.get_users()
    tests = ram.get_tests_meta()
    daily = ram.get_daily()
    today_users  = sum(1 for v in daily.values() if v.get("by_test"))
    today_solves = sum(
        len(v.get("by_test", {})) for v in daily.values()
    )
    cache_info = ram.get_cache_stats() if hasattr(ram, 'get_cache_stats') else []
    text = (
        f"📈 <b>STATISTIKA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Jami userlar: <b>{len(users)}</b>\n"
        f"📋 Jami testlar: <b>{len(tests)}</b>\n\n"
        f"📅 <b>Bugun:</b>\n"
        f"  👤 Aktiv userlar: <b>{today_users}</b>\n"
        f"  🎯 Yechilgan: <b>{today_solves}</b>\n\n"
        f"🧠 <b>RAM holati:</b>\n"
        f"  💾 {st.get('mb',0)} MB / {st.get('limit_mb',450)} MB ({st.get('pct',0)}%)\n"
        f"  📦 Cached testlar: <b>{st.get('cached_q',0)} ta</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


# ══ USERLAR ════════════════════════════════════════════════════
@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    await _show_users_page(callback.message, page=0, edit=True)

@router.callback_query(F.data.startswith("adm_users_p"))
async def admin_users_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data[11:])
    await _show_users_page(callback.message, page=page, edit=True)

async def _show_users_page(msg, page=0, edit=False):
    users_dict = ram.get_users()
    users      = sorted(users_dict.values(), key=lambda u: u.get("total_tests",0), reverse=True)
    PG    = 10
    total = (len(users)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = users[page*PG:(page+1)*PG]
    text  = (
        f"👥 <b>FOYDALANUVCHILAR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(users)} ta | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for u in chunk:
        uid   = u.get("telegram_id","")
        name  = u.get("name","?")[:16]
        total_t = u.get("total_tests",0)
        avg   = round(u.get("avg_score",0),1)
        blk   = "🚫" if u.get("is_blocked") else ""
        text += f"{blk}👤 <b>{name}</b> | 📋{total_t} | ⭐{avg}%\n"
        b.row(InlineKeyboardButton(
            text=f"{'🚫' if u.get('is_blocked') else '👤'} {name} — {total_t} test",
            callback_data=f"adm_user_{uid}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_users_p{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_users_p{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("adm_user_"))
async def adm_user_detail(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    uid_str = callback.data[9:]
    users   = ram.get_users()
    u       = users.get(str(uid_str), {})
    if not u:
        return await callback.answer("Topilmadi", show_alert=True)
    name  = u.get("name","?")
    uname = f"@{u['username']}" if u.get("username") else "Yo'q"
    blk   = u.get("is_blocked", False)
    text  = (
        f"👤 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{uid_str}</code>\n"
        f"📱 {uname}\n"
        f"📋 Testlar: <b>{u.get('total_tests',0)}</b>\n"
        f"⭐ O'rtacha: <b>{round(u.get('avg_score',0),1)}%</b>\n"
        f"🕐 Oxirgi: {str(u.get('last_active',''))[:16]}\n"
        f"{'🚫 BLOKLANGAN' if blk else '✅ Aktiv'}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="✅ Blokdan chiqarish" if blk else "🚫 Bloklash",
        callback_data=f"adm_block_{uid_str}"
    ))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_users"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("adm_block_"))
async def adm_block_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    uid_str = callback.data[10:]
    users   = ram.get_users()
    u       = users.get(str(uid_str), {})
    new_blk = not u.get("is_blocked", False)
    block_user(int(uid_str), new_blk)
    await callback.answer("🚫 Bloklandi" if new_blk else "✅ Blok ochildi", show_alert=True)
    await adm_user_detail(callback)


# ══ TESTLAR — FANLAR BO'YICHA ══════════════════════════════════
@router.callback_query(F.data == "admin_tests")
async def admin_tests(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    await _show_admin_test_cats(callback.message, edit=True)

@router.callback_query(F.data == "adm_back_to_cats")
async def adm_back_cats(callback: CallbackQuery):
    await callback.answer()
    await _show_admin_test_cats(callback.message, edit=True)


@router.callback_query(F.data.startswith("adm_deleted_"))
async def adm_deleted_tests(callback: CallbackQuery):
    """O'chirilgan testlar ro'yxati."""
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    page  = int(callback.data.split("_")[-1])
    tests = [t for t in ram.get_all_tests_meta() if not t.get("is_active", True)]
    PG    = 8
    total = max(1, (len(tests)+PG-1)//PG)
    page  = max(0, min(page, total-1))
    chunk = tests[page*PG:(page+1)*PG]

    text  = (
        f"🗑 <b>O'CHIRILGAN TESTLAR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in chunk:
        tid     = t.get("test_id","")
        title_t = t.get("title","?")[:18]
        sc      = t.get("solve_count", 0)
        c_name  = t.get("creator_name", "")[:12]
        created = str(t.get("created_at",""))[:10]
        text += f"🗑 <b>{title_t}</b> <code>[{tid}]</code>\n"
        text += f"   👤{c_name} | 📅{created} | 👥{sc}\n\n"
        b.row(InlineKeyboardButton(
            text=f"🗑 {title_t[:20]} [{tid}]",
            callback_data=f"adm_test_{tid}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_deleted_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_deleted_{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm_back_to_cats"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

async def _show_admin_test_cats(msg, edit=False):
    tests = ram.get_all_tests_meta()
    cats  = {}
    for t in tests:
        c = t.get("category") or "Boshqa"
        if c not in cats:
            cats[c] = {"total": 0, "active": 0, "paused": 0, "deleted": 0}
        cats[c]["total"] += 1
        if not t.get("is_active", True):
            cats[c]["deleted"] += 1
        elif t.get("is_paused"):
            cats[c]["paused"] += 1
        else:
            cats[c]["active"] += 1

    sorted_cats = sorted(cats.items(), key=lambda x: x[1]["total"], reverse=True)
    text = (
        f"📋 <b>TESTLAR — FANLAR BO'YICHA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(tests)} ta test | {len(cats)} ta fan</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for cat, info in sorted_cats:
        icon  = get_cat_icon(cat)
        parts = []
        if info["active"]:  parts.append(f"✅{info['active']}")
        if info["paused"]:  parts.append(f"⏸{info['paused']}")
        if info["deleted"]: parts.append(f"🗑{info['deleted']}")
        stat  = " ".join(parts)
        text += f"{icon} <b>{cat}</b> — {info['total']} ta ({stat})\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {cat} — {info['total']} ta",
            callback_data=f"adm_cat_{cat[:30]}_0"
        ))
    b.row(InlineKeyboardButton(text="🌟 Hammasi", callback_data="adm_cat_ALL_0"))
    b.row(InlineKeyboardButton(text="⬅️ Admin",   callback_data="admin_panel"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("adm_cat_"))
async def adm_cat_tests(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    raw   = callback.data[8:]
    parts = raw.rsplit("_", 1)
    cat   = parts[0]
    page  = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    await _show_adm_cat_tests(callback.message, cat, page, edit=True)

async def _show_adm_cat_tests(msg, cat_name, page=0, edit=False, show_deleted=False):
    tests = ram.get_all_tests_meta()
    if cat_name != "ALL":
        tests = [t for t in tests if t.get("category") == cat_name]
    # O'chirilganlarni yashirish (maxsus ko'rsatilmasa)
    if not show_deleted:
        tests = [t for t in tests if t.get("is_active", True)]
    deleted_count = sum(1 for t in ram.get_all_tests_meta() if not t.get("is_active", True))
    PG    = 8
    total = (len(tests)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = tests[page*PG:(page+1)*PG]
    title = "🌟 BARCHA TESTLAR" if cat_name == "ALL" else f"📋 {cat_name.upper()}"
    vis_m = {"public":"🌍","link":"🔗","private":"🔒"}
    diff_m= {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta aktiv | 🗑 {deleted_count} ta o'chirilgan | Sahifa {page+1}/{max(1,total)}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in chunk:
        tid     = t.get("test_id","")
        title_t = t.get("title","?")[:18]
        active  = t.get("is_active", True)
        paused  = t.get("is_paused", False)
        sc      = t.get("solve_count", 0)
        vis     = vis_m.get(t.get("visibility",""), "")
        diff    = diff_m.get(t.get("difficulty",""), "")
        c_name  = t.get("creator_name", "")[:12]
        icon    = "🗑" if not active else ("⏸" if paused else "✅")
        text += f"{icon}{vis}{diff} <b>{title_t}</b> <code>[{tid}]</code> | 👥{sc}"
        if c_name:
            text += f" | 👤{c_name}"
        text += "\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {title_t[:20]} [{tid}]",
            callback_data=f"adm_test_{tid}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_cat_{cat_name}_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_cat_{cat_name}_{page+1}"))
    if nav: b.row(*nav)
    if deleted_count > 0:
        b.row(InlineKeyboardButton(
            text=f"🗑 O'chirilganlar ({deleted_count})",
            callback_data=f"adm_deleted_0"
        ))
    b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="adm_back_to_cats"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("adm_test_"))
async def adm_test_detail(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    tid  = callback.data[9:]
    meta = ram.get_test_meta(tid) or {}
    if not meta:
        # O'chirilgan test — all_tests_meta dan qidirish
        meta = next((t for t in ram.get_all_tests_meta() if t.get("test_id")==tid), {})
    if not meta:
        return await callback.answer("❌ Test topilmadi", show_alert=True)

    active = meta.get("is_active", True)
    paused = meta.get("is_paused", False)
    vis_m  = {"public":"🌍 Ommaviy","link":"🔗 Ssilka","private":"🔒 Shaxsiy"}
    diff_m = {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}

    c_id   = meta.get("creator_id", "?")
    c_name = meta.get("creator_name", "")
    c_user = meta.get("creator_username", "")
    c_str  = c_name if c_name else f"ID: {c_id}"
    if c_user:
        c_str += f" (@{c_user})"
    created = str(meta.get("created_at", ""))[:10] or "—"

    text = (
        f"🔍 <b>TEST BATAFSIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'🗑 <b>O\'CHIRILGAN</b>\n\n' if not active else ''}"
        f"{'⏸ <b>PAUZADA</b>\n\n' if paused else ''}"
        f"📝 <b>{meta.get('title','?')}</b>\n"
        f"🆔 <code>{tid}</code>\n"
        f"📁 {meta.get('category','')}\n"
        f"📊 {diff_m.get(meta.get('difficulty',''),'')}\n"
        f"🔒 {vis_m.get(meta.get('visibility',''),'')}\n"
        f"📋 {meta.get('question_count',0)} savol\n"
        f"👥 {meta.get('solve_count',0)} yechgan\n"
        f"⭐ {round(meta.get('avg_score',0),1)}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Yaratuvchi: <b>{c_str}</b>\n"
        f"📅 Yaratilgan: <b>{created}</b>"
    )
    b = InlineKeyboardBuilder()
    if active:
        b.row(InlineKeyboardButton(
            text="▶️ Davom ettirish" if paused else "⏸ To'xtatish",
            callback_data=f"{'test_resume' if paused else 'test_pause'}_{tid}"
        ))
        b.row(
            InlineKeyboardButton(text="✏️ Nomini o'zgartirish", callback_data=f"edit_title_{tid}"),
        )
        b.row(
            InlineKeyboardButton(text="👥 Kim yechgan",    callback_data=f"test_solvers_{tid}_0"),
            InlineKeyboardButton(text="⏱ Poll vaqti",      callback_data=f"edit_poll_time_{tid}"),
        )
        b.row(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_test_{tid}"))
    cat = meta.get("category","")[:30]
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"adm_cat_{cat}_0"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("del_test_"))
async def del_test_confirm(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    tid  = callback.data[9:]
    meta = ram.get_test_meta_any(tid) or {}
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Ha, butunlay o'chirish", callback_data=f"del_confirm_{tid}"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data=f"adm_test_{tid}"),
    )
    try:
        await callback.message.edit_text(
            f"⚠️ <b>BUTUNLAY O'CHIRISH</b>\n\n"
            f"📝 {meta.get('title','?')} [{tid}]\n\n"
            f"Test bazadan, RAMdan, TG dan <b>butunlay o'chiriladi</b>.\n"
            f"Faqat backup TG kanalda qoladi.",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("del_confirm_"))
async def del_test_exec(callback: CallbackQuery):
    await callback.answer("⏳ O'chirilmoqda...")
    if not is_admin(callback.from_user.id): return
    tid  = callback.data[12:]
    meta = ram.get_test_meta_any(tid) or {}
    from utils.db import delete_test
    await delete_test(tid)
    try:
        await callback.message.edit_text(
            f"✅ <b>{meta.get('title','?')}</b> butunlay o'chirildi.\n"
            f"🗑 Baza, RAM, TG — tozalandi.\n"
            f"💾 Backup TG kanalda saqlanadi."
        )
    except: pass
    await _show_admin_test_cats(callback.message)


# ══ O'CHIRILGAN TESTLAR (yaratuvchi o'chirgan) ══════════════════

@router.callback_query(F.data == "admin_deleted_tests")
async def admin_deleted_tests(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    deleted = ram.get_deleted_tests()
    if not deleted:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_panel"))
        try:
            await callback.message.edit_text(
                "🗑 <b>O'chirilgan testlar</b>\n\nHozircha o'chirilgan test yo'q.",
                reply_markup=b.as_markup()
            )
        except TelegramBadRequest: pass
        return

    # Fan bo'yicha guruhlash
    cats = {}
    for t in deleted:
        cat = t.get("category") or t.get("subject") or "Boshqa"
        cats.setdefault(cat, []).append(t)

    lines = ["🗑 <b>O'chirilgan testlar</b> (yaratuvchi o'chirgan)\n"]
    for cat, tests in sorted(cats.items()):
        lines.append(f"\n📂 <b>{cat}</b> — {len(tests)} ta")
        for t in tests[:5]:
            lines.append(
                f"  • {t.get('title','?')} [{t.get('test_id','')}] "
                f"— {t.get('question_count',0)} savol"
            )
        if len(tests) > 5:
            lines.append(f"  ... va yana {len(tests)-5} ta")

    b = InlineKeyboardBuilder()
    for cat in sorted(cats.keys()):
        b.row(InlineKeyboardButton(
            text=f"📂 {cat} ({len(cats[cat])})",
            callback_data=f"del_cat_{cat[:30]}"
        ))
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("del_cat_"))
async def admin_deleted_cat(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    cat     = callback.data[8:]
    deleted = ram.get_deleted_tests()
    tests   = [t for t in deleted
               if (t.get("category") or t.get("subject") or "Boshqa")[:30] == cat]
    b = InlineKeyboardBuilder()
    for t in tests:
        tid = t.get("test_id","")
        b.row(
            InlineKeyboardButton(
                text=f"📝 {t.get('title','?')[:30]}",
                callback_data=f"del_view_{tid}"
            )
        )
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_deleted_tests"))
    lines = [f"📂 <b>{cat}</b> — o'chirilgan testlar\n"]
    for t in tests:
        lines.append(
            f"• <b>{t.get('title','?')}</b>\n"
            f"  🆔 <code>{t.get('test_id','')}</code> | "
            f"❓ {t.get('question_count',0)} savol | "
            f"👤 {t.get('creator_name','?')}"
        )
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("del_view_"))
async def admin_deleted_view(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    tid  = callback.data[9:]
    meta = ram.get_test_meta_any(tid) or {}
    cat  = (meta.get("category") or meta.get("subject") or "Boshqa")[:30]
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📄 TXT yuklab olish", callback_data=f"del_txt_{tid}"))
    b.row(
        InlineKeyboardButton(text="♻️ Qayta tiklash",  callback_data=f"del_restore_{tid}"),
        InlineKeyboardButton(text="🗑 Butunlay o'chir", callback_data=f"del_confirm_{tid}"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"del_cat_{cat}"))
    try:
        await callback.message.edit_text(
            f"🗑 <b>O'chirilgan test</b>\n\n"
            f"📝 {meta.get('title','?')}\n"
            f"🆔 <code>{tid}</code>\n"
            f"📂 {cat}\n"
            f"❓ {meta.get('question_count',0)} savol\n"
            f"👤 {meta.get('creator_name','?')}\n"
            f"📅 {meta.get('created_at','?')}",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"Test: {meta.get('title','?')} [{tid}]",
            reply_markup=b.as_markup()
        )


@router.callback_query(F.data.startswith("del_restore_"))
async def admin_restore_test(callback: CallbackQuery):
    await callback.answer("♻️ Tiklanmoqda...")
    if not is_admin(callback.from_user.id): return
    tid = callback.data[12:]
    from utils import tg_db
    ram.update_test_meta(tid, {"is_deleted": False})
    if tg_db.ready():
        await tg_db.update_test_meta_tg(tid, {"is_deleted": False})
    meta = ram.get_test_meta_any(tid) or {}
    try:
        await callback.message.edit_text(
            f"✅ <b>{meta.get('title','?')}</b> tiklandi!\n"
            f"Test endi foydalanuvchilarga ko'rinadi."
        )
    except: pass


@router.callback_query(F.data.startswith("del_txt_"))
async def admin_download_txt(callback: CallbackQuery):
    await callback.answer("📄 TXT tayyorlanmoqda...")
    if not is_admin(callback.from_user.id): return
    tid  = callback.data[8:]
    from utils import tg_db
    test = await tg_db.get_test_full(tid)
    if not test or not test.get("questions"):
        meta = ram.get_test_meta_any(tid) or {}
        return await callback.message.answer(
            f"❌ <b>{meta.get('title','?')}</b> savollari topilmadi.\n"
            f"Test TG kanalda bo'lishi kerak."
        )
    # TXT format
    lines = [
        f"Test: {test.get('title','?')}",
        f"Fan: {test.get('category') or test.get('subject','?')}",
        f"Savollar: {len(test.get('questions',[]))}",
        f"ID: {tid}",
        "="*50,
        ""
    ]
    for i, q in enumerate(test.get("questions", []), 1):
        lines.append(f"{i}. {q.get('question', q.get('q','?'))}")
        options = q.get("options", q.get("variants", []))
        correct = q.get("correct", q.get("correct_index", 0))
        for j, opt in enumerate(options):
            mark = "✓" if j == correct else " "
            lines.append(f"   {mark} {chr(65+j)}) {opt}")
        if q.get("explanation"):
            lines.append(f"   💡 {q['explanation']}")
        lines.append("")

    txt_content = "\n".join(lines).encode("utf-8")
    from aiogram.types import BufferedInputFile
    doc = BufferedInputFile(txt_content, filename=f"{test.get('title','test')}_{tid}.txt")
    await callback.message.answer_document(
        doc,
        caption=f"📄 <b>{test.get('title','?')}</b>\n{len(test.get('questions',[]))} savol | {tid}"
    )


# ══ BROADCAST ══════════════════════════════════════════════════
@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            "📢 <b>BROADCAST</b>\n\nXabar yozing (HTML qo'llab-quvvatlanadi):",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest: pass
    await state.set_state(AdminPanel.broadcast)

@router.message(AdminPanel.broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    users   = ram.get_users()
    sent = ok = fail = 0
    status = await message.answer(f"⏳ <b>Yuborilmoqda...</b> 0/{len(users)}")
    for uid_str, u in users.items():
        if u.get("is_blocked"): continue
        try:
            await message.bot.send_message(int(uid_str), message.text or message.caption or "")
            ok += 1
        except Exception:
            fail += 1
        sent += 1
        if sent % 20 == 0:
            try:
                await status.edit_text(f"⏳ {sent}/{len(users)} | ✅{ok} ❌{fail}")
            except: pass
    await state.clear()
    try:
        await status.edit_text(
            f"✅ <b>Broadcast tugadi</b>\n\n"
            f"✅ Yuborildi: {ok}\n❌ Xato: {fail}\n📊 Jami: {sent}"
        )
    except: pass


# ══ GURUH E'LON ════════════════════════════════════════════════

@router.callback_query(F.data == "admin_group_broadcast")
async def group_broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_admin(callback.from_user.id): return

    groups = ram.get_known_groups()
    active = {cid: g for cid, g in groups.items() if g.get("active", True)}

    if not active:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
        try:
            await callback.message.edit_text(
                "📣 <b>Guruh E'lon</b>\n\n"
                "⚠️ Hali hech qaysi guruh yo'q.\n"
                "Bot biror guruhga qo'shilganda bu ro'yxat to'ladi.",
                reply_markup=b.as_markup()
            )
        except TelegramBadRequest: pass
        return

    lines = [f"📣 <b>GURUH E'LON</b>\n"]
    lines.append(f"Bot admin bo'lgan guruhlar: <b>{len(active)} ta</b>\n")
    for i, (cid, g) in enumerate(active.items(), 1):
        title    = g.get("title", "?")
        members  = g.get("member_count", "?")
        lines.append(f"{i}. <b>{title}</b> — {members} a'zo  <code>{cid}</code>")

    lines.append("\n✍️ Xabar yozing (matn, rasm, video — hammasi qo'llab-quvvatlanadi):")

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer("\n".join(lines), reply_markup=b.as_markup())

    await state.set_state(AdminPanel.group_broadcast)


@router.message(AdminPanel.group_broadcast)
async def group_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    groups = ram.get_known_groups()
    active = {cid: g for cid, g in groups.items() if g.get("active", True)}

    if not active:
        await state.clear()
        return await message.answer("⚠️ Guruh topilmadi.")

    status = await message.answer(f"⏳ <b>Guruhlarga yuborilmoqda...</b> 0/{len(active)}")
    ok = fail = 0

    for cid, g in active.items():
        try:
            # Xabar turini aniqlash va forward qilish
            if message.text:
                await message.bot.send_message(
                    int(cid),
                    message.text,
                    parse_mode="HTML"
                )
            elif message.photo:
                await message.bot.send_photo(
                    int(cid),
                    message.photo[-1].file_id,
                    caption=message.caption or ""
                )
            elif message.video:
                await message.bot.send_video(
                    int(cid),
                    message.video.file_id,
                    caption=message.caption or ""
                )
            elif message.document:
                await message.bot.send_document(
                    int(cid),
                    message.document.file_id,
                    caption=message.caption or ""
                )
            elif message.sticker:
                await message.bot.send_sticker(int(cid), message.sticker.file_id)
            elif message.voice:
                await message.bot.send_voice(int(cid), message.voice.file_id,
                                             caption=message.caption or "")
            elif message.video_note:
                await message.bot.send_video_note(int(cid), message.video_note.file_id)
            else:
                await message.forward(int(cid))
            ok += 1
            # Guruh member sonini yangilab qo'yish
            try:
                mc = await message.bot.get_chat_member_count(int(cid))
                g["member_count"] = mc
            except: pass
        except Exception as e:
            fail += 1
            log.warning(f"Guruh e'lon xato {cid} ({g.get('title','?')}): {e}")
            # Bot guruhdan chiqarilgan bo'lsa belgilaymiz
            err = str(e).lower()
            if "bot was kicked" in err or "bot is not a member" in err or "chat not found" in err:
                ram.remove_known_group(int(cid))

        try:
            await status.edit_text(f"⏳ {ok+fail}/{len(active)} | ✅{ok} ❌{fail}")
        except: pass

    await state.clear()

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📣 Yana e'lon", callback_data="admin_group_broadcast"))
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try:
        await status.edit_text(
            f"✅ <b>Guruh E'lon tugadi</b>\n\n"
            f"✅ Yuborildi: <b>{ok}</b> ta guruh\n"
            f"❌ Xato: <b>{fail}</b> ta\n"
            f"📊 Jami guruhlar: <b>{len(active)}</b>",
            reply_markup=b.as_markup()
        )
    except: pass


# ══ FLUSH / REFRESH ════════════════════════════════════════════
@router.callback_query(F.data == "adm_flush")
async def adm_flush(callback: CallbackQuery):
    await callback.answer("⏳ Yuborilmoqda...")
    if not is_admin(callback.from_user.id): return
    from utils import tg_db
    results = await tg_db.manual_flush(
        ram.get_daily(), ram.get_users(), ram.get_all_settings()
    )
    text = "⚡ <b>MANUAL FLUSH</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(results)
    b    = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data == "adm_refresh")
async def adm_refresh(callback: CallbackQuery):
    await callback.answer("⏳ Sync qilinmoqda...")
    if not is_admin(callback.from_user.id): return
    from utils import tg_db
    from utils.db import _sync_from_tg
    try:
        await _sync_from_tg()
        text = "🔄 <b>SYNC TUGADI</b>\n\nRAM TGdan yangilandi."
    except Exception as e:
        text = f"❌ Sync xato: {e}"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data == "adm_export_json")
async def adm_export_json(callback: CallbackQuery):
    await callback.answer("⏳")
    if not is_admin(callback.from_user.id): return
    data = {
        "tests_meta": ram.get_all_tests_meta(),
        "users_count": len(ram.get_users()),
        "daily_users": len(ram.get_daily()),
        "exported_at": str(datetime.now(UTC))
    }
    doc = BufferedInputFile(
        json.dumps(data, ensure_ascii=False, indent=2, default=str).encode(),
        filename=f"export_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.json"
    )
    await callback.message.answer_document(doc, caption="💾 Export")

@router.callback_query(F.data == "adm_backups")
async def adm_backups(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    from utils import tg_db
    dates = tg_db.get_backup_dates()
    info  = tg_db.get_index_info()
    text  = (
        f"🗂 <b>BACKUPLAR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Jami: {len(dates)} ta\n"
        f"📋 Testlar: {info.get('tests_count',0)} | Cache: {info.get('cached_tests',0)}\n\n"
    )
    for d in dates[:10]:
        text += f"💾 {d}\n"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


# ══════════════════════════════════════════════════════════════
# /reindex — Barcha testlarni qayta protect_content=False bilan saqlash
# ══════════════════════════════════════════════════════════════



@router.message(Command("rescan"))
async def cmd_rescan(message: Message):
    """
    TG kanaldan BARCHA JSON fayllarni skanerlaydi va ma'lumotlarni tiklaydi.
    Testlar, userlar, guruhlar — hammasi tiklanadi.
    """
    if not is_admin(message.from_user.id):
        return
    from utils import tg_db, ram_cache as ram
    msg = await message.answer(
        "🔍 <b>To'liq kanal skanerlash boshlandi...</b>\n"
        "3000 xabar skanerlash ~2-4 daqiqa davom etadi.\n"
        "⏳ Kuting..."
    )
    before_tests = len(ram.get_all_tests_meta())
    before_users = len(ram.get_users())

    # To'liq skanerlash
    result = await tg_db._migrate_from_old_index()

    after_tests = len(ram.get_all_tests_meta())
    after_users = len(ram.get_users())

    if result:
        await msg.edit_text(
            f"✅ <b>To'liq skanerlash yakunlandi!</b>\n\n"
            f"📋 Testlar: <b>{before_tests}</b> → <b>{after_tests}</b> ta\n"
            f"👥 Userlar: <b>{before_users}</b> → <b>{after_users}</b> ta\n\n"
            f"Endi barcha ma'lumotlar tiklanib saqlandi. ✅"
        )
    else:
        await msg.edit_text(
            "⚠️ Skanerlash natija bermadi.\n"
            "Kanal bo'sh yoki xato yuz berdi."
        )


@router.message(Command("reindex"))
async def cmd_reindex(message: Message):
    if not is_admin(message.from_user.id):
        return
    msg = await message.answer(
        "♻️ <b>Reindex boshlandi...</b>\n"
        "Barcha testlar qayta saqlanadi (protect_content=False).\n"
        "Bu bir necha daqiqa davom etishi mumkin."
    )
    from utils import tg_db, ram_cache as ram
    metas  = ram.get_all_tests_meta()
    total  = len(metas)
    ok     = 0
    failed = 0

    for i, meta in enumerate(metas):
        tid = meta.get("test_id")
        if not tid:
            continue
        # To'liq testni RAM yoki TGdan olish
        test = ram.get_cached_questions(tid) or tg_db._tests_cache.get(tid)
        if not test or not test.get("questions"):
            try:
                test = await tg_db.get_test_full(tid)
            except Exception:
                test = None
        if not test or not test.get("questions"):
            failed += 1
            continue
        # protect_content=False bilan qayta saqlash
        saved = await tg_db.save_test_full(test)
        if saved:
            ok += 1
        else:
            failed += 1
        # Progress har 5 testda
        if (i + 1) % 5 == 0:
            try:
                await msg.edit_text(
                    f"♻️ <b>Reindex:</b> {i+1}/{total}\n"
                    f"✅ {ok} ta saqlandi | ❌ {failed} ta xato"
                )
            except Exception:
                pass
        await asyncio.sleep(0.3)  # Flood oldini olish

    try:
        await msg.edit_text(
            f"✅ <b>Reindex yakunlandi!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Jami: {total} ta test\n"
            f"✅ Saqlandi: {ok} ta\n"
            f"❌ Xato: {failed} ta\n\n"
            f"Endi barcha testlar protect_content=False bilan saqlanmoqda.\n"
            f"Keyingi rebootlarda muammo bo'lmaydi."
        )
    except Exception:
        pass
