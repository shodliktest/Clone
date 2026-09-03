Guruhlar ro'yxati va e'lon fix

Yangilangan:
- bot.py
- handlers/admin.py
- utils/states.py

Asosiy o'zgarishlar:
1) known_groups Supabase'dan startup vaqtida to'liq yuklanadi.
2) Guruh e'lon menyusi ochilganda Telegram orqali known_groups qayta tekshiriladi.
3) Botning haqiqiy statusi administrator/creator ekanligi tekshiriladi.
4) Guruh ID bilan qo'shish funksiyasi qo'shildi: admin panel -> Guruh E'lon -> Guruh qo'shish.
5) E'lon uchun send_message/send_photo va boshqalar o'rniga copy_message ishlatiladi; admin yuborgan xabar turi va captioni saqlanadi.
6) Telegram RetryAfter bo'lsa avtomatik kutib qayta yuboriladi.
7) Yuborishdan keyingi active/status o'zgarishlari Supabase'ga saqlanadi.
8) Compileall tekshirildi.

Muhim cheklov:
Telegram Bot API botning o'zi a'zo bo'lgan barcha guruhlarni sanab beradigan endpoint bermaydi. Agar known_groups jadvali ilgari bo'sh bo'lgan bo'lsa, bot o'z-o'zidan eski barcha guruhlarni topa olmaydi. Bunday holatda admin paneldagi 'Guruh qo'shish' orqali -100... ID kiritiladi; bot Telegram orqali o'zining administrator ekanini tekshiradi va jadvalga saqlaydi.
