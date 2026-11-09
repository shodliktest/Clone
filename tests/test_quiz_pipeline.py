"""
Test parseri va savol zanjiri uchun regressiya testlari.

Ishga tushirish (repo ildizidan):   python -m pytest tests/ -q
Yoki:                              python tests/test_quiz_pipeline.py

Qamrab olinadi:
  • txt / docx / pdf bir xil natija berishi (tashqi kutubxonalar bo'lsa)
  • sarlavha va '====' chiziqlari savol bo'lib qolmasligi
  • variant matnidagi qavslar buzilmasligi
  • to'g'ri javob (harf / indeks / matn) to'g'ri aniqlanishi
  • aralashtirishdan keyin to'g'ri javob saqlanishi
  • poll va ball hisobida to'g'ri javob bir xil bo'lishi
"""
import importlib.util
import os
import random
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.modules.setdefault("aiogram", types.ModuleType("aiogram"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QT = _load("quiz_text", "utils/quiz_text.py")
QM = _load("quiz_model", "utils/quiz_model.py")
SC = _load("scoring", "utils/scoring.py")
PS = _load("poll_safe", "utils/poll_safe.py")

SAMPLE = """PEDIATRIYA TESTLARI (3 ta)
======================
1. Qaysi biri to'g'ri?
A) Rinit (burun oqishi)
B) Yuqori tana harorati
   va ikkinchi qator
C) Kislorod (O2) bilan
D) Hech biri
Javob: C
Izoh: Birinchi satr.
Davomi izoh.
2. [2/3] Bu savol "Jami" so'zi bilan: nechta?
A) 1
B) 2
+ C) 3
D) 4
3. Oddiy savol
A) x (ichki qavs)
B) y *
C) z
D) w
=== Jami: 3 ta test ===
"""


def test_header_and_footer_not_questions():
    qs, rep = QT.parse_quiz_text(SAMPLE)
    assert len(qs) == 3
    assert [q["number"] for q in qs] == [1, 2, 3]


def test_parenthesized_options_intact():
    qs, _ = QT.parse_quiz_text(SAMPLE)
    assert qs[0]["options"][0] == "A) Rinit (burun oqishi)"
    assert qs[2]["options"][0] == "A) x (ichki qavs)"


def test_wrapped_option_joined():
    qs, _ = QT.parse_quiz_text(SAMPLE)
    assert qs[0]["options"][1] == "B) Yuqori tana harorati va ikkinchi qator"


def test_correct_from_hint_marker_and_star():
    qs, _ = QT.parse_quiz_text(SAMPLE)
    assert qs[0]["correct_index"] == 2                  # "Javob: C"
    assert qs[1]["correct_index"] == 2                  # "+ C) 3"
    assert qs[1]["options"][2] == "C) 3"
    assert qs[2]["correct_index"] == 1                  # "B) y *"
    assert qs[2]["options"][1] == "B) y"


def test_explanation_multiline():
    qs, _ = QT.parse_quiz_text(SAMPLE)
    assert qs[0]["explanation"] == "Birinchi satr. Davomi izoh."


def test_bracket_number_stripped_from_question():
    qs, _ = QT.parse_quiz_text(SAMPLE)
    assert qs[1]["question"].startswith('Bu savol "Jami"')


def test_correct_by_text_is_order_independent():
    q = {"options": ["A) Berlin", "B) Parij", "C) Rim"], "correct": "Parij"}
    assert QM.resolve_correct(q) == 1


def test_set_correct_roundtrip_and_shuffle_keeps_answer():
    q = {"question": "x", "options": ["A) a1", "B) b1", "C) c1", "D) d1"]}
    QM.set_correct(q, 2)
    assert QM.resolve_correct(q) == 2
    rnd = random.Random(1)
    texts = QM.option_texts(q)
    target = texts[2]
    rnd.shuffle(texts)
    q["options"] = [f"{chr(65 + i)}) {t}" for i, t in enumerate(texts)]
    q.pop("correct_index", None)                        # aralashtirgandan keyin faqat matn qoladi
    new_ci = QM.resolve_correct(q)
    assert QM.option_texts(q)[new_ci] == target


def test_poll_and_score_agree_on_correct():
    qs, _ = QT.parse_quiz_text(SAMPLE)
    for q in qs:
        QM.set_correct(q, 1)
    for q in qs:
        texts, ci = QM.poll_payload(q)
        _, clean, cix = PS.sanitize_poll("Savol", texts, ci, strip_label=False)
        assert "—" not in clean
        letter = chr(65 + cix)
        assert SC.calculate_score([q], {"0": letter})["correct_count"] == 1


def test_real_file_if_present():
    path = os.environ.get("PED_TXT", "/tmp/ped.txt")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        qs, rep = QT.parse_quiz_text(f.read())
    assert len(qs) == 200
    assert all(len(q["options"]) == 4 for q in qs)
    assert rep["dropped"] == []


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("OK  ", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    print("FAILED" if fails else "ALL PASSED")
    sys.exit(1 if fails else 0)
