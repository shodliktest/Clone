"""
WEB_CMD handler — SUPABASE versiyasida KERAK EMAS.

Eski arxitekturada Streamlit → Telegram kanal xabar → bot ushbu
kanaldan "WEB_CMD:..." buyruqlarini o'qirdi (Streamlit va bot bir
xil RAM'ni ko'rolmaganidan). Supabase'da ikkalasi ham bitta
Postgres bazasiga to'g'ridan-to'g'ri yozadi/o'qiydi, shuning
uchun bu "buyruq kanali" arxitekturasi butunlay yo'qoldi.

Fayl import xatosi bermasligi uchun saqlanib qolindi, lekin
handler'lar ro'yxatga qo'shilmaydi (router bo'sh).
"""

import logging
from aiogram import Router

log    = logging.getLogger(__name__)
router = Router()

# Hech qanday handler yo'q — router bo'sh.
# bot.py ushbu router'ni include qilishda davom etaversin
# (xato bermaydi, faqat hech nima ishlamaydi).
