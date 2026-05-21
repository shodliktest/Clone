import asyncio
"""👤 PROFIL — Natijalar, Tahlil, Mening testlarim (fan bo'yicha)"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils.db import (get_user, get_my_tests, get_user_results,
                      get_analysis, get_test_full, get_test_stats_for_user,
                      pause_test, get_test_solvers)
from utils.states import AllowedUsersState, EditTestTitle
from utils.ram_cache import get_test_by_id, get_test_meta
from keyboards.keyboards import main_kb, analysis_kb, mytest_settings_kb, CAT_ICONS, get_cat_icon

log = logging.getLogger(__name__)
router = Router()
PAGE_RES = 7


# ══ PROFIL ═════════════════════════════════════════════════════
@router.message(F.text == "👤 Profil")
async def profile_msg(message: Message):
    await _show_profile(message, message.from_user.id)

@router.callback_query(F.data == "profile")
async def profile_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_profile(callback.message, callback.from_user.id, edit=True)

async def _show_profile(msg, uid, edit=False):
    user = get_user(uid)
    if not user:
        t = "❌ Profil topilmadi. /start ni bosing."
        try:
            if edit: await msg.edit_text(t)
            else:    await msg.answer(t)
        except: pass
        return
    avg   = round(user.get("avg_score",0),1)
    total = user.get("total_tests",0)
    badges= []
    if total >= 1:  badges.append("🥉 Boshliqchi")
    if total >= 10: badges.append("🥈 Tajribali")
    if total >= 50: badges.append("🥇 Ustoz")
    if avg >= 90:   badges.append("🌟 Mukammal")
    if avg >= 80:   badges.append("🔥 A'lochi")
    text = (
        f"👤 <b>SHAXSIY PROFIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Ism: <b>{user.get('name','?')}</b>\n\n"
        f"📋 Yechilgan: <b>{total} ta</b>\n"
        f"📊 O'rtacha: <b>{avg}%</b>\n"
        f"🏅 {('  '.join(badges)) if badges else 'Hali yo\'q'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📋 Natijalarim",      callback_data="results_p0"))
    b.row(InlineKeyboardButton(text="🗂 Mening testlarim", callback_data="mytests_cats"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu",     callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ══ NATIJALAR ══════════════════════════════════════════════════
@router.message(F.text == "📊 Natijalarim")
async def results_msg(message: Message):
    await _show_results(message, message.from_user.id)

@router.callback_query(F.data.startswith("results_p"))
async def results_page_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_results(callback.message, callback.from_user.id,
                        page=int(callback.data[9:]), edit=True)

async def _show_results(msg, uid, page=0, edit=False):
    all_r = get_user_results(uid)
    if not all_r:
        text = (
            "📭 <b>NATIJALARIM</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Hali test ishlamagansiz.\n📚 Testlar bo'limidan boshlang! 🚀"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="📚 Testlarga o'tish", callback_data="go_tests"))
        b.row(InlineKeyboardButton(text="🏠 Bosh sahifa",      callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    total_pg = (len(all_r)+PAGE_RES-1)//PAGE_RES
    page     = max(0, min(page, total_pg-1))
    chunk    = all_r[page*PAGE_RES:(page+1)*PAGE_RES]

    text = (
        f"<b>📋 NATIJALARIM</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Sahifa {page+1}/{total_pg} | Jami: {len(all_r)} ta</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for res in chunk:
        tid      = res.get("test_id","")
        meta     = get_test_by_id(tid)
        title    = meta.get("title","?")[:18] if meta else "O'chirilgan test"
        icon     = "✅" if res.get("passed") else "❌"
        last_pct = res.get("last_pct",0)
        best_pct = res.get("best_pct",last_pct)
        att      = res.get("attempts",1)
        all_pcts = res.get("all_pcts",[last_pct])
        dt       = res.get("completed_at","")[:10]
        rid      = res.get("result_id","")
        all_str  = " → ".join(f"{p}%" for p in all_pcts[-5:])
        if len(all_pcts)>5: all_str = f"...{len(all_pcts)-5} oldin | "+all_str
        text += (
            f"{icon} <b>{title}</b>\n"
            f"   📊 {last_pct}% | ⭐ {best_pct}% | 🔄 {att}x | 📅 {dt}\n"
            f"   📈 {all_str}\n\n"
        )
        b.row(InlineKeyboardButton(
            text=f"{icon} {title[:15]} — {last_pct}%",
            callback_data=f"res_back_{rid}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"results_p{page-1}"))
    if page < total_pg-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"results_p{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ══ NATIJA KARTOCHKASI ══════════════════════════════════════════
@router.callback_query(F.data.startswith("res_back_"))
async def result_back_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_result_card(callback, callback.data[9:])

async def _show_result_card(callback, rid):
    uid     = callback.from_user.id
    results = get_user_results(uid)
    res     = next((r for r in results if r.get("result_id")==rid), None)
    if not res:
        return await callback.answer("❌ Natija topilmadi.", show_alert=True)
    tid      = res.get("test_id","")
    meta     = get_test_by_id(tid)
    title    = meta.get("title","?") if meta else "O'chirilgan test"
    all_pcts = res.get("all_pcts",[res.get("last_pct",0)])
    att      = res.get("attempts",1)
    best     = res.get("best_pct",max(all_pcts) if all_pcts else 0)
    avg_s    = round(sum(all_pcts)/len(all_pcts),1) if all_pcts else 0
    last_pct = res.get("last_pct",0)
    passed   = res.get("passed", last_pct>=60)
    ps       = meta.get("passing_score",60) if meta else 60
    all_txt  = "\n".join(
        f"  {'✅' if p>=ps else '❌'} {i+1}-urinish: {p}%"
        for i,p in enumerate(all_pcts)
    )
    text = (
        f"{'✅' if passed else '❌'} <b>TEST NATIJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>{title}</b>\n"
        f"📅 {res.get('completed_at','')[:16]}\n\n"
        f"📊 Oxirgi: <b>{last_pct}%</b> | ⭐ Eng yaxshi: <b>{best}%</b>\n"
        f"📈 O'rtacha: <b>{avg_s}%</b> | 🔄 {att} urinish\n\n"
        f"<b>Barcha urinishlar:</b>\n<code>{all_txt}</code>\n\n"
        f"{'🎉 MUVAFFAQIYATLI!' if passed else '❌ YIQILDINGIZ'}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Oxirgi tahlil", callback_data=f"analysis_{rid}_0"))
    if meta:
        b.row(
            InlineKeyboardButton(text="🔄 Qaytadan",  callback_data=f"start_test_{tid}"),
            InlineKeyboardButton(text="📊 Quiz Poll", callback_data=f"start_poll_{tid}"),
        )
    b.row(InlineKeyboardButton(text="📤 Ulashish",    switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="⬅️ Natijalar",   callback_data="results_p0"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


# ══ TAHLIL ═════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("analysis_"))
async def analysis_handler(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data[9:].rsplit("_",1)
    rid   = parts[0]
    page  = int(parts[1]) if len(parts)>1 else 0
    uid   = callback.from_user.id
    det   = get_analysis(uid, rid)
    if not det:
        return await callback.answer(
            "❌ Tahlil topilmadi.\nFaqat oxirgi yechilgan test tahlili mavjud.",
            show_alert=True
        )
    parts2 = str(rid).split("_",1)
    tid    = parts2[1] if len(parts2)==2 else ""
    test   = await get_test_full(tid) if tid else {}
    qs     = test.get("questions",[]) if test else []
    title  = test.get("title","Test") if test else "Test"
    PG     = 5
    tot    = (len(det)+PG-1)//PG
    page   = max(0, min(page, tot-1))
    chunk  = det[page*PG:(page+1)*PG]
    corr   = sum(1 for d in det if d.get("is_correct"))
    text   = (
        f"📊 <b>{title.upper()} — TAHLIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ {corr}/{len(det)} to'g'ri | {page+1}/{tot}\n"
        f"<i>Faqat OXIRGI yechilgan test tahlili</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for d in chunk:
        i    = d.get("question_index",0)
        is_c = d.get("is_correct",False)
        u_a  = d.get("user_answer") or "Belgilanmagan"
        c_a  = d.get("correct_answer","?")
        q_o  = qs[i] if i<len(qs) else {}
        q_t  = q_o.get("question",q_o.get("text",f"{i+1}-savol"))
        expl = q_o.get("explanation","")
        pts  = d.get("earned_points",0)
        mp   = d.get("max_points",1)
        text += f"{'✅' if is_c else '❌'} <b>Savol {i+1}</b> [{pts}/{mp}]\n"
        text += f"<i>{q_t[:90]}{'...' if len(q_t)>90 else ''}</i>\n"
        if not is_c:
            text += f"  👤 <code>{str(u_a)[:45]}</code>\n  🎯 <code>{str(c_a)[:45]}</code>\n"
        else:
            text += f"  ✔️ <code>{str(c_a)[:45]}</code>\n"
        if expl and expl not in ("Izoh kiritilmagan.","Izoh yo'q",""):
            text += f"  💡 <i>{expl[:80]}</i>\n"
        text += "\n"
    try:
        await callback.message.edit_text(text, reply_markup=analysis_kb(rid,page,tot))
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=analysis_kb(rid,page,tot))


# ══ MENING TESTLARIM — FANLAR BO'YICHA ═════════════════════════
@router.message(F.text == "🗂 Mening testlarim")
async def my_tests_msg(message: Message):
    await _show_mytest_cats(message, message.from_user.id)

@router.callback_query(F.data == "mytests_cats")
async def mytests_cats_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_mytest_cats(callback.message, callback.from_user.id, edit=True)

@router.callback_query(F.data == "back_to_mytests")
@router.callback_query(F.data == "back_to_mytests_cat")
async def back_to_mytests(callback: CallbackQuery):
    await callback.answer()
    # Qaysi fanga qaytish kerakligini data dan olamiz agar bo'lsa
    if callback.data == "back_to_mytests_cat":
        # Oldingi cat sahifasiga qaytish
        # FSM state dan cat_name olish imkoni yo'q — fanlar listiga qaytamiz
        pass
    await _show_mytest_cats(callback.message, callback.from_user.id, edit=True)

async def _show_mytest_cats(msg, uid, edit=False):
    tests = get_my_tests(uid)
    if not tests:
        text = (
            "📭 <b>MENING TESTLARIM</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Hali test yaratmagansiz.\n➕ Test Yaratish bo'limidan boshlang!"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    cats = {}
    for t in tests:
        c = t.get("category") or "Boshqa"
        cats.setdefault(c, 0)
        cats[c] += 1

    sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)
    text = (
        f"🗂 <b>MENING TESTLARIM — FANLAR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(tests)} ta test | {len(cats)} ta fan</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for cat, cnt in sorted_cats:
        icon  = get_cat_icon(cat)
        text += f"{icon} <b>{cat}</b> — {cnt} ta\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {cat} — {cnt} ta",
            callback_data=f"mycat_{cat[:30]}_0"
        ))
    b.row(InlineKeyboardButton(text="🌟 Hammasi",     callback_data="mycat_ALL_0"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ── Fan ichidagi testlar (5 tadan, to'liq ma'lumot) ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data.startswith("mycat_"))
async def mycat_cb(callback: CallbackQuery):
    await callback.answer()
    raw      = callback.data[6:]  # "Matematika_0" yoki "ALL_2"
    parts    = raw.rsplit("_",1)
    cat_name = parts[0]
    page     = int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
    await _show_mycat_tests(callback.message, callback.from_user.id, cat_name, page, edit=True)

async def _show_mycat_tests(msg, uid, cat_name, page=0, edit=False):
    tests = get_my_tests(uid)
    if cat_name != "ALL":
        tests = [t for t in tests if t.get("category")==cat_name]
    if not tests:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_mytests"))
        try: await msg.edit_text("📭 Bu fanda test yo'q.", reply_markup=b.as_markup())
        except: pass
        return

    PG    = 5
    total = (len(tests)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = tests[page*PG:(page+1)*PG]
    title = "🌟 BARCHA TESTLAR" if cat_name=="ALL" else f"📚 {cat_name.upper()}"
    vis_m = {"public":"🌍 Ommaviy","link":"🔗 Ssilka","private":"🔒 Shaxsiy"}
    diff_m= {"easy":"🟢 Oson","medium":"🟡 O'rtacha","hard":"🔴 Qiyin","expert":"⚡ Ekspert"}

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta test | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()

    for t in chunk:
        tid    = t.get("test_id","")
        t_t    = t.get("title","Nomsiz")
        vis    = vis_m.get(t.get("visibility",""),"")
        diff   = diff_m.get(t.get("difficulty",""),"")
        qc     = t.get("question_count",len(t.get("questions",[])))
        sc     = t.get("solve_count",0)
        avg    = round(t.get("avg_score",0),1)
        ps     = t.get("passing_score",60)
        att_t  = f"{t.get('max_attempts',0)}x" if t.get("max_attempts",0) else "♾"
        tl_t   = f"{t.get('time_limit',0)}daq" if t.get("time_limit",0) else "♾"
        pt_t   = f"{t.get('poll_time',30)}s"
        paused = "⏸ " if t.get("is_paused") else ""
        created= t.get("created_at","")[:10]

        text += (
            f"{'━━━━━━━━━━━━━━━━━━━━━━━━'}\n"
            f"{paused}<b>{t_t}</b> <code>[{tid}]</code>\n"
            f"📁 {t.get('category','')} | {diff}\n"
            f"🔒 {vis}\n"
            f"📋 {qc} savol | ⏱ {tl_t} / Poll: {pt_t}\n"
            f"🎯 O'tish: {ps}% | 🔄 {att_t}\n"
            f"👥 {sc} yechgan | ⭐ {avg}% | 📅 {created}\n\n"
        )
        b.row(InlineKeyboardButton(
            text=f"⚙️ Sozlamalar — {t_t[:20]}",
            callback_data=f"mytest_settings_{tid}"
        ))

    # Navigatsiya
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"mycat_{cat_name}_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"mycat_{cat_name}_{page+1}"))
    if nav: b.row(*nav)
    b.row(
        InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_mytests"),
        InlineKeyboardButton(text="🏠 Menyu",  callback_data="main_menu"),
    )
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ══ TEST SOZLAMALARI ═══════════════════════════════════════════
@router.callback_query(F.data.startswith("mytest_settings_"))
async def mytest_settings_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[16:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    from config import ADMIN_IDS
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    await _show_test_settings(callback.message, meta, tid, edit=True)

async def _show_test_settings(msg, meta, tid, edit=False):
    vis_m  = {"public":"🌍 Ommaviy","link":"🔗 Ssilka orqali","private":"🔒 Shaxsiy"}
    diff_m = {"easy":"🟢 Oson","medium":"🟡 O'rtacha","hard":"🔴 Qiyin","expert":"⚡ Ekspert"}
    paused = meta.get("is_paused",False)
    att_t  = f"{meta.get('max_attempts',0)} marta" if meta.get("max_attempts",0) else "Cheksiz"
    tl_t   = f"{meta.get('time_limit',0)} daqiqa" if meta.get("time_limit",0) else "Cheksiz"
    text = (
        f"⚙️ <b>TEST SOZLAMALARI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'⏸ <b>VAQTINCHA TO\'XTATILGAN</b>\n\n' if paused else ''}"
        f"📝 <b>{meta.get('title','?')}</b>\n"
        f"🆔 Kod: <code>{tid}</code>\n"
        f"📁 Fan: {meta.get('category','')}\n"
        f"📊 Qiyinlik: {diff_m.get(meta.get('difficulty',''),'')}\n"
        f"🔒 Ko'rinish: {vis_m.get(meta.get('visibility',''),'')}\n"
        f"📋 Savollar: <b>{meta.get('question_count',0)} ta</b>\n"
        f"⏱ Vaqt limiti: {tl_t}\n"
        f"⏱ Poll vaqti: {meta.get('poll_time',30)}s/savol\n"
        f"🎯 O'tish foizi: <b>{meta.get('passing_score',60)}%</b>\n"
        f"🔄 Urinishlar: {att_t}\n"
        f"👥 Yechilgan: <b>{meta.get('solve_count',0)} marta</b>\n"
        f"⭐ O'rtacha: <b>{round(meta.get('avg_score',0),1)}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    # Kirish nazorati
    allowed = meta.get("allowed_users", [])
    if allowed:
        text += f"\n🔐 <b>Kirish nazorati:</b> {len(allowed)} ta foydalanuvchi"
    else:
        text += "\n🔓 Kirish nazorati: <i>hammaga ochiq</i>"
    kb = mytest_settings_kb(tid, is_paused=paused)
    try:
        if edit: await msg.edit_text(text, reply_markup=kb)
        else:    await msg.answer(text, reply_markup=kb)
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("edit_title_"))
async def edit_title_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    tid = callback.data[11:]
    uid = callback.from_user.id
    from config import ADMIN_IDS
    meta = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    await state.set_state(EditTestTitle.waiting_title)
    await state.update_data(edit_title_tid=tid)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data=f"mytest_settings_{tid}"))
    await callback.message.edit_text(
        f"✏️ <b>Yangi nom kiriting</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Hozirgi nom: <b>{meta.get('title','?')}</b>\n\n"
        f"Yangi nomni yozing:",
        reply_markup=b.as_markup()
    )


@router.message(EditTestTitle.waiting_title)
async def edit_title_input(message: Message, state: FSMContext):
    new_title = message.text.strip() if message.text else ""
    if not new_title or len(new_title) > 100:
        return await message.answer("❌ Nom 1-100 belgi bo'lishi kerak.")
    d   = await state.get_data()
    tid = d.get("edit_title_tid", "")
    await state.clear()
    if not tid:
        return await message.answer("❌ Test topilmadi.")
    from utils.ram_cache import update_test_meta, get_test_meta
    from utils import tg_db
    update_test_meta(tid, {"title": new_title})
    try:
        await tg_db.update_test_meta_tg(tid, {"title": new_title})
    except Exception as e:
        log.error(f"edit_title TG save xato: {e}")
    meta = get_test_meta(tid) or {}
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data=f"mytest_settings_{tid}"))
    b.row(InlineKeyboardButton(text="⬅️ Mening testlarim", callback_data="back_to_mytests"))
    await message.answer(
        f"✅ <b>Test nomi o'zgartirildi!</b>\n\n"
        f"📝 Yangi nom: <b>{new_title}</b>\n"
        f"🆔 <code>{tid}</code>",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("edit_att_"))
async def edit_att_cb(callback: CallbackQuery):
    await callback.answer()
    tid = callback.data[9:]
    b = InlineKeyboardBuilder()
    for a in [1, 2, 3, 5, 10]:
        b.add(InlineKeyboardButton(text=f"🔄 {a}x", callback_data=f"set_att_{tid}_{a}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data=f"set_att_{tid}_0"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"mytest_settings_{tid}"))
    await callback.message.edit_text(
        "<b>🔄 Urinishlar sonini ozgartirish</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Har foydalanuvchi necha marta ishlashi mumkin?",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("set_att_"))
async def set_att_cb(callback: CallbackQuery):
    await callback.answer()
    parts   = callback.data.split("_")
    new_att = int(parts[-1])
    tid     = "_".join(parts[2:-1])
    from utils.ram_cache import update_test_meta, get_test_meta
    from utils import tg_db
    update_test_meta(tid, {"max_attempts": new_att})
    asyncio.create_task(tg_db.update_test_meta_tg(tid, {"max_attempts": new_att}))
    att_t = f"{new_att} marta" if new_att else "Cheksiz"
    meta  = get_test_meta(tid) or {}
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"mytest_settings_{tid}"))
    await callback.message.edit_text(
        f"✅ <b>Urinishlar soni yangilandi!</b>\n\n"
        f"🔄 Urinish: <b>{att_t}</b>\n"
        f"📝 Test: {meta.get('title', tid)}",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("edit_poll_time_"))
async def edit_poll_time_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[15:]
    meta = get_test_meta(tid) or {}
    cur  = meta.get("poll_time", 30)
    b    = InlineKeyboardBuilder()
    for sec in [10, 15, 20, 30, 45, 60, 90, 120]:
        mark = "✅ " if sec == cur else ""
        b.add(InlineKeyboardButton(
            text=f"{mark}{sec}s",
            callback_data=f"set_poll_time_{tid}_{sec}"
        ))
    b.adjust(4)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"mytest_settings_{tid}"))
    try:
        await callback.message.edit_text(
            f"⏱ <b>POLL VAQTINI O'ZGARTIRISH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Test: <b>{meta.get('title', tid)}</b>\n"
            f"Hozir: <b>{cur}s</b>/savol\n\n"
            f"Har savol uchun necha sekund berilsin?",
            reply_markup=b.as_markup()
        )
    except Exception as e:
        await callback.message.answer(str(e))


@router.callback_query(F.data.startswith("set_poll_time_"))
async def set_poll_time_cb(callback: CallbackQuery):
    await callback.answer()
    parts    = callback.data.split("_")
    # format: set_poll_time_TID_SEC
    new_sec  = int(parts[-1])
    tid      = "_".join(parts[3:-1])
    from utils.ram_cache import update_test_meta
    from utils import tg_db
    update_test_meta(tid, {"poll_time": new_sec})
    # TG indexda va test_XXX.json da ham yangilash
    async def _save_poll_time():
        try:
            await tg_db.update_test_meta_tg(tid, {"poll_time": new_sec})
            # test_XXX.json ni ham qayta yozish (to'liq fayl)
            test = await tg_db.get_test_full(tid)
            if test and test.get("questions"):
                test["poll_time"] = new_sec
                await tg_db.save_test_full(test)
        except Exception as e:
            log.error(f"set_poll_time TG save xato: {e}")
    asyncio.create_task(_save_poll_time())
    meta = get_test_meta(tid) or {}
    b    = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data=f"mytest_settings_{tid}"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"edit_poll_time_{tid}"))
    try:
        await callback.message.edit_text(
            f"✅ <b>Poll vaqti o'zgartirildi!</b>\n\n"
            f"⏱ Yangi vaqt: <b>{new_sec}s</b>/savol\n"
            f"📝 Test: {meta.get('title', tid)}",
            reply_markup=b.as_markup()
        )
    except Exception: pass


# ══ KIRISH NAZORATI ═══════════════════════════════════════════

@router.callback_query(F.data.startswith("edit_allowed_"))
async def edit_allowed_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    tid  = callback.data[13:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid) or {}
    from config import ADMIN_IDS

    # Ruxsat: o'z testi yoki admin
    if uid not in ADMIN_IDS and meta.get("creator_id") != uid:
        return await callback.answer("⚠️ Faqat o'z testingizni sozlay olasiz!", show_alert=True)

    allowed = meta.get("allowed_users", [])
    allowed_txt = ", ".join(str(i) for i in allowed) if allowed else "Yo'q"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ ID qo'shish",   callback_data=f"allowed_add_{tid}"))
    if allowed:
        b.row(InlineKeyboardButton(text="➖ ID o'chirish", callback_data=f"allowed_del_{tid}"))
        b.row(InlineKeyboardButton(text="🔄 Ro'yxatni almashtirish", callback_data=f"allowed_replace_{tid}"))
        b.row(InlineKeyboardButton(text="🔓 Hammaga ochish", callback_data=f"allowed_clear_{tid}"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"mytest_settings_{tid}"))

    status = f"🔐 <b>Qulflangan</b> — {len(allowed)} ta foydalanuvchi" if allowed else "🔓 <b>Hammaga ochiq</b>"
    ids_txt = "\n".join(f"• <code>{i}</code>" for i in allowed) if allowed else "<i>Ro'yxat bo'sh</i>"
    try:
        await callback.message.edit_text(
            f"🔐 <b>KIRISH NAZORATI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 <b>{meta.get('title', tid)}</b>\n"
            f"Holat: {status}\n\n"
            f"<b>Ruxsat etilgan IDlar:</b>\n"
            f"{ids_txt}",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"🔐 Kirish nazorati: {status}",
            reply_markup=b.as_markup()
        )


@router.callback_query(F.data.startswith("allowed_clear_"))
async def allowed_clear_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[14:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid) or {}
    from config import ADMIN_IDS
    from utils.roles import get_role, ROLE_LEVELS
    if uid not in ADMIN_IDS and meta.get("creator_id") != uid:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    from utils.ram_cache import update_test_meta
    from utils import tg_db
    update_test_meta(tid, {"allowed_users": []})
    tg_db.mark_stats_dirty()
    async def _clear_allowed():
        try:
            await tg_db.update_test_meta_tg(tid, {"allowed_users": []})
        except Exception as e:
            log.error(f"allowed_clear TG save xato: {e}")
    asyncio.create_task(_clear_allowed())
    await callback.answer("🔓 Hammaga ochildi!", show_alert=True)
    await edit_allowed_cb(callback)


@router.callback_query(F.data.startswith("allowed_del_"))
async def allowed_del_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    tid  = callback.data[12:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid) or {}
    from config import ADMIN_IDS
    from utils.roles import get_role, ROLE_LEVELS
    if uid not in ADMIN_IDS and meta.get("creator_id") != uid:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    await state.set_state(AllowedUsersState.waiting_ids)
    await state.update_data(allowed_tid=tid, allowed_mode="delete")
    allowed = meta.get("allowed_users", [])
    cur_txt = ", ".join(str(i) for i in allowed) if allowed else "yo'q"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data=f"edit_allowed_{tid}"))
    try:
        await callback.message.edit_text(
            f"➖ <b>ID O'CHIRISH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Hozirgi ro'yxat:\n<code>{cur_txt}</code>\n\n"
            f"O'chirmoqchi bo'lgan IDlarni yuboring:\n"
            f"<code>1919293828, 1728393992</code>",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer("O'chirmoqchi IDlarni yuboring:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("allowed_replace_"))
async def allowed_replace_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    tid  = callback.data[16:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid) or {}
    from config import ADMIN_IDS
    from utils.roles import get_role, ROLE_LEVELS
    if uid not in ADMIN_IDS and meta.get("creator_id") != uid:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    await state.set_state(AllowedUsersState.waiting_ids)
    await state.update_data(allowed_tid=tid, allowed_mode="replace")
    allowed = meta.get("allowed_users", [])
    cur_txt = ", ".join(str(i) for i in allowed) if allowed else "yo'q"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data=f"edit_allowed_{tid}"))
    try:
        await callback.message.edit_text(
            f"🔄 <b>RO'YXATNI ALMASHTIRISH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Hozirgi: <code>{cur_txt}</code>\n\n"
            f"Yangi IDlarni yuboring (eskisi o'chadi):\n"
            f"<code>1919293828, 1728393992, 18283837</code>",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer("Yangi IDlarni yuboring:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("allowed_add_"))
async def allowed_add_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    tid = callback.data[12:]
    uid = callback.from_user.id
    meta = get_test_meta(tid) or {}
    from config import ADMIN_IDS
    from utils.roles import get_role, ROLE_LEVELS
    role = get_role(uid)
    is_admin = uid in ADMIN_IDS
    is_teacher = ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS["teacher"]
    if not is_admin and not is_teacher:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    if is_teacher and not is_admin and meta.get("creator_id") != uid:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    await state.set_state(AllowedUsersState.waiting_ids)
    await state.update_data(allowed_tid=tid, allowed_mode="add")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data=f"edit_allowed_{tid}"))
    allowed = meta.get("allowed_users", [])
    cur_txt = ", ".join(str(i) for i in allowed) if allowed else "hali yo'q"
    try:
        await callback.message.edit_text(
            f"➕ <b>ID QO'SHISH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Hozirgi ro'yxat: <code>{cur_txt}</code>\n\n"
            f"Qo'shmoqchi bo'lgan IDlarni yuboring:\n"
            f"<code>1919293828, 1728393992</code>\n\n"
            f"<i>Yangi IDlar mavjud ro'yxatga qo'shiladi</i>",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer("IDlarni yuboring:", reply_markup=b.as_markup())


@router.message(AllowedUsersState.waiting_ids)
async def allowed_ids_received(message: Message, state: FSMContext):
    import re
    d    = await state.get_data()
    tid  = d.get("allowed_tid", "")
    mode = d.get("allowed_mode", "add")   # add | replace | delete
    await state.clear()

    raw_ids = re.findall(r"\d{5,12}", message.text or "")
    new_ids = [int(i) for i in raw_ids]

    if not new_ids:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔄 Qayta", callback_data=f"edit_allowed_{tid}"))
        return await message.answer(
            "❌ Hech qanday to'g'ri ID topilmadi.\n"
            "ID 5-12 xonali raqam bo'lishi kerak.",
            reply_markup=b.as_markup()
        )

    from utils.ram_cache import update_test_meta, get_test_meta as _gtm
    from utils import tg_db
    import asyncio

    meta    = _gtm(tid) or {}
    current = meta.get("allowed_users", [])

    if mode == "add":
        result = list(dict.fromkeys(current + new_ids))   # Dublikat yo'q
        action = f"➕ {len(new_ids)} ta ID qo'shildi"
    elif mode == "replace":
        result = new_ids
        action = f"🔄 Ro'yxat almashtirildi"
    elif mode == "delete":
        result = [i for i in current if i not in new_ids]
        removed = len(current) - len(result)
        action = f"➖ {removed} ta ID o'chirildi"
    else:
        result = new_ids
        action = "✅ Saqlandi"

    update_test_meta(tid, {"allowed_users": result})
    tg_db.mark_stats_dirty()
    async def _save_allowed():
        try:
            await tg_db.update_test_meta_tg(tid, {"allowed_users": result})
        except Exception as e:
            log.error(f"allowed_ids TG save xato: {e}")
    asyncio.create_task(_save_allowed())

    status  = f"🔐 {len(result)} ta foydalanuvchi" if result else "🔓 Hammaga ochiq"
    ids_txt = ", ".join(str(i) for i in result) if result else "yo'q"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔐 Kirish nazorati", callback_data=f"edit_allowed_{tid}"))
    b.row(InlineKeyboardButton(text="⚙️ Sozlamalar",      callback_data=f"mytest_settings_{tid}"))
    await message.answer(
        f"✅ <b>{action}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {meta.get('title', tid)}\n"
        f"Holat: {status}\n"
        f"<code>{ids_txt[:200]}</code>",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("mytest_view_"))
async def my_test_view(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[12:]
    uid  = callback.from_user.id
    test = get_test_by_id(tid) or await get_test_full(tid)
    if not test:
        return await callback.message.answer("❌ Test topilmadi.")
    from handlers.start import _send_test_card
    await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)


@router.callback_query(F.data.startswith("mytest_txt_"))
async def my_test_to_txt(callback: CallbackQuery):
    await callback.answer("⏳ TXT tayyorlanmoqda...")
    tid  = callback.data[11:]
    test = await get_test_full(tid) or get_test_by_id(tid)
    if not test:
        return await callback.message.answer("❌ Test topilmadi.")
    txt = _test_to_txt(test)
    doc = BufferedInputFile(txt.encode("utf-8"), filename=f"{test.get('title',tid)}.txt")
    await callback.message.answer_document(
        doc,
        caption=f"📄 <b>{test.get('title')}</b>\n📋 {len(test.get('questions',[]))} savol | <code>{tid}</code>"
    )


# ── Test o'chirish (faqat mening testlarim dan) ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data.startswith("del_mytest_"))
async def del_mytest_confirm(callback: CallbackQuery):
    tid  = callback.data[11:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    from config import ADMIN_IDS
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Faqat test egasi o'chira oladi!", show_alert=True)
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"del_mytest_ok_{tid}"),
        InlineKeyboardButton(text="❌ Yo'q",          callback_data=f"mytest_settings_{tid}"),
    )
    try:
        await callback.message.edit_text(
            f"⚠️ <b>O'CHIRISH TASDIQLASH</b>\n\n"
            f"📝 {meta.get('title','?')} [{tid}]\n\n"
            f"Test RAMdan va TG bazadan <b>butunlay o'chiriladi</b>.\n"
            f"Bu amalni qaytarib bo'lmaydi!",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"⚠️ {meta.get('title','?')} [{tid}] ni o'chirilsinmi?",
            reply_markup=b.as_markup()
        )

@router.callback_query(F.data.startswith("del_mytest_ok_"))
async def del_mytest_exec(callback: CallbackQuery):
    await callback.answer("⏳ O'chirilmoqda...")   # DARHOL javob
    tid = callback.data[14:]
    uid = callback.from_user.id
    meta= get_test_meta(tid)
    from config import ADMIN_IDS
    if uid != (meta or {}).get("creator_id") and uid not in ADMIN_IDS:
        return
    from utils.db import delete_test
    await delete_test(tid)
    try:
        await callback.message.edit_text(
            f"✅ <b>{meta.get('title','?')} [{tid}]</b> muvaffaqiyatli o'chirildi.\n"
            f"Backup TG ga yuborildi."
        )
    except: pass
    # Fanlar sahifasiga qaytish
    await _show_mytest_cats(callback.message, uid)


# ── Kim yechgan ━━━━━━━━━━━━━━━━━━━━━━━━
@router.callback_query(F.data.startswith("test_solvers_"))
async def test_solvers_cb(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data[13:].rsplit("_",1)
    tid   = parts[0]
    page  = int(parts[1]) if len(parts)>1 else 0
    uid   = callback.from_user.id
    meta  = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    from config import ADMIN_IDS
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    solvers = get_test_solvers(tid)
    if not solvers:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"mytest_settings_{tid}"))
        try:
            await callback.message.edit_text(
                f"📊 <b>{meta.get('title','?')} — KIM YECHGAN</b>\n\n😔 Hali hech kim yechmagan.",
                reply_markup=b.as_markup()
            )
        except TelegramBadRequest: pass
        return

    PG    = 5
    total = (len(solvers)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = solvers[page*PG:(page+1)*PG]
    text  = (
        f"📊 <b>{meta.get('title','?')} — KIM YECHGAN</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 {len(solvers)} kishi | Sahifa {page+1}/{total}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    b = InlineKeyboardBuilder()
    for sv in chunk:
        all_p = " → ".join(f"{p}%" for p in sv["all_pcts"])
        uname = f"@{sv['username']}" if sv.get("username") else ""
        text += (
            f"👤 <b>{sv['name']}</b> {uname}\n"
            f"   🔄 {sv['attempts']}x | ⭐ {sv['best_score']}%\n"
            f"   📈 {all_p}\n\n"
        )
        b.row(InlineKeyboardButton(
            text=f"🔍 {sv['name'][:20]} — {sv['best_score']}%",
            callback_data=f"solver_detail_{tid}_{sv['uid']}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"test_solvers_{tid}_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"test_solvers_{tid}_{page+1}"))
    if nav: b.row(*nav)
    b.row(
        InlineKeyboardButton(text="📄 TXT",     callback_data=f"solvers_txt_{tid}"),
        InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"mytest_settings_{tid}"),
    )
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("solver_detail_"))
async def solver_detail_cb(callback: CallbackQuery):
    await callback.answer()
    parts   = callback.data[14:].split("_",1)
    tid     = parts[0]
    uid_str = parts[1] if len(parts)>1 else ""
    viewer  = callback.from_user.id
    meta    = get_test_meta(tid)
    from config import ADMIN_IDS
    if viewer != meta.get("creator_id") and viewer not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    solvers = get_test_solvers(tid)
    sv      = next((s for s in solvers if s["uid"]==uid_str), None)
    if not sv:
        return await callback.answer("Topilmadi.", show_alert=True)
    first    = sv.get("first_result") or {}
    all_pcts = sv.get("all_pcts",[])
    ps       = meta.get("passing_score",60)
    att_txt  = "\n".join(
        f"  {'✅' if p>=ps else '❌'} {i+1}-urinish: {p}%"
        for i,p in enumerate(all_pcts)
    )
    text = (
        f"👤 <b>{sv['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 {sv['attempts']} urinish | ⭐ {sv['best_score']}% | 📈 {sv['avg_score']}%\n\n"
        f"<b>Barcha urinishlar:</b>\n<code>{att_txt}</code>\n\n"
        f"<b>1-urinish:</b> {first.get('percentage',0)}% | "
        f"✅{first.get('correct_count',0)} ❌{first.get('wrong_count',0)}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"test_solvers_{tid}_0"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("solvers_txt_"))
async def solvers_txt_cb(callback: CallbackQuery):
    await callback.answer("⏳ TXT tayyorlanmoqda...")
    tid  = callback.data[12:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)
    from config import ADMIN_IDS
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    solvers = get_test_solvers(tid)
    lines   = [f"TEST: {meta.get('title',tid)}", f"KOD: {tid}",
               f"JAMI: {len(solvers)} kishi", "="*55, ""]
    for i, sv in enumerate(solvers,1):
        all_p = " → ".join(f"{p}%" for p in sv["all_pcts"])
        lines.append(f"{i}. {sv['name']}")
        if sv.get("username"): lines.append(f"   @{sv['username']}")
        lines.append(f"   Urinishlar: {sv['attempts']}")
        lines.append(f"   Foizlar: {all_p}")
        lines.append(f"   Eng yaxshi: {sv['best_score']}%")
        fr = sv.get("first_result") or {}
        if fr:
            lines.append(
                f"   1-urinish: {fr.get('percentage',0)}% | "
                f"To'g'ri:{fr.get('correct_count',0)} Xato:{fr.get('wrong_count',0)}"
            )
        lines.append("")
    doc = BufferedInputFile(
        "\n".join(lines).encode("utf-8"),
        filename=f"solvers_{meta.get('title',tid)}.txt"
    )
    await callback.message.answer_document(
        doc, caption=f"📊 <b>{meta.get('title',tid)}</b>\n👥 {len(solvers)} kishi"
    )


@router.callback_query(F.data == "go_tests")
async def go_tests_cb(callback: CallbackQuery):
    await callback.answer()
    from handlers.tests import _show_categories
    await _show_categories(callback.message, callback.from_user.id, edit=True)


def _test_to_txt(test):
    import re
    labels = ["A", "B", "C", "D", "E", "F"]
    lines  = []
    for i, q in enumerate(test.get("questions", []), 1):
        qtype = q.get("type", "multiple_choice")
        qtext = q.get("question", q.get("text", "")).strip()
        corr  = q.get("correct", "")
        opts  = q.get("options", [])

        lines.append(f"{i}. {qtext}")

        if qtype == "true_false":
            ans = "Ha" if str(corr).lower() in ("ha", "true", "1", "yes") else "Yo'q"
            lines.append(f"*Javob: {ans}")

        elif qtype in ("multiple_choice", "multi_select"):
            # To'g'ri javob indeksini aniqlash
            correct_idx = None
            if isinstance(corr, int):
                correct_idx = corr
            elif isinstance(corr, str):
                # "A", "B" harfi bo'lsa
                m = re.match(r'^([A-Za-z])', corr.strip())
                if m:
                    correct_idx = ord(m.group(1).upper()) - ord('A')
                else:
                    # Matn bo'lsa — mos variantni qidirish
                    for j, opt in enumerate(opts):
                        opt_clean = re.sub(r'^[A-Za-z]\)', '', str(opt)).strip()
                        if opt_clean == corr.strip() or str(opt).strip() == corr.strip():
                            correct_idx = j
                            break

            for j, opt in enumerate(opts[:6]):
                # Variant matni — "A) " prefiksini olib tashlash
                opt_s = re.sub(r'^[A-Za-z]\)\s*', '', str(opt)).strip()
                label = labels[j] if j < len(labels) else str(j+1)
                is_correct = (j == correct_idx)
                prefix = "*" if is_correct else ""
                lines.append(f"{prefix}{label}) {opt_s}")

        else:
            # To'ldirish / matnli javob
            lines.append(f"*Javob: {corr}")

        expl = q.get("explanation", "")
        if expl and expl not in ("Izoh kiritilmagan.", "Izoh yo'q", ""):
            lines.append(f"Izoh: {expl}")

        lines.append("")  # Bo'sh qator savollar orasida

    return "\n".join(lines).strip()
