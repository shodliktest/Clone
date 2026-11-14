"""
Eski formatlar (? = / ==== # ++++ / + belgilar) yangi parser tizimida ham ishlashi
va to'g'ri javobni variant belgilarini solishtirib topishi (differential) regressiyasi.
Ishga tushirish:  python -I -m pytest -q tests/test_parser_legacy_formats.py
"""
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# boshqa test fayllari qoldirgan stub modullarni tozalaymiz
for _m in [m for m in list(sys.modules) if m == "utils" or m.startswith("utils.") or m == "aiogram" or m.startswith("aiogram.")]:
    if not getattr(sys.modules[_m], "__file__", None):
        del sys.modules[_m]

from utils import parser as P  # noqa: E402

Q = [(f"Savol {i}?", [f"Javob {i}-a", f"Javob {i}-b", f"Javob {i}-v", f"Javob {i}-g"]) for i in range(1, 7)]


def _c(fn, qs=Q):
    out = []
    for i, (q, opts) in enumerate(qs):
        out.append("? " + q)
        out += [fn(i, j, o) for j, o in enumerate(opts)]
    return "\n".join(out)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _pdf(tmp_path, name, text):
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    p = tmp_path / name
    c = canvas.Canvas(str(p), pagesize=A4)
    y = 800
    for line in text.split("\n"):
        if y < 50:
            c.showPage()
            y = 800
        c.drawString(40, y, line)
        y -= 16
    c.save()
    return str(p)


def _correct_letters(qs):
    return [(q.get("correct") or "")[:1] for q in qs]


# ───────────── differential: farqli belgi = to'g'ri ─────────────
@pytest.mark.parametrize("name,fn", [
    ("plus_marker", lambda i, j, o: ("=+ " if j == i % 4 else "= ") + o),
    ("star_marker", lambda i, j, o: ("* " if j == i % 4 else "= ") + o),
    ("nospace",     lambda i, j, o: ("=" if j == i % 4 else "= ") + o),
])
@pytest.mark.parametrize("kind", ["txt", "pdf"])
def test_differential_marker_found(tmp_path, name, fn, kind):
    text = _c(fn)
    path = (_write if kind == "txt" else _pdf)(tmp_path, f"{name}.{kind}", text)
    qs = P.parse_file(path)
    assert len(qs) == len(Q)
    assert all(q["_marked"] for q in qs)
    assert _correct_letters(qs) == ["ABCD"[i % 4] for i in range(len(Q))]


def test_quote_noise_is_not_a_marker(tmp_path):
    # "= «x»" dagi qo'shtirnoq belgi emas; faqat "=" (bo'sh joysiz) farqli
    text = _c(lambda i, j, o: ("=" if j == 0 else "= ") + (f"«{o}»" if j == 1 else o))
    qs = P.parse_file(_write(tmp_path, "q.txt", text))
    assert _correct_letters(qs) == ["A"] * len(Q)


# ───────────── hammasi bir xil "=" ─────────────
@pytest.mark.parametrize("kind", ["txt", "pdf"])
def test_all_same_marker_takes_first(tmp_path, kind):
    text = _c(lambda i, j, o: "= " + o)
    path = (_write if kind == "txt" else _pdf)(tmp_path, f"s.{kind}", text)
    qs = P.parse_file(path)
    assert len(qs) == len(Q)
    assert _correct_letters(qs) == ["A"] * len(Q)
    assert all(q.get("_guessed") for q in qs)


def test_all_same_switch_off(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "EQ_ALLSAME_FIRST_CORRECT", False)
    qs = P.parse_file(_write(tmp_path, "s.txt", _c(lambda i, j, o: "= " + o)))
    assert len(qs) == len(Q)
    assert not any(q["_marked"] for q in qs)


def test_mixed_file_keeps_unmarked_unmarked(tmp_path):
    # Faylda belgilangan savollar bor — belgisizi taxmin qilinmaydi
    lines = []
    for i, (q, opts) in enumerate(Q):
        lines.append("? " + q)
        for j, o in enumerate(opts):
            lines.append((("=+ " if j == 1 else "= ") if i < 5 else "= ") + o)
    qs = P.parse_file(_write(tmp_path, "m.txt", "\n".join(lines)))
    assert [q["_marked"] for q in qs] == [True] * 5 + [False]
    assert qs[-1]["correct"] == ""


def test_extract_prefix_marker_chars_only():
    assert P._extract_prefix("=+To'g'ri") == ("=+", "To'g'ri")
    assert P._extract_prefix("= «Xato»") == ("= ", "«Xato»")
    assert P._extract_prefix("Oddiy matn") == (None, None)


def test_find_correct_by_diff_guess_flag():
    raw = ["= a", "= b", "= c"]
    assert P._find_correct_by_diff(raw)[1] == -1
    assert P._find_correct_by_diff(raw, guess_first=True)[1] == 0
    assert P._find_correct_by_diff(["= a", "=+ b", "= c"], guess_first=True)[1] == 1


# ───────────── yo'qolgan format: unified natijasi legacy'ni bosib ketmasin ─────────────
def test_pick_best_prefers_more_marked():
    u = [{"question": "q", "options": ["A) 1", "B) 2"], "correct": "", "_marked": False}] * 3
    l = [{"question": "q", "options": ["A) 1", "B) 2"], "correct": "A) 1", "_marked": True}] * 3
    assert P._pick_best([("unified", u), ("legacy", l)])[0] == "legacy"
    assert P._pick_best([("unified", l), ("legacy", u)])[0] == "unified"


def test_standard_format_still_works(tmp_path):
    text = "\n".join(f"{i}. {q}\n*A) {o[0]}\nB) {o[1]}\nC) {o[2]}\nD) {o[3]}" for i, (q, o) in enumerate(Q, 1))
    for qs in (P.parse_file(_write(tmp_path, "a.txt", text)), P.parse_file(_pdf(tmp_path, "a.pdf", text))):
        assert len(qs) == len(Q) and all(q["_marked"] for q in qs)
        assert _correct_letters(qs) == ["A"] * len(Q)
