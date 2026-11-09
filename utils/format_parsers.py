"""
Tuzilmaga xos o'quvchilar. Har biri savol dict ro'yxatini qaytaradi (utils.quiz_text bilan bir xil shakl):
    {"type","question","options":["A) ..",..],"correct","correct_index","explanation",
     "accepted_answers","points","_marked","number"}

  parse_docx_blocks(path)   — "====" ajratgichli DOCX: savol, variantlar, '#' = to'g'ri, '++++' = blok oxiri
  parse_xlsx_table(path)    — ustunli jadval: savol ustuni, variant ustunlari, ixtiyoriy "To'g'ri javob" ustuni
  parse_unlabeled_lines(ls) — harfsiz PDF: savol '?' bilan tugaydi, undan keyin 4 ta variant
  apply_answer_key(qs, text)— "1-B 2-C ..." yoki "1. B" ko'rinishidagi javob kaliti
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

_SEP = re.compile(r"^\s*=+\s*$")
_NEW_Q = re.compile(r"^\s*\d{1,4}\.\s+\S")
_BLOCK_END = re.compile(r"^\s*\+{3,}")
_NUM_PREFIX = re.compile(r"^\s*\d{1,4}\s*[\.\)]\s*")
_LBL = re.compile(r"^\s*[A-Ja-j]\s*[\)\.:]\s*")
_WS = re.compile(r"\s+")
_UNSURE = re.compile(r"\s*\(\?\)\s*")
_HEADER_KEYS = ("savol", "test topshir", "topshiriq", "to'g'ri javob", "to’g’ri javob", "muqobil")


def _clean(s) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\xa0", " ").replace("\u200b", "")
    return _WS.sub(" ", s).strip()


def _mk(number: int, question: str, opts: list[str], ci: int | None, expl: str = "") -> dict:
    labeled = [f"{chr(65 + i)}) {o}" for i, o in enumerate(opts)]
    return {
        "type": "multiple_choice",
        "question": question,
        "options": labeled,
        "correct": (f"{chr(65 + ci)}) {opts[ci]}" if ci is not None else None),
        "correct_index": ci,
        "explanation": expl,
        "accepted_answers": [],
        "points": 1,
        "_marked": ci is not None,
        "number": number,
    }


# ── 1) DOCX: ====, #, ++++ ───────────────────────────────────
def _docx_lines(path: str) -> list[str]:
    """DOCX dagi barcha matn (paragraf + jadval katakchalari), hujjat tartibida."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(path)
    out: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(_clean(Paragraph(child, doc).text))
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                for c in row.cells:
                    for par in c.paragraphs:
                        out.append(_clean(par.text))
    return [x for x in out if x]


def parse_docx_blocks(path: str) -> tuple[list[dict], dict]:
    """Qoida: savol → (====  variant)* → '++++' (blok oxiri). '#' belgili variant = to'g'ri javob.
    Sarlavha va noto'g'ri bloklar (6 tadan ko'p variant) tashlanadi va hisobotga yoziladi."""
    lines = _docx_lines(path)
    out: list[dict] = []
    rep = {"blocks": 0, "dropped": []}
    q_text: str | None = None
    q_open = False           # savol matni hali davom etyaptimi (birinchi '====' gacha)
    opts: list[str] = []
    ci: int | None = None

    def close():
        nonlocal q_text, opts, ci
        if q_text is not None:
            rep["blocks"] += 1
            if len(opts) > 6:
                rep["dropped"].append((rep["blocks"], "sarlavha yoki buzilgan blok: " + q_text[:60]))
            else:
                _finish_block(out, rep, len(out) + 1, q_text, opts, ci)
        q_text, opts, ci = None, [], None

    for raw in lines:
        if "++++" in raw:                                # blok oxiri (ichida matn bo'lishi mumkin)
            pre = raw.split("++++", 1)[0].strip()
            if pre and q_text is not None and not _SEP.match(pre):
                marked = pre.startswith("#")
                if marked:
                    ci = len(opts)
                opts.append(_LBL.sub("", pre).lstrip("#").strip())
            close()
            continue
        # '++++' tushib qolgan bo'lsa ham, raqamli yangi savol boshlanishi yangi blok
        if q_text is not None and not q_open and len(opts) >= 2 and _NEW_Q.match(raw):
            close()
        if _SEP.match(raw):
            q_open = False
            continue
        if q_text is None:
            q_text, q_open = raw, True                   # blok boshlanishi: savol
            continue
        if q_open:                                       # ko'p qatorli savol (she'r, shart)
            q_text = q_text + " " + raw
            continue
        marked = raw.startswith("#")
        if marked:
            ci = len(opts)
        opts.append(raw.lstrip("#").strip())
    close()
    return out, rep


def _finish_block(out, rep, no, q_text, opts, ci):
    q = _NUM_PREFIX.sub("", _UNSURE.sub(" ", q_text)).strip()
    opts = [o for o in opts if o]
    if not q or len(opts) < 2:
        rep["dropped"].append((no, "savol yoki variant yetarli emas"))
        return
    if any(re.fullmatch(r"[=+\-_*.\s]{2,}", o) for o in opts):
        rep["dropped"].append((no, "buzilgan variant (manbada matn yo'q): " + q[:50]))
        return
    out.append(_mk(no, q, opts, ci))


