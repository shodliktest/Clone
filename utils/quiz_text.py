"""
Yagona test parseri — barcha formatlar uchun bitta mantiq.

  extract_text(path)  → txt / docx / pdf / xlsx dan oddiy matn (tartib saqlanadi)
  parse_quiz_text(t)  → (savollar, hisobot)

Savol modeli (utils.quiz_model bilan mos):
    {"type": "multiple_choice", "question": str, "options": ["A) ...", ...],
     "correct": "X) matn" | None, "correct_index": int | None,
     "explanation": str, "accepted_answers": [], "points": 1, "_marked": bool,
     "number": int}

Qo'llab-quvvatlanadigan belgilar:
  • Savol:     "12. matn", "12) matn", "[12/50] matn"
  • Variant:   "A) matn", "A. matn", "A: matn", "a) matn"  (faqat boshida, bir marta)
  • Javob:     "Javob: B", "To'g'ri javob: Parij", "Correct: C", "Answer: ..."
  • To'g'ri variant belgisi: "+ matn", "matn *", "matn ✅"
  • Izoh:      "Izoh: ...", "Tushuntirish: ...", "Explanation: ..." (keyingi qatorlar ham)
  • Sarlavha/chiziqlar: birinchi savoldan oldingi matn, "====", "=== Jami ... ===" tashlanadi.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# ── Regexlar ───────────────────────────────────────────────
# Savol boshlanishi: 1. Matn, 1) Matn, [1/10] Matn, 1.Matn (bo'shliqsiz ham), 1-savol:, # 1., # 83-84., № 1.
_Q_START = re.compile(
    r"^\s*(?:(?:#|№|savol\s*|topshiriq\s*)?\s*\[\s*(\d{1,4})\s*/\s*\d{1,4}\s*\]\s*|(?:#|№|savol\s*|topshiriq\s*)?\s*(\d{1,4})(?:\s*-\s*\d{1,4})?\s*(?:[\.\)]|-savol[\.:]?|-topshiriq[\.:]?|:)\s*)(\S.*)$",
    re.IGNORECASE
)

# Kril va Lotin harflari: A-J, А-Я
_OPT_LABEL_CHARS = r"[A-Ja-jА-Яа-яёЁ]"

# Prefix to'g'ri javob belgilari: ===, ==, --, *, +, #, ✅, ✔, ✓, ~, •, ►, →, ■, ●, ▶, ◆, ★, ☑
_MARK_PREFIX_PATTERN = re.compile(
    r"^\s*(?:={1,}|[-]{2,}|[*+#•►→✓✔√■●▶◆★☑~]|✅|✔️)\s*"
)

# Variant boshlanishi: A) , A. , A: , A - (Lotin va Krill)
_OPT_START = re.compile(rf"^\s*({_OPT_LABEL_CHARS})\s*[\)\.:\-]\s*(.*)$")

# Harfsiz variantlar: + To'g'ri javob, - Noto'g'ri javob
_PLUS_MINUS_OPT = re.compile(r"^\s*([+\-])\s+(\S.*)$")

# Variant oxiridagi yoki ichidagi to'g'ri javob belgilari
_MARK_SUFFIX = re.compile(r"\s*([*+#•►→✓✔√■●▶◆★☑~]|✅|✔|✓|✔️)\s*$")

_ANSWER = re.compile(
    r"^\s*(?:to['’ʻ`‘]?g['’ʻ`‘]?ri\s+javob|javob|correct(?:\s+answer)?|answer|kalit)\s*[:：\-–]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_EXPL = re.compile(
    r"^\s*(?:izoh|tushuntirish|tushuntirma|explanation|sharh)\s*[:：\-–]?\s*(.*)$",
    re.IGNORECASE,
)
_DECOR_LINE = re.compile(r"^\s*[=\-_*#~•·.]{4,}\s*$")
_FOOTER = re.compile(r"^\s*[=\-_*#~]{2,}.*\b(jami|total)\b.*$", re.IGNORECASE)
_MARK_PREFIX = re.compile(r"^\s*\+\s+")
_WS = re.compile(r"[ \t\u00a0\u200b\u200c\u200d\ufeff]+")


# ── 1) MATN OLISH ──────────────────────────────────────────
def _read_txt(path: str) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


def _docx_text(path: str) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    out: list[str] = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            tbl = Table(child, doc)
            for row in tbl.rows:
                cells = []
                for c in row.cells:
                    t = c.text.strip()
                    if t and (not cells or cells[-1] != t):
                        cells.append(t)
                # Jadval qatorini alohida qatorlarga: birinchi katak — savol, qolganlari — variantlar
                out.extend(cells)
    return "\n".join(out)


def _pdf_text(path: str) -> str:
    try:
        import pdfplumber
        pages: list[list[str]] = []
        with pdfplumber.open(path) as pdf:
            for p in pdf.pages:
                t = p.extract_text() or ""
                pages.append([ln for ln in t.split("\n")])
        return _strip_repeated_page_lines(pages)
    except Exception as e:  # pdfplumber yo'q yoki buzuq PDF
        log.warning("pdfplumber ishlamadi (%s), pdftotext urinilmoqda", e)
    import subprocess
    try:
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:
        log.error("pdf matn olinmadi: %s", e)
        return ""


def _strip_repeated_page_lines(pages: list[list[str]]) -> str:
    """Har sahifada takrorlanadigan sarlavha/raqam qatorlarini (kolontitul) olib tashlaydi."""
    from collections import Counter
    counts: Counter = Counter()
    for lines in pages:
        for ln in set(l.strip() for l in lines if l.strip()):
            if len(ln) <= 80:
                counts[ln] += 1
    threshold = max(3, len(pages) // 2) if len(pages) >= 4 else 10**9
    repeated = {ln for ln, c in counts.items() if c >= threshold}
    out = []
    for lines in pages:
        out.extend(l for l in lines if l.strip() not in repeated)
    return "\n".join(out)


def _xlsx_text(path: str) -> str:
    """Har qator: [savol, variant1, variant2, ...] — har biri alohida qator bo'lib yoziladi."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if not cells:
                continue
            out.append(cells[0])
            for k, c in enumerate(cells[1:]):
                out.append(c if re.match(r"^[A-Ja-j][\)\.:]\s", c) else f"{chr(65 + k)}) {c}")
    return "\n".join(out)


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".txt":
        return _read_txt(path)
    if ext == ".docx":
        return _docx_text(path)
    if ext == ".pdf":
        return _pdf_text(path)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx_text(path)
    if ext == ".doc":
        from utils.parser import _convert_doc
        conv = _convert_doc(path)
        return extract_text(conv) if conv else ""
    return ""


