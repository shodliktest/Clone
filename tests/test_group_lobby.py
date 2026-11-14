"""Lobby ("✋ Tayyorman" → 2 kishi tayyor bo'lsa avto-start) va ism qoidasi testlari.

Haqiqiy handlers/group.py chaqiriladi; Telegram bot soxta (fake) obyekt bilan almashtirilgan.
Ishga tushirish:  python -I -m pytest -q <this file>
"""
import asyncio
import os
import sys
import types

REPO = os.environ.get("REPO_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Boshqa test fayllari (test_formats, test_quiz_pipeline, test_premium_access) aiogram/utils
# ni yengil "soxta" modul bilan sys.modules ga qo'yadi. Ularni olib tashlaymiz, shunda
# haqiqiy kutubxona va loyiha moduli import qilinadi (tartibdan qat'i nazar).
for _name in list(sys.modules):
    if _name.split(".")[0] in ("aiogram", "utils", "keyboards", "config", "handlers") and \
            getattr(sys.modules[_name], "__file__", None) is None:
        del sys.modules[_name]

import handlers.group as g                                   # noqa: E402
from utils.display_name import display_name, user_display_name, clean_text  # noqa: E402

TID   = "ABC12345"
CHAT  = -1001234567890
HOST  = 1
ALI   = 2
VALI  = 3
ADMIN = 4


# ─── Soxta Telegram obyektlari ───────────────────────────────────────────
class Msg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    def __init__(self):
        self.sent, self.edits, self.deleted, self.polls = [], [], [], []
        self._mid = 100
        self.admins = {ADMIN}

    async def send_message(self, chat_id, text, **kw):
        self._mid += 1
        self.sent.append((chat_id, text, kw))
        return Msg(self._mid)

    async def send_photo(self, chat_id, photo, **kw):
        self._mid += 1
        return Msg(self._mid)

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append((chat_id, message_id, text))
        return True

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)
        return True

    async def get_chat_member(self, chat_id, uid):
        return types.SimpleNamespace(status="administrator" if uid in self.admins else "member")

    async def send_poll(self, **kw):
        self._mid += 1
        self.polls.append(kw)
        return types.SimpleNamespace(message_id=self._mid, poll=types.SimpleNamespace(id=f"poll{self._mid}"))

    async def me(self):
        return types.SimpleNamespace(username="QuizTestBot")


class FakeCB:
    def __init__(self, bot, data, uid, first="", last="", username=None):
        self.bot = bot
        self.data = data
        self.from_user = types.SimpleNamespace(id=uid, first_name=first, last_name=last,
                                               username=username, full_name=f"{first} {last}".strip())
        self.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=CHAT, type="supergroup"),
                                             message_id=1)
        self.answers = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append((text, show_alert))
        return True


class FakeMessage:
    def __init__(self, bot, uid, text="/quiz_stop"):
        self.bot = bot
        self.chat = types.SimpleNamespace(id=CHAT, type="supergroup")
        self.from_user = types.SimpleNamespace(id=uid)
        self.text = text
        self.replies = []

    async def answer(self, text, **kw):
        self.replies.append(text)
        return Msg(0)


# ─── Test muhiti ─────────────────────────────────────────────────────────
TEST_DATA = {
    "title": "Matematika <1-bob> & algebra",
    "poll_time": 30,
    "passing_score": 60,
    "shuffle_questions": False,
    "questions": [
        {"type": "multiple_choice", "question": "2+2?", "options": ["A) 3", "B) 4"], "correct": "B"},
        {"type": "true_false", "question": "Yer yumaloq", "correct": "ha"},
    ],
}


def _setup(monkeypatch):
    bot = FakeBot()
    g._lobby_sessions.clear()
    g._group_sessions.clear()
    g._inline_sessions.clear()
    g._starting.clear()
    g._busy_warn_ts.clear()
    monkeypatch.setattr(g, "is_test_paused", lambda tid: False)
    monkeypatch.setattr(g, "is_protect_content", lambda: False)
    monkeypatch.setattr(g, "COUNT_EMOJIS", [])          # sanoqni qisqartirish

    async def _load(bot_, chat_id, tid):
        return {**TEST_DATA, "questions": [dict(q) for q in TEST_DATA["questions"]]}

    async def _access(tid, uid, test):
        return True

    async def _no_polls(*a, **k):                        # poll sikli o'rniga — bo'sh
        return None

    monkeypatch.setattr(g, "_load_test", _load)
    monkeypatch.setattr(g, "_group_test_access", _access)
    monkeypatch.setattr(g, "_run_group_polls", _no_polls)
    return bot


