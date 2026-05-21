"""🌐 WEBAUTH — Sayt uchun Telegram ID orqali kirish"""
import urllib.parse
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, CommandStart

router = Router()

WEBAPP_URL = "https://quizmarkerbotweb.vercel.app"


def _login_url(user) -> str:
    """Foydalanuvchi ma'lumotlari bilan to'ldirilgan login URL qaytaradi."""
    name  = user.full_name or "Foydalanuvchi"
    uname = user.username or ""
    params = urllib.parse.urlencode({
        "uid":   user.id,
        "name":  name,
        "uname": uname,
        "auto":  "1",
    })
    return f"{WEBAPP_URL}/login.html?{params}"


async def _send_id(message: Message):
    uid   = message.from_user.id
    name  = message.from_user.full_name or "Foydalanuvchi"
    uname = f"@{message.from_user.username}" if message.from_user.username else "Mavjud emas"

    await message.answer(
        f"🌐 <b>SAYTGA KIRISH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Quyidagi ID ni saytga kiriting:\n\n"
        f"<code>{uid}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Ism: {name}\n"
        f"🔗 Username: {uname}\n\n"
        f"<i>💡 ID ni bosib nusxa oling, keyin saytga kiriting</i>"
    )


@router.message(Command("id"))
@router.message(F.text == "🌐 Sayt ID")
async def send_web_id(message: Message):
    await _send_id(message)


@router.message(CommandStart(deep_link=True, magic=F.args == "getid"))
async def start_getid(message: Message):
    await _send_id(message)


@router.message(Command("webapp"))
@router.message(F.text == "🌐 Saytga kirish")
async def open_webapp(message: Message):
    url = _login_url(message.from_user)
    b = InlineKeyboardBuilder()
    # 1. WebApp tugmasi — Telegram ichida to'g'ri ochiladi (eng qulay)
    b.row(InlineKeyboardButton(
        text="🌐 Saytni ochish (Telegram ichida)",
        web_app=WebAppInfo(url=f"{WEBAPP_URL}/login.html")
    ))
    # 2. Oddiy URL — brauzerda ochiladi, uid parametr bilan avtomatik kiradi
    b.row(InlineKeyboardButton(
        text="🔗 Brauzerda ochish",
        url=url
    ))
    await message.answer(
        "🌐 <b>TestPro saytiga kirish</b>\n\n"
        "Birinchi tugma — Telegram ichida ochadi (tavsiya etiladi)\n"
        "Ikkinchi tugma — brauzerda ochadi, avtomatik kirasiz:",
        reply_markup=b.as_markup()
    )

