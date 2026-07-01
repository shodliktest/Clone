"""
ROLES ADMIN — Foydalanuvchi darajalarini boshqarish
====================================================
Admin buyruqlari:
  /users          — Foydalanuvchilar ro'yxati
  /user <id>      — Foydalanuvchi ma'lumotlari
  /setrole        — Role o'zgartirish (interaktiv)
  /resetall       — Barchani student ga tushirish

Bu fayl mavjud admin.py ga ta'sir qilmaydi.
"""

import logging
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS
from utils import ram_cache as ram
from utils.db import update_user, get_all_users
from utils.roles import (
    ROLE_LABELS, ROLE_LEVELS, DURATION_OPTIONS,
    set_role, get_role, format_role_info, get_referral_stats,
    get_global_config, set_global_config
)

log    = logging.getLogger(__name__)
router = Router()
UTC    = timezone.utc


class RoleAdmin(StatesGroup):
    waiting_uid    = State()
    confirm_role   = State()
    confirm_dur    = State()
    resetall_confirm = State()


# ── Guard: faqat admin ━━━━━━━━━━━━━━━━━━━━━━━━
def _is_admin(uid: int) -> bool:
    if uid in ADMIN_IDS:
        return True
    user = ram.get_user(uid)
    return bool(user and user.get("role") == "admin")


# ══════════════════════════════════════════════════════════════
# /users — foydalanuvchilar ro'yxati
# ══════════════════════════════════════════════════════════════
@router.message(Command("users"))
async def cmd_users(message: Message):
    if not _is_admin(message.from_user.id):
        return

    users = get_all_users()
    if not users:
        return await message.answer("👤 Foydalanuvchilar yo'q.")

    # Rollar bo'yicha guruhlash
    by_role = {}
    for u in users:
        r = u.get("role", "user")
        by_role.setdefault(r, []).append(u)

    lines = [f"👥 <b>FOYDALANUVCHILAR</b> — jami: {len(users)}\n"]
    for role in ["admin", "teacher", "student", "user"]:
        grp = by_role.get(role, [])
        if not grp:
            continue
        lbl = ROLE_LABELS.get(role, role)
        lines.append(f"\n{lbl} — {len(grp)} ta:")
        for u in grp[:10]:  # Har roldan max 10
            nm  = u.get("name","?")[:20]
            uid = u.get("telegram_id","?")
            exp = ""
            if u.get("role_expires_at"):
                try:
                    dt  = datetime.fromisoformat(u["role_expires_at"])
                    d   = (dt - datetime.now(UTC)).days
                    exp = f" ({d}k)"
                except: pass
            lines.append(f"  <code>{uid}</code> {nm}{exp}")
        if len(grp) > 10:
            lines.append(f"  ... va yana {len(grp)-10} ta")

    lines.append("\n💡 /user &lt;ID&gt; — batafsil ma'lumot")
    lines.append("💡 /setrole — daraja o'zgartirish")
    await message.answer("\n".join(lines))


# ══════════════════════════════════════════════════════════════
# /user <uid> — bitta user ma'lumotlari
# ══════════════════════════════════════════════════════════════
@router.message(Command("user"))
async def cmd_user_info(message: Message):
    if not _is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("❌ Foydalanish: /user &lt;ID&gt;")

    try:
        uid = int(args[1])
    except ValueError:
        return await message.answer("❌ ID raqam bo'lishi kerak")

    user = ram.get_user(uid)
    if not user:
        return await message.answer(f"❌ <code>{uid}</code> topilmadi")

    await message.answer(
        _format_user_detail(uid, user),
        reply_markup=_user_action_kb(uid, user.get("role","user"))
    )


def _format_user_detail(uid: int, user: dict) -> str:
    role    = user.get("role", "user")
    label   = ROLE_LABELS.get(role, role)
    expires = user.get("role_expires_at")
    ref     = get_referral_stats(uid)
    blocked = user.get("is_blocked", False)

    exp_txt = ""
    if expires:
        try:
            dt  = datetime.fromisoformat(expires)
            d   = (dt - datetime.now(UTC)).days
            exp_txt = f"\n⏳ Muddat: <b>{max(0,d)} kun</b> qoldi ({dt.strftime('%d.%m.%Y')})"
        except: pass

    return (
        f"👤 <b>{user.get('name','?')}</b>\n"
        f"🆔 <code>{uid}</code>"
        f"{' | @'+user['username'] if user.get('username') else ''}\n"
        f"{'🚫 BLOKLANGAN\n' if blocked else ''}"
        f"\n📊 Daraja: <b>{label}</b>{exp_txt}\n"
        f"\n📝 Testlar: {user.get('total_tests',0)}\n"
        f"⭐ O'rtacha: {user.get('avg_score',0)}%\n"
        f"\n👥 Referal: {ref['total']} jami / {ref['today']} bugun\n"
        f"🎁 Bonus kunlar: {ref['bonus_days']}\n"
        f"\n📅 Ro'yxatdan: {user.get('created_at','?')[:10]}\n"
        f"🕐 Oxirgi: {user.get('last_active','?')[:10]}"
    )


