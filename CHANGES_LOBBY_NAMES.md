# O'zgarishlar: Guruh lobbisi ("✋ Tayyorman") va ism qoidasi

## 1. Guruhda test darhol boshlanmaydi — lobby

Oldin: `/quiz_start KOD`, `startgroup=gpoll_KOD` yoki "Guruhda Poll Test" tugmasi bosilishi bilan
sanoq boshlanardi va birinchi savol darhol ketardi (tayyor bo'lmagan odamlar savolni o'tkazib yuborardi).

Endi (Native QuizBot kabi):
1. Test chaqirilganda guruhda lobby xabari chiqadi: test nomi, savollar soni, vaqt va tugmalar.
2. **✋ Tayyorman** — har bir a'zo bosadi; tayyorlar ro'yxati jonli yangilanadi (bir kishi bir marta).
3. Kamida **2 kishi** tayyor bo'lgach, **10 soniyadan keyin** test o'zi boshlanadi (kechikkanlar ulgursin).
   Sozlash: `LOBBY_MIN_READY`, `LOBBY_START_DELAY_SEC` (`handlers/group.py`).
4. "Boshlash" tugmasi yo'q. **❌ Bekor qilish** — faqat boshlovchi yoki admin (sanoq paytida ham ishlaydi). `/quiz_stop` ham bekor qiladi.
5. 2 kishi yig'ilmasa, 10 daqiqadan keyin lobby avtomatik yopiladi.
6. Lobby ochiq bo'lganda guruhda boshqa test boshlab bo'lmaydi.

Eslatma: rejalashtirilgan (scheduler) testlar lobbysiz, vaqtida darhol boshlanadi (`lobby=False`).

Asosiy kod: `handlers/group.py` — `_open_lobby`, `lobby_ready`, `_lobby_autostart`, `lobby_cancel`, `_lobby_timeout`.

## 2. Ism qoidasi: ism yo'q bo'lsa familiya, NoName kamroq

Sabab: eski tozalagich faqat oddiy harf/raqamni qoldirardi. "𝓢𝓱𝓸𝓭𝓲𝓴" kabi fancy yozuvlar butunlay
o'chib ketardi va familiya e'tiborga olinmasdi — natijada "NoName" chiqardi.

Endi (`utils/display_name.py`):
- NFKC normalizatsiya: fancy yozuv oddiy harflarga aylanadi (`𝓢𝓱𝓸𝓭𝓲𝓴 𝓚𝓪𝓻𝓲𝓶` → `Shodik Karim`).
- Ism yaroqsiz bo'lsa (faqat emoji, nuqta, ko'rinmas "ㅤ") → familiya olinadi.
- Familiya ham yo'q bo'lsa → username, undan keyin "NoName".
- Ism va familiya ikkalasi yaroqli bo'lsa — "Ism Familiya" ko'rsatiladi.

Qo'llanilgan joylar: test oxiridagi reyting rasmi/matni, kunlik guruh reytingi, `/start` dagi ism
(mavjud foydalanuvchining eski ismi ham keyingi `/start` da yangilanadi).

## 3. Xavfsizlik tuzatishi

Reyting matnidagi ismlar HTML-escape qilinmagan edi: `&` yoki `<` bo'lsa xabar yuborilmasdi.
Endi escape qilinadi.

## Testlar

`tests/test_group_lobby.py` — 20 ta test (ism qoidasi, lobby oqimi, 2 kishida avto-start,
bir kishi ikki marta bosishi, sanoq paytida bekor qilish, timeout, /quiz_stop, scheduler yo'li, natija ismlari, HTML escape).

Ishga tushirish: `python -m pytest -q tests/test_group_lobby.py`
