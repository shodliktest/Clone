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


# ───────────── hammasi bir xil "=" — birinchisi to'g'ri deb TAXMIN QILINMAYDI ─────────────
@pytest.mark.parametrize("kind", ["txt", "pdf"])
def test_all_same_marker_is_unmarked_by_default(tmp_path, kind):
    text = _c(lambda i, j, o: "= " + o)
    path = (_write if kind == "txt" else _pdf)(tmp_path, f"s.{kind}", text)
    qs = P.parse_file(path)
    assert len(qs) == len(Q)
    assert not any(q["_marked"] for q in qs)               # Seryalik/AI/admin hal qiladi
    assert all(not q["correct"] for q in qs)
    assert len(qs[0]["options"]) == 4                       # variantlar saqlangan
    assert not any("=" in o for q in qs for o in q["options"])   # "= Javob" qoldig'i yo'q


def test_all_same_first_correct_switch_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "EQ_ALLSAME_FIRST_CORRECT", True)
    qs = P.parse_file(_write(tmp_path, "s.txt", _c(lambda i, j, o: "= " + o)))
    assert _correct_letters(qs) == ["A"] * len(Q) and all(q.get("_guessed") for q in qs)


def test_xlsx_headerless_without_markers_stays_unmarked(tmp_path):
    rows = [[f"Test matni {i + 1}?"] + o for i, o in enumerate(OPTS)]
    qs = P.parse_file(_xlsx(tmp_path, "nh.xlsx", rows))
    assert len(qs) == 6
    assert not any(q["_marked"] for q in qs) and all(len(q["options"]) == 5 for q in qs)


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


# ───────────── soxta variantlar ("A" harfi, savolning o'zi), qavs, xlsx kalit ustuni ─────────────
def _mcq(question, options, correct):
    return {"type": "multiple_choice", "question": question, "options": options,
            "correct": correct, "_marked": bool(correct)}


def test_sanitize_drops_lone_letter_option_and_maps_key():
    # Jadvaldagi "to'g'ri javob = B" kalit harfi variant bo'lib qolgan, to'g'ri deb belgilangan
    q = _mcq("Oshqozon qon ketishi belgisi?",
             ["A) B", "B) Poliuriya va polidipsiya", "C) Melena va gematemez", "D) Bradikardiya"], "A) B")
    out = P._sanitize_question(q)
    assert out["options"] == ["A) Poliuriya va polidipsiya", "B) Melena va gematemez", "C) Bradikardiya"]
    assert out["correct"] == "B) Melena va gematemez" and out["_marked"] is True


def test_sanitize_drops_option_equal_to_question():
    q = _mcq("Ishlab chiqarish changi nima?",
             ["A) Ishlab chiqarish changi nima?", "B) Biologik mikroorganizmlar majmuasi",
              "C) Gazsimon moddalar aralashmasi", "D) Havoda muallaq zarralar"], "D) Havoda muallaq zarralar")
    out = P._sanitize_question(q)
    assert len(out["options"]) == 3 and out["correct"] == "C) Havoda muallaq zarralar"


def test_sanitize_unmarks_when_fake_option_was_correct_and_not_a_key():
    q = _mcq("Savol matni qanday?", ["A) Savol matni qanday?", "B) Birinchi javob", "C) Ikkinchi javob"],
             "A) Savol matni qanday?")
    out = P._sanitize_question(q)
    assert out["correct"] == "" and out["_marked"] is False and len(out["options"]) == 2


def test_sanitize_keeps_normal_questions_untouched():
    q = _mcq("Vitamin turi?", ["A) A", "B) B1 vitamini", "C) C vitamini", "D) D3 vitamini"], "B) B1 vitamini")
    assert P._sanitize_question(q) == q            # haqiqiy bir harfli variant ("A") — belgilanmagan, tegilmaydi
    q2 = _mcq("Qaysi harf?", ["A) A", "B) B", "C) C"], "A) A")
    assert P._sanitize_question(q2) == q2          # hammasi qisqa — tegilmaydi