# ── 2) PARSE ───────────────────────────────────────────────
_GLUED_NUM = re.compile(r"([^\s\d\W]|[?!.)])(\d{1,3})\.\s+(?=[A-ZА-ЯOʻ«'’])")
_PAGE_TAIL = re.compile(r"([?!.])\d{1,3}$")
_UNSURE = re.compile(r"\s*\(\?\)\s*")
_CHECK_PREFIX = re.compile(r"^\s*[✓✔✅]\s*(?=[A-Ja-j]\s*[\)\.:])")


def _clean_line(s: str) -> str:
    s = s.replace("\r", "")
    s = _WS.sub(" ", s)
    s = s.strip()
    s = _UNSURE.sub(" ", s).strip()
    s = _PAGE_TAIL.sub(r"\1", s)                 # "...borasiz?2" → "...borasiz?"
    return s


def _split_glued(line: str) -> list[str]:
    """'Qarshi6. Chig'atoy...' → ['Qarshi', '6. Chig'atoy...'] (PDF da yopishib qolgan savol raqami)."""
    m = _GLUED_NUM.search(line)
    if not m:
        return [line]
    cut = m.start(2)
    return [line[:cut].strip(), line[cut:].strip()]


def _strip_marker(text: str) -> tuple[str, bool]:
    """Variant matnidan to'g'ri javob belgilarini tozalash."""
    if _MARK_PREFIX_PATTERN.match(text):
        m = _MARK_PREFIX_PATTERN.match(text)
        return text[m.end():].strip(), True
    m = _MARK_SUFFIX.search(text)
    if m and len(text[:m.start()].strip()) > 0:
        return text[:m.start()].strip(), True
    return text, False


