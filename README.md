# 🎓 Quiz Bot Pro — Firebase'siz versiya

## ✅ Firebase kerak emas!
Hamma narsa (testlar, userlar, natijalar) **Telegram kanalda** saqlanadi.

## 🚀 Ishga tushirish

### 1. Telegram Storage kanal yarating
1. Yangi **yopiq** kanal yarating
2. Botni kanalga **admin** qiling (Post + Pin huquqi)
3. Kanal ID ni oling (`-1001234567890` ko'rinishida)

### 2. `.streamlit/secrets.toml` ni to'ldiring
```toml
BOT_TOKEN          = "YOUR_BOT_TOKEN"
ADMIN_IDS          = "YOUR_TELEGRAM_ID"
ADMIN_PASSWORD     = "your_password"
STORAGE_CHANNEL_ID = "-1001234567890"
```

### 3. Streamlit Cloud ga deploy qiling
```
streamlit_app.py ni main file qilib belgilang
```

## 📦 Arxitektura
```
Telegram Kanal:
  📌 pinned → index.json   (barcha msg_id lar)
  📄 tests.json            (barcha testlar)
  📄 users.json            (barcha userlar)
  📄 backup_2024-05-20.json (kunlik natijalar)
```

## 📁 Fayl tuzilishi
```
├── bot.py
├── config.py
├── streamlit_app.py
├── requirements.txt
├── utils/
│   ├── tg_db.py      ← TG kanal = Database
│   ├── ram_cache.py  ← RAM + session_state
│   ├── db.py         ← CRUD (Firebase YO'Q)
│   ├── parser.py     ← TXT/PDF/DOCX parser
│   ├── scoring.py    ← Ball hisoblash
│   └── states.py     ← FSM states
├── handlers/
│   ├── start.py
│   ├── tests.py      ← Inline test (Keyingi tugmasi)
│   ├── poll_test.py  ← Poll (Pause/Resume)
│   ├── create_test.py
│   ├── profile.py    ← Tahlil ◀️▶️ navigatsiya
│   ├── leaderboard.py
│   └── admin.py      ← RAM Flush, backup
├── keyboards/
│   └── keyboards.py
└── samples/          ← Namuna fayllar
```