async def _drain():
    """Fon tasklarini (lobby refresh, timeout) tugatishga imkon beradi."""
    for _ in range(3):
        await asyncio.sleep(0)


# ─── 1. Ism qoidasi (birlik testlari) ────────────────────────────────────
def test_fancy_name_is_readable_not_noname():
    assert display_name("𝓢𝓱𝓸𝓭𝓲𝓴", "𝓚𝓪𝓻𝓲𝓶") == "Shodik Karim"
    assert display_name("𝐀𝐥𝐢") == "Ali"


def test_missing_first_name_falls_back_to_last_name():
    assert display_name("🙂", "Karimov") == "Karimov"
    assert display_name("ㅤ", "Karimov") == "Karimov"       # ko'rinmas to'ldiruvchi
    assert display_name(".", "Karimov") == "Karimov"
    assert display_name("", "Karimov") == "Karimov"


def test_first_and_last_both_kept_when_valid():
    assert display_name("Ali", "Karimov") == "Ali Karimov"
    assert display_name("Ali", "🙂") == "Ali"


def test_username_is_last_resort_before_noname():
    assert display_name("🙂", "🙂", "ali_uz") == "ali_uz"
    assert display_name("🙂", "🙂") == "NoName"
    assert display_name("", "", "") == "NoName"


def test_uzbek_apostrophe_and_truncation_and_user_obj():
    assert display_name("Oʻtkir", "") == "Oʻtkir"
    assert len(display_name("A" * 60, max_len=25)) == 26      # 25 + "…"
    u = types.SimpleNamespace(first_name="🙂", last_name="Ali", username=None)
    assert user_display_name(u) == "Ali"
    assert user_display_name(None) == "NoName"
    assert clean_text("A & B") == "A & B"


def test_group_clean_name_uses_same_rule():
    assert g._clean_name("𝓢𝓱𝓸𝓭𝓲𝓴 𝓚𝓪𝓻𝓲𝓶", 20) == "Shodik Karim"
    assert g._clean_name("🔥🔥", 20) == "NoName"


# ─── 2. Lobby oqimi ──────────────────────────────────────────────────────
def test_start_opens_lobby_and_does_not_start_test(monkeypatch):
    bot = _setup(monkeypatch)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        assert CHAT in g._lobby_sessions
        assert CHAT not in g._group_sessions          # test HALI boshlanmadi
        assert bot.polls == []
        _, text, kw = bot.sent[-1]
        assert "Tayyor" in text
        assert "Matematika &lt;1-bob&gt; &amp; algebra" in text   # sarlavha HTML-escape qilingan
        cbs = [b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row]
        assert f"gl_ready_{CHAT}" in cbs and f"gl_cancel_{CHAT}" in cbs
        assert not any(c.startswith("gl_go_") for c in cbs)      # "Boshlash" tugmasi yo'q
        await _drain()
        g._lobby_sessions.clear()
    asyncio.run(run())


def test_ready_presses_update_list_and_are_deduplicated(monkeypatch):
    bot = _setup(monkeypatch)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", ALI, "🙂", "Karimov"))
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", VALI, "Vali"))
        again = FakeCB(bot, f"gl_ready_{CHAT}", ALI, "🙂", "Karimov")
        await g.lobby_ready(again)
        lobby = g._lobby_sessions[CHAT]
        assert list(lobby["ready"].values()) == ["Karimov", "Vali"]      # familiyadan olindi
        assert "allaqachon tayyor" in again.answers[0][0]
        # Throttle: ketma-ket o'zgarish kechiktirib bo'lsa ham oxirgisi yetib boradi
        await asyncio.sleep(g.LOBBY_EDIT_MIN_SEC + 0.3)
        assert any("Tayyor: 2 kishi" in t for _, _, t in bot.edits)
        assert any("Karimov" in t for _, _, t in bot.edits)
        g._lobby_sessions.clear()
    asyncio.run(run())