_BRACKET_NO = re.compile(r"^\s*\[\s*\d{1,4}\s*/\s*\d{1,4}\s*\]\s*")
CYRILLIC_MAP = {"А": 0, "Б": 1, "В": 2, "Г": 3, "Д": 4, "Е": 5, "Ж": 6, "З": 7, "И": 8, "К": 9}


def _finish(cur: dict, report: dict) -> dict | None:
    """Joriy blokni yakunlab, yaroqli bo'lsa natijaga qo'shadi."""
    q_text = _BRACKET_NO.sub("", _WS.sub(" ", cur["q"]).strip()).strip()
    opts = [o.strip() for o in cur["opts"]]
    if not q_text:
        report["dropped"].append((cur["no"], "savol matni yo'q"))
        return None

    # Ha / Yo'q (true_false) savollari uchun avtomatik variantlar
    is_tf = cur.get("type") == "true_false" or (
        not opts and cur.get("hint") and str(cur.get("hint")).lower().strip() in ("ha", "yoq", "yo'q", "true", "false", "yes", "no")
    )
    if is_tf and len(opts) < 2:
        opts = ["Ha", "Yo'q"]
        if cur.get("hint"):
            hl = str(cur["hint"]).lower().strip()
            cur["marks"] = [hl in ("ha", "true", "yes"), hl in ("yoq", "yo'q", "false", "no")]
        elif not cur["marks"]:
            cur["marks"] = [True, False]

    if len([o for o in opts if o]) < 2:
        report["dropped"].append((cur["no"], f"variant {len(opts)} ta (kamida 2 kerak)"))
        return None
    if any(not o for o in opts):
        report["dropped"].append((cur["no"], "bo'sh variant bor"))
        return None
    if any(re.fullmatch(r"[=+\-_*.\s]{2,}", o) for o in opts):
        report["dropped"].append((cur["no"], "buzilgan variant (manbada matn yo'q): " + q_text[:50]))
        return None

    ci = None
    marked = [i for i, mk in enumerate(cur["marks"]) if mk]
    if len(marked) >= 1:
        ci = marked[0]
    if ci is None and cur.get("hint"):
        h = cur["hint"].strip()
        mm = re.match(r"^([A-Ja-jА-Яа-яёЁ])\s*[\)\.:]?(?:\s|$)", h)
        if mm:
            char = mm.group(1).upper()
            if char in CYRILLIC_MAP:
                idx = CYRILLIC_MAP[char]
            else:
                idx = ord(char) - 65
            if 0 <= idx < len(opts):
                ci = idx
        else:
            hn = _norm(h)
            hits = [i for i, o in enumerate(opts) if _norm(o) == hn]
            if len(hits) == 1:
                ci = hits[0]
    if ci is None:
        report["no_answer"] += 1

    labeled = [f"{chr(65 + i)}) {o}" for i, o in enumerate(opts)]
    return {
        "type": "true_false" if is_tf else "multiple_choice",
        "question": q_text,
        "options": labeled,
        "correct": (f"{chr(65 + ci)}) {opts[ci]}" if ci is not None else None),
        "correct_index": ci,
        "explanation": _WS.sub(" ", cur.get("expl", "")).strip(),
        "accepted_answers": [],
        "points": 1,
        "_marked": ci is not None,
        "number": cur["no"],
    }


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("ʻ", "'").replace("`", "'").replace("‘", "'")
    return _WS.sub(" ", s).strip()