# ── 2) XLSX: ustunli jadval ─────────────────────────────────
def parse_xlsx_table(path: str) -> tuple[list[dict], dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: list[dict] = []
    rep = {"blocks": 0, "dropped": [], "sheet": None}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        hdr_i, cols = _find_header(rows)
        if hdr_i is None:
            continue
        rep["sheet"] = ws.title
        q_col = cols["question"]
        corr_col = cols.get("correct")
        opt_cols = cols["options"]
        for r in rows[hdr_i + 1:]:
            q = _clean(r[q_col]) if q_col < len(r) else ""
            if not q:
                continue
            q = _NUM_PREFIX.sub("", q).strip()
            rep["blocks"] += 1
            vals = [_clean(r[c]) if c < len(r) else "" for c in opt_cols]
            ci = None
            if corr_col is not None:
                cv = _clean(r[corr_col]) if corr_col < len(r) else ""
                if cv and cv in vals:
                    ci = vals.index(cv)
                elif cv:
                    vals = vals + [cv]
                    ci = len(vals) - 1
            vals = [v for v in vals if v]
            if ci is not None and ci >= len(vals):
                ci = None
            if len(vals) < 2:
                rep["dropped"].append((rep["blocks"], "variant yetarli emas"))
                continue
            out.append(_mk(len(out) + 1, q, vals, ci))
        if out:
            break
    return out, rep


def _find_header(rows):
    for i, r in enumerate(rows[:6]):
        cells = [_clean(c).lower() for c in r]
        if not any(any(k in c for k in _HEADER_KEYS) for c in cells):
            continue
        cols = {"options": []}
        for j, c in enumerate(cells):
            if not c or c in ("№", "no", "#"):
                continue
            if "savol" in c or "topshir" in c or c.startswith("test"):
                cols.setdefault("question", j)
            elif "to'g'ri" in c or "to’g’ri" in c or "tog'ri" in c:
                cols["correct"] = j
            elif "muqobil" in c or len(c) == 1 and c.isalpha() or c.startswith(("variant", "javob")):
                cols["options"].append(j)
        if "question" in cols:
            cols["options"] = sorted(set(cols["options"]) - {cols.get("correct")})
            if "correct" in cols:
                # To'g'ri javob ustuni ham variant ustunlaridan biri sifatida hisoblanadi
                cols["options"] = sorted(set(cols["options"]) | {cols["correct"]})
            if len(cols["options"]) >= 2:
                return i, cols
    return None, None


# ── 3) Harfsiz PDF: savol '?' bilan, keyin 4 variant ─────────
def parse_unlabeled_lines(lines: list[str], opt_count: int = 4) -> tuple[list[dict], dict]:
    ls = [_clean(l) for l in lines]
    ls = [l for l in ls if l and not re.fullmatch(r"\d{1,4}", l)]
    out: list[dict] = []
    rep = {"blocks": 0, "dropped": []}
    pos = 0
    n = len(ls)
    while pos < n:
        e = pos
        while e < n and not ls[e].endswith("?"):
            e += 1
        if e >= n:
            break
        q = " ".join(ls[pos:e + 1]).strip()
        opts = ls[e + 1:e + 1 + opt_count]
        rep["blocks"] += 1
        if len(opts) < opt_count or any(o.endswith("?") for o in opts):
            rep["dropped"].append((rep["blocks"], q[:60]))
            pos = e + 1
            continue
        out.append(_mk(len(out) + 1, q, opts, None))
        pos = e + 1 + opt_count
    return out, rep


# ── 4) Javob kaliti: "1-B 2-C" yoki "1. B" ──────────────────
_KEY_PAIR = re.compile(r"(?<!\d)(\d{1,4})\s*[-.)]\s*([A-Ja-j])(?![A-Za-z])")


def apply_answer_key(qs: list[dict], text: str) -> int:
    """Kalit bo'limini topib, belgilanmagan savollarga to'g'ri javob indeksini qo'yadi. → qo'yilganlar soni."""
    m = re.search(r"javob\w*\s*kalit\w*|kalit\s*javob\w*|javoblar\s*kaliti", text, re.I)
    tail = text[m.end():] if m else ""
    if not tail:
        return 0
    byno = {int(a): ord(b.upper()) - 65 for a, b in _KEY_PAIR.findall(tail)}
    applied = 0
    for q in qs:
        if q.get("_marked"):
            continue
        ci = byno.get(int(q.get("number", -1)))
        if ci is not None and 0 <= ci < len(q["options"]):
            opts = [re.sub(r"^[A-Ja-j]\s*[\)\.:]\s*", "", o) for o in q["options"]]
            q["correct_index"] = ci
            q["correct"] = f"{chr(65 + ci)}) {opts[ci]}"
            q["_marked"] = True
            applied += 1
    return applied