def test_autostart_when_two_ready(monkeypatch):
    bot = _setup(monkeypatch)
    monkeypatch.setattr(g, "LOBBY_START_DELAY_SEC", 0.2)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        # 1 kishi — boshlanmaydi
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", ALI, "Ali"))
        await asyncio.sleep(0.4)
        assert CHAT in g._lobby_sessions and CHAT not in g._group_sessions
        assert not g._lobby_sessions[CHAT].get("start_task")
        # 2-kishi bosadi — kechikishdan keyin test o'zi boshlanadi
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", VALI, "Vali"))
        assert g._lobby_sessions[CHAT]["start_task"]
        assert CHAT not in g._group_sessions                      # darhol emas
        # 3-kishi kechikkan — ikkinchi start ochilmaydi
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", ADMIN, "Admin"))
        for _ in range(40):                                       # sanoq tugashini kutamiz
            await asyncio.sleep(0.2)
            if any("QUIZ POLL BOSHLANDI" in t for _, t, _ in bot.sent):
                break
        assert CHAT not in g._lobby_sessions
        assert CHAT in g._group_sessions
        assert g._group_sessions[CHAT]["host_id"] == HOST
        assert sum(1 for _, t, _ in bot.sent if "QUIZ POLL BOSHLANDI" in t) == 1
        assert bot.deleted                                        # lobby xabari o'chirildi
        g._group_sessions.clear()
        await _drain()
    asyncio.run(run())


def test_same_user_twice_does_not_trigger_autostart(monkeypatch):
    bot = _setup(monkeypatch)
    monkeypatch.setattr(g, "LOBBY_START_DELAY_SEC", 0.1)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", ALI, "Ali"))
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", ALI, "Ali"))
        await asyncio.sleep(0.3)
        assert CHAT in g._lobby_sessions and CHAT not in g._group_sessions
        g._cancel_lobby_task(g._lobby_sessions[CHAT])
        g._lobby_sessions.clear()
    asyncio.run(run())


def test_cancel_during_countdown_prevents_start(monkeypatch):
    bot = _setup(monkeypatch)
    monkeypatch.setattr(g, "LOBBY_START_DELAY_SEC", 0.2)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", ALI, "Ali"))
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", VALI, "Vali"))
        await g.lobby_cancel(FakeCB(bot, f"gl_cancel_{CHAT}", HOST, "Host"))
        await asyncio.sleep(0.5)
        assert CHAT not in g._lobby_sessions and CHAT not in g._group_sessions
        assert not any("QUIZ POLL BOSHLANDI" in t for _, t, _ in bot.sent)
    asyncio.run(run())


def test_lobby_text_shows_need_and_countdown(monkeypatch):
    bot = _setup(monkeypatch)
    monkeypatch.setattr(g, "LOBBY_START_DELAY_SEC", 5)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        lobby = g._lobby_sessions[CHAT]
        assert "yana 2 kishi kerak" in g._lobby_text(lobby)
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", ALI, "Ali"))
        assert "yana 1 kishi kerak" in g._lobby_text(lobby)
        await g.lobby_ready(FakeCB(bot, f"gl_ready_{CHAT}", VALI, "Vali"))
        assert "5 soniyadan keyin boshlanadi" in g._lobby_text(lobby)
        g._cancel_lobby_task(lobby)
        g._lobby_sessions.clear()
        await _drain()
    asyncio.run(run())


def test_busy_while_lobby_open_and_cancel(monkeypatch):
    bot = _setup(monkeypatch)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        assert g._is_busy(CHAT)
        n_before = len(bot.sent)
        await g._start_group_test(bot, CHAT, ALI, TID, "poll")     # ikkinchi test — rad etiladi
        assert len(bot.sent) == n_before + 1
        assert "tayyorlanmoqda" in bot.sent[-1][1]
        assert CHAT not in g._group_sessions

        cancel = FakeCB(bot, f"gl_cancel_{CHAT}", ALI, "Ali")
        await g.lobby_cancel(cancel)                                # oddiy a'zo — rad
        assert CHAT in g._lobby_sessions
        await g.lobby_cancel(FakeCB(bot, f"gl_cancel_{CHAT}", HOST, "Host"))
        assert CHAT not in g._lobby_sessions
        assert any("bekor qilindi" in t for _, _, t in bot.edits)
        assert not g._is_busy(CHAT)
        await _drain()
    asyncio.run(run())