def _user_action_kb(uid: int, current_role: str):
    b = InlineKeyboardBuilder()
    # Role o'zgartirish tugmalari
    for role, label in ROLE_LABELS.items():
        if role == "guest":
            continue
        if role == current_role:
            b.row(InlineKeyboardButton(
                text=f"✅ {label} (hozirgi)",
                callback_data=f"ra_role:{uid}:{role}"
            ))
        else:
            b.row(InlineKeyboardButton(
                text=label,
                callback_data=f"ra_role:{uid}:{role}"
            ))
    b.row(
        InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"ra_block:{uid}:1"),
        InlineKeyboardButton(text="✅ Blokdan chiq", callback_data=f"ra_block:{uid}:0"),
    )
    b.row(InlineKeyboardButton(text="❌ Yopish", callback_data="ra_close"))
    return b.as_markup()


def _duration_kb(uid: int, role: str):
    """Muddat tanlash klaviaturasi."""
    b = InlineKeyboardBuilder()
    for key, (label, days) in DURATION_OPTIONS.items():
        b.button(
            text=label,
            callback_data=f"ra_dur:{uid}:{role}:{key}"
        )
    b.adjust(3)
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="ra_close"))
    return b.as_markup()


# ══════════════════════════════════════════════════════════════
# Callback: role tanlash → muddat tanlash → tasdiqlash
# ══════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("ra_role:"))
async def cb_role_select(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫 Ruxsat yo'q", show_alert=True)

    _, uid_s, role = callback.data.split(":")
    uid = int(uid_s)
    user = ram.get_user(uid)
    if not user:
        return await callback.answer("User topilmadi", show_alert=True)

    await callback.answer()
    label = ROLE_LABELS.get(role, role)
    await callback.message.edit_text(
        f"👤 <b>{user.get('name','?')}</b> (<code>{uid}</code>)\n\n"
        f"Yangi daraja: <b>{label}</b>\n\n"
        f"📅 Qancha muddatga?",
        reply_markup=_duration_kb(uid, role)
    )


@router.callback_query(F.data.startswith("ra_dur:"))
async def cb_dur_select(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫 Ruxsat yo'q", show_alert=True)

    parts = callback.data.split(":")
    _, uid_s, role, dur_key = parts
    uid = int(uid_s)
    user = ram.get_user(uid)
    if not user:
        return await callback.answer("User topilmadi", show_alert=True)

    result = set_role(uid, role, dur_key)
    label  = ROLE_LABELS.get(role, role)
    dur_lbl = DURATION_OPTIONS.get(dur_key, ("?",))[0]

    await callback.answer(f"✅ {label} — {dur_lbl}", show_alert=True)

    # Foydalanuvchiga xabar yuborish
    try:
        exp_txt = f"\n⏳ Muddat: <b>{dur_lbl}</b>" if dur_key != "perm" else ""
        await callback.bot.send_message(
            uid,
            f"🎉 <b>Darajangiz o'zgartirildi!</b>\n\n"
            f"Yangi daraja: <b>{label}</b>{exp_txt}\n\n"
            f"{'🌍 Endi ommaviy test yarata olasiz!' if role == 'teacher' else ''}"
            f"{'📝 Endi shaxsiy va link testlar yarata olasiz!' if role == 'student' else ''}"
        )
    except Exception:
        pass

    # Xabarni yangilash
    updated = ram.get_user(uid) or {}
    try:
        await callback.message.edit_text(
            _format_user_detail(uid, updated),
            reply_markup=_user_action_kb(uid, role)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("ra_block:"))
async def cb_block(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫 Ruxsat yo'q", show_alert=True)

    _, uid_s, blocked_s = callback.data.split(":")
    uid     = int(uid_s)
    blocked = blocked_s == "1"

    from utils.db import block_user
    block_user(uid, blocked)

    status = "🚫 Bloklandi" if blocked else "✅ Blokdan chiqarildi"
    await callback.answer(status, show_alert=True)

    # Foydalanuvchiga xabar
    if blocked:
        try:
            await callback.bot.send_message(uid, "🚫 Hisobingiz bloklandi. Admin bilan bog'laning.")
        except: pass

    user = ram.get_user(uid) or {}
    try:
        await callback.message.edit_text(
            _format_user_detail(uid, user),
            reply_markup=_user_action_kb(uid, user.get("role","user"))
        )
    except: pass


@router.callback_query(F.data == "ra_close")
async def cb_close(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except: pass


# ══════════════════════════════════════════════════════════════
# /setrole — ID kiritib role o'zgartirish
# ══════════════════════════════════════════════════════════════
@router.message(Command("setrole"))
async def cmd_setrole(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    await state.set_state(RoleAdmin.waiting_uid)
    await message.answer(
        "👤 <b>Daraja o'zgartirish</b>\n\n"
        "Foydalanuvchi ID sini kiriting:"
    )


@router.message(RoleAdmin.waiting_uid)
async def setrole_uid(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    try:
        uid = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ ID raqam bo'lishi kerak")

    user = ram.get_user(uid)
    if not user:
        return await message.answer(f"❌ <code>{uid}</code> topilmadi")

    await state.clear()
    await message.answer(
        _format_user_detail(uid, user),
        reply_markup=_user_action_kb(uid, user.get("role","user"))
    )


# ══════════════════════════════════════════════════════════════
# /resetall — Barchani student/user ga tushirish
# ══════════════════════════════════════════════════════════════
@router.message(Command("resetall"))
async def cmd_resetall(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Ha, barchani student", callback_data="ra_resetall:student"),
        InlineKeyboardButton(text="✅ Ha, barchani user",    callback_data="ra_resetall:user"),
    )
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="ra_close"))
    await message.answer(
        "⚠️ <b>Barchani reset qilish</b>\n\n"
        "Bu barcha foydalanuvchilarning (admindan tashqari) darajasini o'zgartiradi.\n\n"
        "Qaysi darajaga tushiramiz?",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("ra_resetall:"))
async def cb_resetall(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫 Ruxsat yo'q", show_alert=True)

    role  = callback.data.split(":")[1]
    label = ROLE_LABELS.get(role, role)
    users = get_all_users()
    count = 0
    admin_uid = callback.from_user.id

    for u in users:
        uid = u.get("telegram_id")
        if not uid or uid == admin_uid or uid in ADMIN_IDS:
            continue
        cur_role = u.get("role", "user")
        if cur_role in ("admin", "teacher") and uid not in ADMIN_IDS:
            update_user(uid, {
                "role":            role,
                "role_expires_at": None,
            })
            count += 1
        elif cur_role not in ("admin",):
            update_user(uid, {
                "role":            role,
                "role_expires_at": None,
            })
            count += 1

    await callback.answer(f"✅ {count} ta user → {label}", show_alert=True)
    try:
        await callback.message.edit_text(
            f"✅ <b>Reset bajarildi</b>\n\n"
            f"{count} ta foydalanuvchi {label} darajasiga o'tkazildi.\n"
            f"(Adminlar o'zgartirilmadi)"
        )
    except: pass


# ══════════════════════════════════════════════════════════════
# /settings — Bosh sozlamalar markazi
# ══════════════════════════════════════════════════════════════

def _settings_kb() -> object:
    cfg = get_global_config()
    open_create = cfg.get("open_test_creation", False)
    b = InlineKeyboardBuilder()

    # ── Global sozlamalar ──
    b.row(InlineKeyboardButton(
        text=f"{'✅' if open_create else '❌'} Hammaga test yaratish (shaxsiy/link)",
        callback_data="ra_toggle:open_test_creation"
    ))

    # ── Foydalanuvchi boshqaruvi ──
    b.row(InlineKeyboardButton(
        text="👥 Foydalanuvchilar ro'yxati",
        callback_data="ra_users_list:0"
    ))
    b.row(InlineKeyboardButton(
        text="🔍 ID bo'yicha qidirish",
        callback_data="ra_search_user"
    ))
    b.row(
        InlineKeyboardButton(text="🎓 Barchani → Student", callback_data="ra_resetall:student"),
        InlineKeyboardButton(text="👤 Barchani → User",    callback_data="ra_resetall:user"),
    )
    b.row(InlineKeyboardButton(text="❌ Yopish", callback_data="ra_close"))
    return b.as_markup()


def _settings_text() -> str:
    cfg = get_global_config()
    open_create = cfg.get("open_test_creation", False)
    from utils import ram_cache as ram
    users = ram.get_users()
    by_role = {}
    for u in users.values():
        r = u.get("role", "user")
        by_role[r] = by_role.get(r, 0) + 1

    role_lines = ""
    for r in ["admin", "teacher", "student", "user"]:
        cnt = by_role.get(r, 0)
        if cnt:
            role_lines += f"  {ROLE_LABELS.get(r, r)}: <b>{cnt}</b>\n"

    return (
        "⚙️ <b>SOZLAMALAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Test yaratish (shaxsiy/link):</b>\n"
        f"   {'✅ Hamma yarata oladi' if open_create else '❌ Faqat Student+ va referal'}\n"
        f"🌍 <b>Ommaviy test:</b> Faqat Teacher va Admin\n\n"
        f"👥 <b>Foydalanuvchilar:</b> {len(users)} ta\n"
        f"{role_lines}"
        f"\n💡 Buyruqlar:\n"
        f"  /user &lt;ID&gt; — user batafsil\n"
        f"  /setrole — daraja o'zgartirish\n"
        f"  /resetall — barchani tushirish"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer(_settings_text(), reply_markup=_settings_kb())


@router.callback_query(F.data.startswith("ra_toggle:"))
async def cb_toggle_setting(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫 Ruxsat yo'q", show_alert=True)

    key = callback.data.split(":")[1]
    cfg = get_global_config()
    new_val = not cfg.get(key, False)
    set_global_config({key: new_val})

    status = "✅ Yoqildi" if new_val else "❌ O'chirildi"
    await callback.answer(status, show_alert=False)
    try:
        await callback.message.edit_text(
            _settings_text(), reply_markup=_settings_kb()
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("ra_users_list:"))
async def cb_users_list(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)

    page  = int(callback.data.split(":")[1])
    users = get_all_users()
    PER   = 8
    total = len(users)
    chunk = users[page*PER : (page+1)*PER]

    lines = [f"👥 <b>Foydalanuvchilar</b> ({total} ta) — bet {page+1}\n"]
    for u in chunk:
        uid  = u.get("telegram_id", "?")
        nm   = u.get("name", "?")[:18]
        role = ROLE_LABELS.get(u.get("role","user"), "👤")
        blk  = "🚫" if u.get("is_blocked") else ""
        lines.append(f"{blk}{role} <code>{uid}</code> {nm}")

    b = InlineKeyboardBuilder()
    # Har user uchun tugma
    for u in chunk:
        uid = u.get("telegram_id")
        nm  = u.get("name","?")[:15]
        b.row(InlineKeyboardButton(
            text=f"{ROLE_LABELS.get(u.get('role','user'), '👤')} {nm}",
            callback_data=f"ra_user_detail:{uid}"
        ))
    # Navigatsiya
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"ra_users_list:{page-1}"))
    if (page+1)*PER < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"ra_users_list:{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Sozlamalar", callback_data="ra_back_settings"))
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ra_user_detail:"))
async def cb_user_detail_inline(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)

    uid  = int(callback.data.split(":")[1])
    user = ram.get_user(uid)
    if not user:
        return await callback.answer("❌ Topilmadi", show_alert=True)

    try:
        await callback.message.edit_text(
            _format_user_detail(uid, user),
            reply_markup=_user_action_kb(uid, user.get("role","user"))
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "ra_search_user")
async def cb_search_user(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer()
    await state.set_state(RoleAdmin.waiting_uid)
    await callback.message.answer(
        "🔍 <b>User qidirish</b>\n\nFoydalanuvchi ID sini kiriting:"
    )


@router.callback_query(F.data == "ra_back_settings")
async def cb_back_settings(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    try:
        await callback.message.edit_text(_settings_text(), reply_markup=_settings_kb())
    except Exception:
        pass
    await callback.answer()


# ── "⚙️ Sozlamalar" tugmasi (admin keyboard) ─────────────────
@router.message(F.text == "⚙️ Sozlamalar")
async def btn_settings(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer(_settings_text(), reply_markup=_settings_kb())