def parse_quiz_text(text: str) -> tuple[list[dict], dict]:
    """Matnni savollarga ajratadi. → (savollar, hisobot)."""
    report = {"blocks": 0, "dropped": [], "no_answer": 0, "numbered": False,
              "option_hist": {}, "duplicates": []}
    lines = []
    for raw in text.split("\n"):
        for part in _split_glued(_clean_line(raw)):
            if part:
                lines.append(part)
    lines = [l for l in lines if l and not re.fullmatch(r"\d{1,4}", l)]   # sahifa raqamlari

    # Sarlavha/chiziqlarni tashlaymiz (footer ham)
    lines = [l for l in lines if not _DECOR_LINE.match(l) and not _FOOTER.match(l)]

    # Savol raqamlari bormi? (bo'lmasa — '?' bilan tugagan qatorlar savol deb olinadi)
    numbered_hits = sum(1 for l in lines if _Q_START.match(l))
    report["numbered"] = numbered_hits >= 2

    blocks: list[dict] = []
    cur: dict | None = None
    expected_no = 1
    mode = "q"            # q | opt | expl | hint
    seen_numbers: set[int] = set()

    forced_type = None

    def start_question(no: int, text_: str) -> None:
        nonlocal cur, mode, forced_type
        if cur is not None:
            blocks.append(cur)
        cur = {"no": no, "q": text_, "opts": [], "marks": [], "hint": None, "expl": "", "type": forced_type}
        forced_type = None
        mode = "q"

    for l in lines:
        # 0) TYPE formati (TYPE: true_false, TYPE: fill_blank, etc.)
        if l.upper().startswith("TYPE:"):
            forced_type = l.split(":", 1)[1].strip().lower()
            if cur is not None and not cur["opts"]:
                cur["type"] = forced_type
            continue

        # 1) Javob kaliti / izoh satrlari (savol va variant ichida ham uchrashi mumkin)
        ma = _ANSWER.match(l)
        if ma and cur is not None:
            cur["hint"] = ma.group(1)
            mode = "hint"
            continue
        me = _EXPL.match(l)
        if me and cur is not None and (cur["opts"] or mode == "q"):
            cur["expl"] = (me.group(1) or "").strip()
            mode = "expl"
            continue

        # 2) Yangi savol
        mq = _Q_START.match(l)
        if mq and (not report["numbered"] or cur is None or _is_new_question(mq, expected_no, cur)):
            no = int(mq.group(1) or mq.group(2))
            if report["numbered"]:
                if no in seen_numbers:
                    report["duplicates"].append(no)
                seen_numbers.add(no)
                expected_no = no + 1
            else:
                expected_no = (cur["no"] + 1) if cur else 1
                no = expected_no
            start_question(no, mq.group(3))
            continue

        # 3) Yangi savol (raqamsiz fayl): variant ketidan "?"/":" bilan tugagan qator
        if not report["numbered"] and (cur is None or cur["opts"]) and _looks_like_question(l) \
                and not _OPT_START.match(l):
            expected_no += 1
            start_question(expected_no, l)
            continue

        # 4) Variant (to'g'ri belgisi: "===A) ...", "*A) ...", "+A) ...", "A)* ...", "A) ... *")
        is_marked = False
        raw_line = l.strip()

        # A) Boshidagi to'g'ri javob belgisi (===, ==, *, +, #, ✅, ✔, ✓ va h.k.)
        mp = _MARK_PREFIX_PATTERN.match(raw_line)
        if mp:
            is_marked = True
            raw_line = raw_line[mp.end():].strip()

        mo = _OPT_START.match(raw_line)
        if mo and cur is not None:
            body = mo.group(2).strip()

            # B) Qavsdan keyingi belgi: A)* yoki A)+ yoki A) *
            body_mp = _MARK_PREFIX_PATTERN.match(body)
            if body_mp:
                is_marked = True
                body = body[body_mp.end():].strip()

            # C) Variant oxiridagi belgi: A) Toshkent *
            body_ms = _MARK_SUFFIX.search(body)
            if body_ms:
                is_marked = True
                body = body[:body_ms.start()].strip()

            cur["opts"].append(body)
            cur["marks"].append(is_marked)
            mode = "opt"
            continue

        # B) Harfsiz variantlar: "+ To'g'ri javob", "- Noto'g'ri javob"
        mpm = _PLUS_MINUS_OPT.match(l)
        if mpm and cur is not None and (mode in ("q", "opt")):
            is_marked = (mpm.group(1) == "+")
            body = mpm.group(2).strip()
            body_ms = _MARK_SUFFIX.search(body)
            if body_ms:
                is_marked = True
                body = body[:body_ms.start()].strip()
            cur["opts"].append(body)
            cur["marks"].append(is_marked)
            mode = "opt"
            continue

        # 5) Davomi (o'ralgan qator)
        if cur is None:
            continue                       # birinchi savoldan oldingi sarlavha
        if mode == "expl":
            cur["expl"] = _join(cur["expl"], l)
        elif mode == "hint":
            continue
        elif mode == "opt" and cur["opts"]:
            tail, tail_marked = _strip_marker(l)
            cur["opts"][-1] = _join(cur["opts"][-1], tail)
            if tail_marked:
                cur["marks"][-1] = True
        else:
            cur["q"] = _join(cur["q"], l)

    if cur is not None:
        blocks.append(cur)

    report["blocks"] = len(blocks)
    result: list[dict] = []
    for b in blocks:
        n = len(b["opts"])
        report["option_hist"][n] = report["option_hist"].get(n, 0) + 1
        q = _finish(b, report)
        if q:
            result.append(q)
    return result, report


