"""
💰 COIN TIZIMI — yagona iqtisodiyot moduli.

Saqlash: foydalanuvchi yozuvidagi "coins" maydoni (ram_cache + TG users chunk),
ya'ni mavjud users saqlash tizimidan foydalanadi — alohida baza kerak emas,
eski ma'lumotlar yo'qolmaydi.

Narxlar ROLES global config orqali admin tomonidan o'zgartirilishi mumkin
(set_global_config({"coin_create_per_block": 1, ...})).

Qoidalar:
  • Yangi foydalanuvchi — SIGNUP_BONUS coin oladi (bir marta).
  • Referal: taklif qiluvchiga REF_REWARD, yangi userga REF_NEWUSER.
  • Test yaratish narxi: har CREATE_BLOCK savol uchun CREATE_PER_BLOCK coin,
    kamida CREATE_MIN. Teacher 50% chegirma, Admin bepul.
  • AI qayta yechish: har blok uchun AI_PER_BLOCK, kamida AI_MIN (Teacher 50%, Admin bepul).
  • Teacher darajasini coin bilan sotib olish mumkin (30/90 kun).
"""
import math
import logging
from utils import ram_cache as ram
from utils.db import update_user

log = logging.getLogger(__name__)

# ── Standart sozlamalar (global config bilan ustidan yozish mumkin) ──
DEFAULTS = {
    "coin_signup_bonus":      30,
    "coin_ref_reward":        15,   # taklif qiluvchiga
    "coin_ref_newuser":       5,    # yangi foydalanuvchiga
    "coin_create_block":      10,   # nechta savol = 1 blok
    "coin_create_per_block":  1,    # blok narxi
    "coin_create_min":        2,    # minimal narx
    "coin_ai_per_block":      2,
    "coin_ai_min":            5,
    "coin_teacher_30d":       300,
    "coin_teacher_90d":       700,
    "coin_teacher_discount":  50,   # foiz
}


def _cfg(key: str) -> int:
    try:
        from utils.roles import get_global_config
        v = get_global_config().get(key)
        if v is not None:
            return int(v)
    except Exception:
        pass
    return DEFAULTS[key]


# ── Balans amallari ──────────────────────────────────────────

def get_balance(uid: int) -> int:
    u = ram.get_user(uid) or {}
    try:
        return max(0, int(u.get("coins", 0)))
    except (TypeError, ValueError):
        return 0


def add_coins(uid: int, amount: int, reason: str = "") -> int:
    """Coin qo'shadi (amount manfiy bo'lishi mumkin — admin ayirishi).
    Yangi balansni qaytaradi. Balans 0 dan pastga tushmaydi."""
    amount = int(amount)
    bal = get_balance(uid) + amount
    if bal < 0:
        bal = 0
    update_user(uid, {"coins": bal})
    log.info(f"COIN {uid}: {amount:+d} ({reason}) → {bal}")
    return bal


def spend_coins(uid: int, amount: int, reason: str = "") -> bool:
    """Yetarli bo'lsa yechib oladi va True qaytaradi; aks holda False."""
    amount = int(amount)
    if amount <= 0:
        return True
    bal = get_balance(uid)
    if bal < amount:
        return False
    update_user(uid, {"coins": bal - amount})
    log.info(f"COIN {uid}: -{amount} ({reason}) → {bal - amount}")
    return True


def ensure_signup_bonus(uid: int) -> int:
    """Bir martalik start bonusi. Berilgan miqdorni qaytaradi (0 = avval olingan)."""
    u = ram.get_user(uid) or {}
    if u.get("coin_signup_given"):
        return 0
    bonus = _cfg("coin_signup_bonus")
    bal = get_balance(uid) + bonus
    update_user(uid, {"coins": bal, "coin_signup_given": True})
    return bonus


# ── Narx hisoblash ───────────────────────────────────────────

def _role_multiplier(uid: int) -> float:
    """Admin = 0 (bepul), Teacher = chegirma, qolganlar = 1."""
    try:
        from config import ADMIN_IDS
        if uid in ADMIN_IDS:
            return 0.0
    except Exception:
        pass
    try:
        from utils.roles import get_role
        if get_role(uid) in ("teacher", "admin"):
            disc = _cfg("coin_teacher_discount")
            return max(0.0, 1 - disc / 100.0)
    except Exception:
        pass
    return 1.0


def _block_cost(q_count: int, per_block_key: str, min_key: str) -> int:
    block = max(1, _cfg("coin_create_block"))
    blocks = math.ceil(max(1, q_count) / block)
    return max(_cfg(min_key), blocks * _cfg(per_block_key))


def create_cost(uid: int, q_count: int) -> int:
    """Test yaratish narxi (rol chegirmasi bilan)."""
    base = _block_cost(q_count, "coin_create_per_block", "coin_create_min")
    return math.ceil(base * _role_multiplier(uid))


def ai_resolve_cost(uid: int, q_count: int) -> int:
    """AI bilan qayta yechish narxi (rol chegirmasi bilan)."""
    base = _block_cost(q_count, "coin_ai_per_block", "coin_ai_min")
    return math.ceil(base * _role_multiplier(uid))


def teacher_price(days: int) -> int:
    return _cfg("coin_teacher_90d") if days >= 90 else _cfg("coin_teacher_30d")


def ref_rewards() -> tuple:
    return _cfg("coin_ref_reward"), _cfg("coin_ref_newuser")


# ── UI yordamchilari ─────────────────────────────────────────

def balance_line(uid: int) -> str:
    return f"💰 Balans: <b>{get_balance(uid)} coin</b>"


def insufficient_text(uid: int, need: int, action: str) -> str:
    bal = get_balance(uid)
    rr, _ = ref_rewards()
    return (
        f"💰 <b>Coin yetarli emas</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 {action}: <b>{need} coin</b>\n"
        f"👛 Sizda: <b>{bal} coin</b>\n"
        f"❗ Yetishmayapti: <b>{need - bal} coin</b>\n\n"
        f"Coin ishlash yo'llari:\n"
        f"  👥 Do'st chaqirish — har biri uchun <b>+{rr} coin</b>\n"
        f"  💳 Hisob to'ldirish — admin orqali"
    )