def test_lobby_times_out(monkeypatch):
    bot = _setup(monkeypatch)
    monkeypatch.setattr(g, "LOBBY_TIMEOUT_SEC", 0.2)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        await asyncio.sleep(0.5)
        assert CHAT not in g._lobby_sessions
        assert not g._is_busy(CHAT)
        assert any("vaqti tugadi" in t for _, _, t in bot.edits)
        assert bot.polls == []
    asyncio.run(run())


def test_quiz_stop_cancels_lobby(monkeypatch):
    bot = _setup(monkeypatch)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll")
        msg = FakeMessage(bot, ALI)
        await g.cmd_quiz_stop(msg)                                  # boshqa a'zo — rad
        assert CHAT in g._lobby_sessions and "Faqat" in msg.replies[-1]
        await g.cmd_quiz_stop(FakeMessage(bot, HOST))
        assert CHAT not in g._lobby_sessions
        await _drain()
    asyncio.run(run())


def test_scheduler_path_starts_directly_without_lobby(monkeypatch):
    bot = _setup(monkeypatch)

    async def run():
        await g._start_group_test(bot, CHAT, HOST, TID, "poll", lobby=False)
        assert CHAT not in g._lobby_sessions
        assert CHAT in g._group_sessions
        g._group_sessions.clear()
        await _drain()
    asyncio.run(run())


def test_group_start_button_path_opens_lobby(monkeypatch):
    bot = _setup(monkeypatch)

    async def run():
        cb = FakeCB(bot, f"group_start_{TID}", HOST, "Host")
        await g._guarded_callback_start(cb, g._group_start_poll_impl)
        assert CHAT in g._lobby_sessions and CHAT not in g._group_sessions
        g._lobby_sessions.clear()
        await _drain()
    asyncio.run(run())


# ─── 3. Natija va reyting ismlari ────────────────────────────────────────
def test_poll_answer_stores_clean_name(monkeypatch):
    _setup(monkeypatch)
    g._group_sessions[CHAT] = {
        "tid": TID, "test": TEST_DATA, "questions": TEST_DATA["questions"],
        "answers": {}, "names": {}, "poll_map": {"poll7": 0}, "host_id": HOST,
        "poll_time": 30, "task": None,
    }
    pa = types.SimpleNamespace(poll_id="poll7", option_ids=[1], user=types.SimpleNamespace(
        id=ALI, first_name="𝓢𝓱𝓸𝓭𝓲𝓴", last_name="𝓚𝓪𝓻𝓲𝓶", username=None, full_name="𝓢𝓱𝓸𝓭𝓲𝓴 𝓚𝓪𝓻𝓲𝓶"))
    asyncio.run(g.route_poll_answer(pa))
    assert g._group_sessions[CHAT]["names"][str(ALI)] == "Shodik Karim"
    assert g._group_sessions[CHAT]["answers"][str(ALI)]["0"] == "B"
    g._group_sessions.clear()


def test_text_leaderboard_escapes_names_and_uses_clean_names():
    results = [
        {"first_name": "A&B <x>", "username": "A&B <x>", "score": 100, "correct": 2, "total": 2},
        {"first_name": "𝓢𝓱𝓸𝓭𝓲𝓴", "username": "𝓢𝓱𝓸𝓭𝓲𝓴", "score": 50, "correct": 1, "total": 2},
        {"first_name": "🔥🔥", "username": "🔥🔥", "score": 0, "correct": 0, "total": 2},
    ]
    text = g._build_text_leaderboard(TID, results, TEST_DATA, TEST_DATA["questions"], "QuizTestBot",
                                     False, 60, "poll")
    assert "A&amp;B x" in text                 # "&" escape, "<x>" belgilari tozalangan
    assert "<x>" not in text
    assert "Shodik" in text
    assert "NoName" in text
