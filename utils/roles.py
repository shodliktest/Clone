"""
ROLES — Foydalanuvchi darajalari tizimi
========================================
Darajalar (pastdan tepaga):
  guest   → Hali ro'yxatdan o'tmagan
  user    → Yangi kirgan (test yarata olmaydi, test yechi oladi)
  student → Referal yoki admin tomonidan ko'tarilgan
             (shaxsiy/link test yarata oladi, public emas)
  teacher → Admin tomonidan tayinlangan
             (barcha turdagi test yarata oladi)
  admin   → To'liq huquq

Referal tizimi:
  - user ro'yxatdan o'tganda referral_code generatsiya qilinadi
  - Har kuni 1 ta yangi referal → o'sha kun test yaratish imkoni
  - 1 kun ichida 10 ta referal → 30 kun student status
  - student status vaqti tugasa → user ga qaytadi

O'zgartirishlar faqat shu faylda va handlers/roles_admin.py da.
Mavjud bot.py, db.py ga ta'sir qilmaydi.
"""

from datetime import datetime, timedelta, timezone
from utils import ram_cache as ram

UTC = timezone.utc

# ── Daraja tartibi ────────────────────────────────────────────
ROLE_LEVELS = {
    "guest":   0,
    "user":    1,
    "student": 2,
    "teacher": 3,
    "admin":   4,
}

ROLE_LABELS = {
    "guest":   "👤 Mehmon",
    "user":    "👤 Foydalanuvchi",
    "student": "🎓 Student",
    "teacher": "👨‍🏫 Teacher",
    "admin":   "👑 Admin",
}

# Necha kun uchun muddatlar (admin sozlashi uchun)
DURATION_OPTIONS = {
    "3d":   ("3 kun",    3),
    "7d":   ("7 kun",    7),
    "14d":  ("14 kun",  14),
    "30d":  ("30 kun",  30),
    "90d":  ("90 kun",  90),
    "perm": ("Cheksiz", None),
}

# ── Huquqlar ──────────────────────────────────────────────────
def get_global_config() -> dict:
    """Global bot sozlamalari (admin tomonidan o'zgartiriladi)."""
    return ram._get("global_config", {})

def set_global_config(updates: dict):
    """Global sozlamalarni yangilash."""
    cfg = get_global_config()
    cfg.update(updates)
    ram._set("global_config", cfg)

def can_create_public_test(uid: int, admin_ids: list) -> bool:
    """Ommaviy test yarata oladimi? Faqat teacher va admin."""
    if uid in admin_ids:
        return True
    user = ram.get_user(uid)
    if not user:
        return False
    role = user.get("role", "user")
    return ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS["teacher"]

def can_create_any_test(uid: int, admin_ids: list) -> bool:
    """Umuman test yarata oladimi? (shaxsiy/link)"""
    if uid in admin_ids:
        return True
    user = ram.get_user(uid)
    if not user:
        return False

    # Global sozlama: admin "hammaga ruxsat" qilganmi?
    cfg = get_global_config()
    if cfg.get("open_test_creation", False):
        return True

    # Vaqtinchalik student huquqini tekshirish
    _check_expire_role(uid, user)
    role = user.get("role", "user")
    if ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS["student"]:
        return True
    # Bugungi referal berganmi
    return bool(get_today_referral_bonus(uid))

def get_role(uid: int) -> str:
    user = ram.get_user(uid)
    if not user:
        return "guest"
    _check_expire_role(uid, user)
    return user.get("role", "user")

def get_role_label(uid: int) -> str:
    return ROLE_LABELS.get(get_role(uid), "👤 Foydalanuvchi")

# ── Role o'zgartirish ─────────────────────────────────────────
def set_role(uid: int, role: str, duration_key: str = "perm") -> dict:
    """
    Foydalanuvchi rolini o'zgartirish.
    duration_key: '3d','7d','14d','30d','90d','perm'
    """
    from utils.db import update_user
    user = ram.get_user(uid) or {}
    now  = datetime.now(UTC)

    days = DURATION_OPTIONS.get(duration_key, ("Cheksiz", None))[1]
    expires_at = None
    if days is not None:
        expires_at = (now + timedelta(days=days)).isoformat()

    update_user(uid, {
        "role":             role,
        "role_expires_at":  expires_at,
        "role_set_at":      now.isoformat(),
        "role_duration":    duration_key,
    })
    return {
        "role":       role,
        "expires_at": expires_at,
        "duration":   DURATION_OPTIONS.get(duration_key, ("?",))[0],
    }

def _check_expire_role(uid: int, user: dict):
    """Muddati tugagan rolni user ga qaytarish."""
    expires = user.get("role_expires_at")
    if not expires:
        return
    try:
        exp_dt = datetime.fromisoformat(expires)
        if datetime.now(UTC) > exp_dt:
            from utils.db import update_user
            update_user(uid, {
                "role":            "user",
                "role_expires_at": None,
            })
    except Exception:
        pass