def _xlsx(tmp_path, name, rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    p = tmp_path / name
    wb.save(str(p))
    return str(p)


OPTS = [[f"Variant {i}-a", f"Variant {i}-b (qavs)", f"Variant {i}-v", f"Variant {i}-g", f"Variant {i}-d"] for i in range(1, 7)]


@pytest.mark.parametrize("key,idx", [("B", 1), ("c)", 2), (4, 3)])
def test_xlsx_letter_or_number_answer_key_is_not_an_option(tmp_path, key, idx):
    rows = [["№", "Savol", "A", "B", "C", "D", "E", "To'g'ri javob"]]
    rows += [[i + 1, f"Test matni {i + 1}?"] + o + [key] for i, o in enumerate(OPTS)]
    qs = P.parse_file(_xlsx(tmp_path, "k.xlsx", rows))
    assert len(qs) == 6
    for i, q in enumerate(qs):
        assert len(q["options"]) == 5                       # soxta "F) B" varianti YO'Q
        assert q["_marked"] and q["correct"] == q["options"][idx]
        assert not any(o.strip()[3:].strip() in ("B", "c)", "4") for o in q["options"])


def test_xlsx_single_javob_column_with_text_answer(tmp_path):
    rows = [["Savol", "A", "B", "C", "D", "E", "Javob"]]
    rows += [[f"Test matni {i + 1}?"] + o + [o[2]] for i, o in enumerate(OPTS)]
    qs = P.parse_file(_xlsx(tmp_path, "t.xlsx", rows))
    assert len(qs) == 6 and all(len(q["options"]) == 5 for q in qs)
    assert all(q["_marked"] and q["correct"] == q["options"][2] for q in qs)


def test_xlsx_headerless_plus_marker_wins_over_default_layout(tmp_path):
    rows = [[f"Test matni {i + 1}?"] + [("+" if j == 1 else "") + x for j, x in enumerate(o)] for i, o in enumerate(OPTS)]
    qs = P.parse_file(_xlsx(tmp_path, "h.xlsx", rows))
    assert len(qs) == 6 and all(q["_marked"] for q in qs)
    assert all(q["correct"].endswith("(qavs)") for q in qs)


def test_label_like_text_is_not_mistaken_for_label(tmp_path):
    # "E. coli" birinchi variant — "A)" qo'shilishi kerak; "(Staphylococcus)" qavsi saqlanadi
    text = "\n".join([
        "? Qaysi bakteriya ichak tayoqchasi?",
        "= E. coli", "=+ Escherichia coli (E. coli)", "= (Staphylococcus) aureus", "= - 5 daraja",
        "? Normal tana harorati?",
        "= 35 (past)", "= 36,6 (normal)", "=+ 36,6 – 37", "= 40 (yuqori)",
    ])
    qs = P.parse_file(_write(tmp_path, "p.txt", text))
    assert qs[0]["options"][0] == "A) E. coli"
    assert qs[0]["options"][2] == "C) (Staphylococcus) aureus"
    # "- 5 daraja" kabi tire bilan boshlangan oddiy variant farqli belgi bo'lib adashtirmaydi
    assert qs[0]["correct"] == qs[0]["options"][1]
    assert qs[1]["correct"] == qs[1]["options"][2]


def test_xlsx_correct_first_muqobil_layout_real_file_shape(tmp_path):
    # "№ | Test topshirig'i | To'g'ri javob | Muqobil javob ×3" (typografik apostrof, NBSP raqamlar, bo'sh qatorlar)
    rows = [["№", "Test topshirig’i", "To’g’ri javob", "Muqobil javob", "Muqobil javob", "Muqobil javob"]]
    for i in range(1, 7):
        rows.append([f"{i}.\xa0\xa0\xa0 \xa0", f"Stenokardiya {i} haqida nima to‘g‘ri?",
                     f"to‘g‘ri-{i}", f" xato {i}-a", f"xato {i}-b", f"xato {i}-v"])
    rows.insert(3, [None] * 6)                                   # bo'sh qator
    # to'g'ri javob katagi savolning o'zi (fayldagi xato): soxta variant bo'lmasin, belgilanmagan qolsin
    rows.append(["7.", "Trombolitik xususiyatli preparat?", "Trombolitik xususiyatli preparat?",
                 "dipiridamol", "klopidogrel", "kurantil"])
    qs = P.parse_file(_xlsx(tmp_path, "real.xlsx", rows))
    assert len(qs) == 7
    for i, q in enumerate(qs[:6], 1):
        assert q["_marked"] and q["correct"] == f"A) to‘g‘ri-{i}" and len(q["options"]) == 4
        assert q["options"][1] == f"B) xato {i}-a"                # bosh bo'shliq tozalangan
    last = qs[6]
    assert not last["_marked"] and last["correct"] == ""
    assert len(last["options"]) == 3 and not any("Trombolitik" in o for o in last["options"])


def test_multi_question_mark_prefix_and_whitespace_marker(tmp_path):
    # "???savol" + "=variant" (hammasi "="), ba'zi savollarda to'g'ri javob "= " (bo'shliq bilan)
    lines = []
    for i in range(1, 7):
        lines.append(f"???Test savoli raqami {i} nima haqida" if i % 2 else f"??? Test savoli raqami {i}?")
        for j, o in enumerate(["birinchi", "ikkinchi", "uchinchi", "to'rtinchi"]):
            lines.append(("= " if (i <= 2 and j == 1) else "=") + f"{o} {i}")
    qs = P.parse_file(_pdf(tmp_path, "mq.pdf", "\n".join(lines)))
    assert len(qs) == 6
    assert all(not q["question"].startswith("?") for q in qs)
    assert all(len(q["options"]) == 4 for q in qs)
    assert [q["_marked"] for q in qs] == [True, True, False, False, False, False]   # taxmin yo'q
    assert qs[0]["correct"].endswith("ikkinchi 1")
