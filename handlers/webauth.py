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


async def _open_webapp(message: Message):
    """Saytga kirish havolasini yuborish — ID so'ramasdan, avtomatik."""
    url = _login_url(message.from_user)
    b   = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="🌐 Saytni ochish (Telegram ichida)",
        web_app=WebAppInfo(url=url)
    ))
    b.row(InlineKeyboardButton(
        text="🔗 Brauzerda ochish",
        url=url
    ))
    await message.answer(
        "🌐 <b>TestPro saytiga kirish</b>\n\n"
        "Tugmani bosing — avtomatik kirasiz, ID yozish shart emas:",
        reply_markup=b.as_markup()
    )


@router.message(Command("webapp"))
@router.message(F.text == "🌐 Saytga kirish")
@router.message(F.text == "🌐 Sayt ID")  # eski tugma ham ishlaydi
async def open_webapp(message: Message):
    await _open_webapp(message)


@router.message(Command("id"))
async def send_web_id(message: Message):
    """Eski /id buyrug'i — endi ham havola beradi"""
    await _open_webapp(message)


@router.message(CommandStart(deep_link=True, magic=F.args == "getid"))
async def start_getid(message: Message):
    await _open_webapp(message)