# ── Referal tizimi ─────────────────────────────────────────────
def get_referral_code(uid: int) -> str:
    """Foydalanuvchining referal kodi (uid asosida)."""
    return f"ref{uid}"

def get_referral_stats(uid: int) -> dict:
    """Referal statistikasi."""
    user = ram.get_user(uid) or {}
    return {
        "total":     user.get("referral_count", 0),
        "today":     user.get("referral_today", 0),
        "today_date":user.get("referral_today_date", ""),
        "bonus_days":user.get("referral_bonus_days", 0),
    }

def get_today_referral_bonus(uid: int) -> bool:
    """Bugun referal berganmi → bugun test yaratish imkoni."""
    user = ram.get_user(uid) or {}
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return user.get("referral_today_date", "") == today and user.get("referral_today", 0) > 0

def process_referral(new_uid: int, referrer_uid: int, admin_ids: list) -> dict:
    """
    Yangi foydalanuvchi ref_uid kodi orqali keldi.
    Refererni mukofotlash.
    """
    from utils.db import update_user
    result = {"ok": False, "msg": ""}

    if new_uid == referrer_uid:
        return {"ok": False, "msg": "O'zingizni taklif qila olmaysiz"}

    referrer = ram.get_user(referrer_uid)
    if not referrer:
        return {"ok": False, "msg": "Referer topilmadi"}

    # Yangi user allaqachon bu referalni ishlatganmi
    new_user = ram.get_user(new_uid) or {}
    if new_user.get("referred_by") == referrer_uid:
        return {"ok": False, "msg": "Allaqachon taklif qilingan"}

    now   = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")

    total  = referrer.get("referral_count", 0) + 1
    r_date = referrer.get("referral_today_date", "")
    r_today= referrer.get("referral_today", 0)

    if r_date == today:
        r_today += 1
    else:
        r_today  = 1
        r_date   = today

    updates = {
        "referral_count":      total,
        "referral_today":      r_today,
        "referral_today_date": r_date,
    }

    msg_parts = [f"✅ Referal qabul qilindi! Jami: {total}"]

    # 10 ta kunlik referal → 30 kun student
    if r_today >= 10:
        role = referrer.get("role", "user")
        if ROLE_LEVELS.get(role, 0) < ROLE_LEVELS["student"]:
            exp = (now + timedelta(days=30)).isoformat()
            updates["role"]            = "student"
            updates["role_expires_at"] = exp
            updates["role_set_at"]     = now.isoformat()
            bonus = referrer.get("referral_bonus_days", 0) + 30
            updates["referral_bonus_days"] = bonus
            msg_parts.append("🎉 1 oy student status berildi!")
        elif role == "student":
            # Muddatni uzaytirish
            exp_str = referrer.get("role_expires_at")
            try:
                exp_dt = datetime.fromisoformat(exp_str) if exp_str else now
                new_exp = (exp_dt + timedelta(days=30)).isoformat()
            except:
                new_exp = (now + timedelta(days=30)).isoformat()
            updates["role_expires_at"] = new_exp
            bonus = referrer.get("referral_bonus_days", 0) + 30
            updates["referral_bonus_days"] = bonus
            msg_parts.append("🎉 Student muddat 30 kun uzaytirildi!")

    update_user(referrer_uid, updates)

    # Yangi userni ham belgilash
    update_user(new_uid, {"referred_by": referrer_uid})

    return {"ok": True, "msg": "\n".join(msg_parts), "today_count": r_today}

def format_role_info(uid: int) -> str:
    """Foydalanuvchi role ma'lumotlarini formatlash."""
    user = ram.get_user(uid) or {}
    _check_expire_role(uid, user)
    role     = user.get("role", "user")
    label    = ROLE_LABELS.get(role, "👤 Foydalanuvchi")
    expires  = user.get("role_expires_at")
    ref_stat = get_referral_stats(uid)

    lines = [f"👤 Daraja: <b>{label}</b>"]

    if expires:
        try:
            exp_dt = datetime.fromisoformat(expires)
            delta  = exp_dt - datetime.now(UTC)
            if delta.days > 0:
                lines.append(f"⏳ Muddati: <b>{delta.days} kun</b> qoldi")
            else:
                lines.append(f"⏳ Muddati: <b>Bugun tugaydi</b>")
        except:
            pass

    if ref_stat["total"] > 0:
        lines.append(f"👥 Jami referal: <b>{ref_stat['total']}</b>")
        lines.append(f"📅 Bugungi: <b>{ref_stat['today']}</b>")

    return "\n".join(lines)
