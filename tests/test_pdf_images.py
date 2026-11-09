"""
Rasmli testlar: PDF rasm hisoboti va DOCX rasm joylashuvi.

Ishga tushirish (repo ildizidan):  python tests/test_pdf_images.py
PDF biriktirish PyMuPDF (fitz) ga bog'liq — u bo'lmasa PDF bo'limida aniq ogohlantirish tekshiriladi.
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.modules.setdefault("aiogram", types.ModuleType("aiogram"))
spec = importlib.util.spec_from_file_location("parser_mod", os.path.join(ROOT, "utils/parser.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def test_one_image_per_question_and_reasons():
    qs = [{"question": "A", "options": ["x"]}, {"question": "B", "options": ["y"]}, {"question": "C", "options": ["z"]}]
    qpos = [(100, 0), (300, 1), (500, 2)]
    imgs = [(150, b"i1", ".png", 1), (160, b"i2", ".png", 1), (520, b"i3", ".jpg", 2), (999, b"i4", ".png", 2)]
    recs = P._assign_images(imgs, qpos, qs)
    assert recs[0]["action"] == "qo'shildi" and recs[0]["q"] == 1
    assert recs[1]["action"] == "qo'shilmadi" and "allaqachon" in recs[1]["reason"]
    assert recs[2]["q"] == 3 and recs[2]["action"] == "qo'shildi"
    assert recs[3]["action"] == "qo'shilmadi"
    assert sum(1 for q in qs if q.get("_img_bytes")) == 2


def test_no_question_positions_reports_reason():
    recs = P._assign_images([(10, b"x", ".png", 1)], [], [{"question": "Q"}])
    assert recs[0]["action"] == "qo'shilmadi" and "topilmadi" in recs[0]["reason"]


def test_pdf_summary_text():
    P._publish_pdf_report(4, [
        {"idx": 1, "page": 1, "q": 1, "action": "qo'shildi", "reason": ""},
        {"idx": 2, "page": 1, "q": 1, "action": "qo'shilmadi", "reason": "bu savolda rasm allaqachon bor"},
    ], True)
    txt = P.pdf_image_summary()
    assert "PDF da 4 ta rasm topildi" in txt
    assert "Savolga qo'shildi: <b>1</b>" in txt
    assert "#2 (sahifa 1) → qo'shilmadi (savol 1)" in txt


def test_summary_empty_for_non_pdf():
    P._publish_pdf_report(0, [], True)
    P.LAST_PDF_IMAGE_REPORT["source"] = "docx"
    assert P.pdf_image_summary() == ""


def test_pymupdf_missing_warning():
    P._publish_pdf_report(2, [], False, note="PyMuPDF o'rnatilmagan — rasmlar savollarga biriktirilmadi")
    assert "PyMuPDF" in P.pdf_image_summary()


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
