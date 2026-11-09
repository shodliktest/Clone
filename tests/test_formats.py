"""
Haqiqiy test fayllari bo'yicha format regressiyasi.

FIXTURE_DIR muhit o'zgaruvchisi test fayllari joylashgan papka (topilmasa test o'tkazib yuboriladi).
Ishga tushirish:  FIXTURE_DIR=/yo/li python tests/test_formats.py
Kutilgan natijalar — har fayl uchun: (savollar soni, javobli savollar soni, tashlangan soni ko'pi bilan).
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.modules.setdefault("aiogram", types.ModuleType("aiogram"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FP = _load("utils.format_parsers", "utils/format_parsers.py")
QT = _load("utils.quiz_text", "utils/quiz_text.py")

# fayl → (savollar, javobli, tashlangan_ko'pi_bilan)
EXPECT = {
    "pediatriya_testlar.txt": (200, 0, 0),
    "4_pediatriya_test__2_.xlsx": (200, 0, 0),
    "Ichki_kasalliklar_va_kasb_kasaliklaridan_yakuniy_test_7_smestr.xlsx": (199, 199, 0),
    "Dinshunoslik_test_150_ABCD__1_.pdf": (150, 150, 0),
    "chigatoy_ulusi_testlar-v2.pdf": (20, 20, 0),
    "Ona_tili_gap_testi_javoblar_bilan.pdf": (30, 30, 0),
    "TEST_Ta_lim_menejmenti__S_BT-22-19-24_.pdf": (95, 0, 0),
    "Tadbirkorlik_asoslari_test_200__1_.docx": (200, 200, 0),
    "XVKM_26-27_eng.docx": (250, 250, 0),
    "Pedagogik_mahorat_fanidan_testlar_.docx": (195, 192, 6),
    "Nomli_stipendiya_AT_test_belgisiz.docx": (473, 0, 7),
    "biznes_yakuniy_test_javoblar.docx": (203, 189, 0),
    "Ingiliz_tili_baza.docx": (300, 0, 0),
}


def test_expected_counts():
    fdir = os.environ.get("FIXTURE_DIR", "")
    if not fdir or not os.path.isdir(fdir):
        return
    fails = []
    for name, (n_q, n_marked, n_drop_max) in EXPECT.items():
        path = os.path.join(fdir, name)
        if not os.path.exists(path):
            continue
        qs, rep = QT.parse_file_unified(path)
        marked = sum(1 for q in qs if q.get("_marked"))
        dropped = len(rep.get("dropped", []))
        if len(qs) != n_q or marked != n_marked or dropped > n_drop_max:
            fails.append(f"{name}: savol={len(qs)}/{n_q} javobli={marked}/{n_marked} tashl={dropped}/{n_drop_max}")
        for q in qs:
            assert 2 <= len(q["options"]) <= 10, (name, q["number"])
            assert q["question"].strip(), (name, q["number"])
            if q.get("_marked"):
                assert 0 <= q["correct_index"] < len(q["options"]), (name, q["number"])
    assert not fails, "\n".join(fails)


if __name__ == "__main__":
    try:
        test_expected_counts()
        print("ALL PASSED (yoki FIXTURE_DIR berilmagan)")
    except AssertionError as e:
        print("FAILED\n" + str(e))
        sys.exit(1)
