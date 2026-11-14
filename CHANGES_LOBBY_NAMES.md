# O'zgarishlar: Guruh lobbisi ("✋ Tayyorman") va ism qoidasi

## 1. Guruhda test darhol boshlanmaydi — lobby

Oldin: `/quiz_start KOD`, `startgroup=gpoll_KOD` yoki "Guruhda Poll Test" tugmasi bosilishi bilan
sanoq boshlanardi va birinchi savol darhol ketardi (tayyor bo'lmagan odamlar savolni o'tkazib yuborardi).

Endi:
1. Test chaqirilganda guruhda lobby xabari chiqadi: test nomi, savollar soni, vaqt, va tugmalar.
2. **✋ Tayyorman** — har bir a'zo bosadi; tayyorlar ro'yxati jonli yangilanadi (bir kishi bir marta).
3. **▶️ Boshlash** — faqat test boshlovchisi yoki guruh admini bosadi; shundan keyin sanoq va testlar boshlanadi.
4. **❌ Bekor qilish** — boshlovchi yoki admin. `/quiz_stop` ham lobbyni bekor qiladi.
5. Boshlanmasa, 10 daqiqadan keyin lobby avtomatik yopiladi.
6. Lobby ochiq bo'lganda guruhda boshqa test boshlab bo'lmaydi.

Eslatma: rejalashtirilgan (scheduler) testlar lobbysiz, vaqtida darhol boshlanadi (`lobby=False`).
Agar har bir "Tayyorman" bosilishi bilan avtomatik boshlansin desangiz, `lobby_ready` ichida
shu shartni qo'shish kerak.

Asosiy kod: `handlers/group.py` — `_open_lobby`, `lobby_ready`, `lobby_go`, `lobby_cancel`, `_lobby_timeout`.

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

`tests/test_group_lobby.py` — 17 ta test (ism qoidasi, lobby oqimi, ikki marta bosish,
admin/a'zo huquqi, bekor qilish, timeout, /quiz_stop, scheduler yo'li, natija ismlari, HTML escape).

Ishga tushirish: `python -m pytest -q tests/test_group_lobby.py`