def _join(a: str, b: str) -> str:
    """Satr oxiridagi tire (PDF/DOCX qator bo'linishi) bo'lsa — bo'shliqsiz, aks holda bo'shliq bilan."""
    a = a.rstrip()
    if a.endswith("-") and b[:1].islower():
        return a + b.lstrip()
    return (a + " " + b).strip()


def _is_new_question(mq, expected_no: int, cur: dict) -> bool:
    """Raqamli faylda: raqam kutilgan keyingi raqam bo'lsa — yangi savol (variant raqami emas)."""
    no = int(mq.group(1) or mq.group(2))
    if expected_no <= no <= expected_no + 5:
        return True
    if cur is not None and no > cur.get("no", 0):
        return True
    return False


def _looks_like_question(l: str) -> bool:
    return l.endswith("?") and len(l) > 12


# ── 3) YAGONA KIRISH NUQTASI ───────────────────────────────
def parse_file_unified(path: str) -> tuple[list[dict], dict]:
    """Fayl turi va tarkibiga qarab mos o'quvchini tanlaydi. → (savollar, hisobot).

    • XLSX     → ustunli jadval (To'g'ri javob ustuni bo'lsa undan)
    • DOCX     → '====' / '++++' / '#' tuzilmasi bo'lsa blok o'quvchi, aks holda matn
    • PDF/TXT  → harfli variantlar; harfsiz bo'lsa (savol '?' bilan) blok o'quvchi
    Barcha holatda javob kaliti bo'limi (1-B 2-C ...) belgilanmagan savollarga qo'llanadi."""
    from utils import format_parsers as FP
    ext = Path(path).suffix.lower()
    text = ""
    qs: list[dict] = []
    rep: dict = {"blocks": 0, "dropped": [], "no_answer": 0, "mode": ""}
    try:
        if ext in (".xlsx", ".xlsm"):
            qs, r = FP.parse_xlsx_table(path)
            rep.update(r, mode="xlsx")
        elif ext == ".docx":
            text = extract_text(path)
            if text.count("====") >= 5 or re.search(r"\+{3,}", text):
                qs, r = FP.parse_docx_blocks(path)
                rep.update(r, mode="docx-blok")
        elif ext == ".txt":
            text = extract_text(path)
            if text.count("====") >= 5 or re.search(r"\+{3,}", text):
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                qs, r = FP.parse_text_blocks(lines)
                rep.update(r, mode="txt-blok")
        if not qs and ext not in (".xlsx", ".xlsm"):
            if not text:
                text = extract_text(path)
            if not text.strip():
                return [], {"blocks": 0, "dropped": [], "no_answer": 0, "error": "matn topilmadi", "mode": ""}
            qs, r = parse_quiz_text(text)
            rep.update(r, mode="matn")
            labeled = len(qs)
            q_marks = sum(1 for l in text.split("\n") if l.strip().endswith("?"))
            if ext == ".pdf" and labeled < max(1, q_marks // 2):
                uq, ur = FP.parse_unlabeled_lines(text.split("\n"))
                if len(uq) > labeled:
                    qs, rep = uq, dict(ur, mode="pdf-harfsiz")
    except Exception as e:
        log.error("parse_file_unified xato (%s): %s", ext, e)
        return [], {"blocks": 0, "dropped": [], "no_answer": 0, "error": str(e), "mode": ""}
    if text:
        applied = FP.apply_answer_key(qs, text)
        rep["key_applied"] = applied
    rep["no_answer"] = sum(1 for q in qs if not q.get("_marked"))
    rep["blocks"] = max(rep.get("blocks", 0), len(qs))
    return qs, rep
