"""
📄 PARSER — TXT/PDF/DOCX fayllardan savollar ajratish

QO'LLAB-QUVVATLANADIGAN FORMATLAR:

FORMAT A — Standart (raqamli):
  1. Savol matni?
  *A) To'g'ri javob
  B) Xato
  C) Xato

FORMAT B — ==== separator (ZIP fayllar):
  Savol matni
  ====
  #To'g'ri javob     ← # bilan to'g'ri
  ====
  Xato javob
  ++++               ← keyingi savol

FORMAT C — ? = formati (PDF):
  ? Savol matni
  =To'g'ri           ← bo'sh joy yo'q = to'g'ri
  = Xato

FORMAT D — Jadval (Ko'p ustunli DOCX):
  Savol | To'g'ri javob | Muqobil | Muqobil

FORMAT E — Ha/Yo'q, Bo'sh joy to'ldirish, Erkin javob
"""
import re, logging, os, subprocess, tempfile
from pathlib import Path

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
#  ASOSIY KIRISH NUQTASI
# ═══════════════════════════════════════════════════════════

def parse_file(path: str) -> list:
    ext = Path(path).suffix.lower()
    try:
        # .doc → .docx konvertatsiya
        if ext == ".doc":
            path = _convert_doc(path)
            if not path:
                return []
            ext = ".docx"

        if ext == ".docx":
            return _parse_docx(path)
        elif ext == ".pdf":
            return _parse_pdf(path)
        elif ext == ".txt":
            return _parse_txt(path)
        else:
            return []
    except Exception as e:
        log.error(f"parse_file xato ({ext}): {e}", exc_info=True)
        return []


def _convert_doc(path: str) -> str:
    """LibreOffice bilan .doc → .docx"""
    outdir = tempfile.mkdtemp()
    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "docx",
             path, "--outdir", outdir],
            capture_output=True, timeout=30
        )
        new = os.path.join(outdir, Path(path).stem + ".docx")
        return new if os.path.exists(new) else ""
    except Exception as e:
        log.warning(f"DOC convert xato: {e}")
        return ""


# ═══════════════════════════════════════════════════════════
#  DOCX PARSER — barcha jadval va paragraf formatlar
# ═══════════════════════════════════════════════════════════

def _parse_docx(path: str) -> list:
    try:
        from docx import Document
        doc = Document(path)
    except Exception as e:
        log.error(f"DOCX ochilmadi: {e}")
        return []

    # FORMAT D: Ko'p ustunli jadval
    multicol = [t for t in doc.tables if len(t.columns) >= 4]
    if multicol:
        q = _parse_table_multicol(multicol)
        if q:
            return q

    # FORMAT B: 1 ustunli jadval (==== + # + ++++)
    single = [t for t in doc.tables if 1 <= len(t.columns) <= 2]
    if single:
        lines = []
        for t in single:
            for row in t.rows:
                lines.append(row.cells[0].text.strip())
            lines.append("+++++")
        if _is_eq_format(lines):
            q = _parse_eq_hash(lines)
            if q:
                return q

    # Paragraflardan
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # FORMAT B: paragraflar ==== + # + ++++
    if _is_eq_format(lines):
        q = _parse_eq_hash(lines)
        if q:
            return q

    # FORMAT A: standart raqamli format
    full_text = "\n".join(lines)
    return parse_text(full_text)


def _parse_table_multicol(tables) -> list:
    """Ko'p ustunli jadval: Savol | To'g'ri | Muqobil | Muqobil"""
    questions = []
    LBL = ["A", "B", "C", "D", "E", "F", "G", "H"]
    for table in tables:
        if not table.rows or len(table.columns) < 4:
            continue
        header = [c.text.strip().lower() for c in table.rows[0].cells]
        q_col = -1; corr_col = -1; alt_cols = []
        for i, h in enumerate(header):
            if any(k in h for k in ["savol", "topshiriq", "вопрос", "test"]):
                q_col = i
            elif any(k in h for k in ["to'g'ri", "tog'ri", "правильн", "correct"]):
                corr_col = i
            elif any(k in h for k in ["muqobil", "variant", "альт"]):
                alt_cols.append(i)
        if q_col == -1 or corr_col == -1:
            if len(header) >= 4:
                q_col = 1; corr_col = 2
                alt_cols = list(range(3, min(len(header), 7)))
            else:
                continue
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) <= max(q_col, corr_col):
                continue
            q_text = cells[q_col]
            correct = cells[corr_col]
            alts = [cells[i] for i in alt_cols if i < len(cells) and cells[i]]
            if not q_text or not correct:
                continue
            all_opts = [correct] + alts
            opts = []
            for i, o in enumerate(all_opts):
                lbl = LBL[i] if i < len(LBL) else str(i+1)
                opts.append(o if re.match(r"^[A-Ha-h]\s*[).]", o) else f"{lbl}) {o}")
            questions.append({
                "type": "multiple_choice", "question": q_text,
                "options": opts, "correct": opts[0],
                "explanation": "", "accepted_answers": [], "points": 1,
                "_marked": True,
            })
    return questions


# ═══════════════════════════════════════════════════════════
#  FORMAT B: ==== + # + ++++ parser  (asosiy logika)
# ═══════════════════════════════════════════════════════════

def _is_eq_format(lines: list) -> bool:
    has_eq   = any(re.match(r"^={3,}$", l) for l in lines)
    has_plus = any(re.match(r"^\+{3,}$", l) for l in lines)
    return has_eq and has_plus


def _clean_text(text: str) -> str:
    """Matnni tozalaydi: bold, pipe, ko'p bo'shliq, bosh raqam"""
    import re as _re
    text = _re.sub(r'\*\*', '', text)
    text = _re.sub(r'\|', '', text)
    text = _re.sub(r'[ \t]+', ' ', text)
    text = _re.sub(r'^\d+[\.)\]]\s*', '', text)
    return text.strip()


def _is_valid_block(parts: list) -> bool:
    if not parts or len(parts[0]) > 800:
        return False
    return any(len(a.strip()) < 200 for a in parts[1:])


def _clean_table_block(block: str) -> str:
    lines = block.split('\n')
    if not any('|' in l for l in lines):
        return block
    cells = []
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            if line: cells.append(line)
            continue
        if re.match(r'^\|[\s\-\|]+\|$', line):
            continue
        parts = [p.strip() for p in line.split('|') if p.strip()]
        for p in parts:
            if not re.match(r'^=+$', p):
                cells.append(p)
    return '\n'.join(cells)


def _parse_eq_hash(lines: list) -> list:
    """
    Asosiy logika (hujjatdan):
      ++++ → savollar chegarasi
      ==== → savol/javob chegarasi
      #    → to'g'ri javob belgisi
    """
    LBL = ["A", "B", "C", "D", "E", "F", "G", "H"]
    questions = []

    content = "\n".join(lines)

    # 1-QADAM: ++++ bo'yicha bloklarga ajratish
    blocks = re.split(r'\+{4,}', content)
    blocks = [b.strip() for b in blocks if b.strip()]

    for block in blocks:
        block = _clean_table_block(block)

        # 2-QADAM: ==== bo'yicha parts ga ajratish
        parts = re.split(r'={3,}', block)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) < 2:
            continue
        if not _is_valid_block(parts):
            continue

        question = _clean_text(parts[0])
        if not question:
            continue

        # 3-QADAM: # bilan to'g'ri javobni topish
        correct_idx = -1
        clean_answers = []

        for ans in parts[1:]:
            ans = ans.strip()
            if ans.startswith('#'):
                if correct_idx == -1:
                    correct_idx = len(clean_answers)
                clean_answers.append(_clean_text(ans[1:]))
            else:
                clean_answers.append(_clean_text(ans))

        clean_answers = [a for a in clean_answers if a]
        if not clean_answers:
            continue

        has_mark = correct_idx != -1
        if correct_idx == -1:
            correct_idx = 0
        if correct_idx >= len(clean_answers):
            correct_idx = 0

        opts = []
        for i, ans in enumerate(clean_answers):
            lbl = LBL[i] if i < len(LBL) else str(i + 1)
            opts.append(ans if re.match(r"^[A-Ha-h]\s*[).]", ans) else f"{lbl}) {ans}")

        questions.append({
            "type":             "multiple_choice",
            "question":         question,
            "options":          opts,
            "correct":          opts[correct_idx],
            "explanation":      "",
            "accepted_answers": [],
            "points":           1,
            "_marked":          has_mark,
        })

    return questions


# ═══════════════════════════════════════════════════════════
#  PDF PARSER
# ═══════════════════════════════════════════════════════════

def _parse_pdf(path: str) -> list:
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        full_text = "\n".join(pages)
    except Exception as e:
        log.error(f"PDF ochilmadi: {e}")
        return []

    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # FORMAT B: ==== + ++++
    if _is_eq_format(lines):
        q = _parse_eq_hash(lines)
        if q:
            return q

    # FORMAT C: ? savol, = variant
    q_cnt  = sum(1 for l in lines if l.startswith("?"))
    eq_cnt = sum(1 for l in lines if l.startswith("="))
    if q_cnt > 0 and eq_cnt > q_cnt:
        q = _parse_question_eq(full_text)
        if q:
            return q

    # FORMAT A: standart
    return parse_text(full_text)


def _parse_question_eq(text: str) -> list:
    """
    ? Savol matni
    = Xato variant
    =To'g'ri variant   ← bo'sh joy yo'q = to'g'ri
    = Xato
    """
    LBL = ["A", "B", "C", "D", "E", "F", "G", "H"]
    questions = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    i = 0
    while i < len(lines):
        if not lines[i].startswith("?"):
            i += 1
            continue
        q_parts = [lines[i][1:].strip()]
        i += 1
        while i < len(lines) and not lines[i].startswith("=") and not lines[i].startswith("?"):
            q_parts.append(lines[i])
            i += 1
        q_text = " ".join(q_parts).strip()
        options = []; correct_idx = -1
        while i < len(lines) and lines[i].startswith("="):
            opt = lines[i]
            if len(opt) > 1 and opt[1] != " ":
                if correct_idx == -1:
                    correct_idx = len(options)
                options.append(opt[1:].strip())
            else:
                options.append(opt[1:].strip())
            i += 1
        if not options:
            continue
        if correct_idx == -1:
            correct_idx = 0
        opts = []
        for j, o in enumerate(options):
            lbl = LBL[j] if j < len(LBL) else str(j+1)
            opts.append(o if re.match(r"^[A-Ha-h]\s*[).]", o) else f"{lbl}) {o}")
        questions.append({
            "type": "multiple_choice", "question": q_text,
            "options": opts, "correct": opts[correct_idx],
            "explanation": "", "accepted_answers": [], "points": 1,
            "_marked": True,
        })
    return questions


# ═══════════════════════════════════════════════════════════
#  TXT PARSER
# ═══════════════════════════════════════════════════════════

def _parse_txt(path: str) -> list:
    text = _read_txt(path)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if _is_eq_format(lines):
        q = _parse_eq_hash(lines)
        if q:
            return q
    if sum(1 for l in lines if l.startswith("?")) > 0:
        q = _parse_question_eq(text)
        if q:
            return q
    return parse_text(text)


def _read_txt(path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            pass
    return ""


# ═══════════════════════════════════════════════════════════
#  FORMAT A — STANDART RAQAMLI (mavjud logika saqlanadi)
# ═══════════════════════════════════════════════════════════

def parse_text(text: str) -> list:
    text = text.replace("\r\n", "\n")
    blocks = re.split(r"\n(?=\d+[\.)] *\S)", "\n" + text.strip())
    result = []
    for b in blocks:
        q = _parse_block(b.strip())
        if q:
            result.append(q)
    return result


def _is_correct_marker(line: str) -> tuple:
    ls = line.strip()
    if ls.startswith("==="):
        return True, ls[3:].strip()
    if re.match(r"^[*+]\s*[A-Za-zA-Яа-яёЁ0-9]", ls):
        return True, ls[1:].strip()
    return False, ls


def _parse_block(block: str) -> dict | None:
    lines = [l.rstrip() for l in block.split("\n") if l.strip()]
    if not lines:
        return None

    forced = None
    if lines[0].upper().startswith("TYPE:"):
        forced = lines[0].split(":", 1)[1].strip().lower()
        lines = lines[1:]
    if not lines:
        return None

    q_text = re.sub(r"^\d+[\.)] *", "", lines[0]).strip()
    if not q_text:
        return None

    opts = []; corr = None; expl = ""; javob = None; acc = []; photo_id = None

    pm = re.match(r"^\[rasm:\s*([^\]]+)\]\s*", q_text)
    if pm:
        photo_id = pm.group(1).strip()
        q_text = q_text[pm.end():].strip()

    for line in lines[1:]:
        ls = line.strip()
        if not ls:
            continue
        if ls.startswith("[rasm:") and ls.endswith("]"):
            photo_id = ls[6:-1].strip()
            continue
        if ls.lower().startswith("izoh:"):
            expl = ls.split(":", 1)[1].strip()
            continue
        if re.match(r"^(qabul|accepted)\s*:", ls, re.IGNORECASE):
            acc = [a.strip() for a in re.split(r"[,;]", ls.split(":", 1)[1]) if a.strip()]
            continue
        if ls.lower().startswith("javob:"):
            javob = ls.split(":", 1)[1].strip()
            continue
        is_correct, cleaned = _is_correct_marker(ls)
        if is_correct:
            opts.append(cleaned)
            corr = cleaned
            continue
        if re.match(r"^[A-Za-zA-Яа-яёЁ0-9]\s*[\).]\s*", ls):
            opts.append(ls)
            continue

    if forced:
        qtype = forced
    elif javob is not None:
        jl = javob.lower().strip()
        if jl in ("ha", "yoq", "yo'q", "true", "false", "yes", "no"):
            qtype = "true_false"
        else:
            qtype = "fill_blank"
    elif opts:
        qtype = "multiple_choice"
    else:
        qtype = "text_input"

    if qtype == "true_false":
        corr = "Ha" if (javob or "").lower().strip() in ("ha", "true", "yes") else "Yo'q"
    elif qtype in ("text_input", "fill_blank"):
        corr = javob or corr or ""
    elif corr is None and opts:
        corr = opts[0]

    clean_opts = [re.sub(r"^[*+]\s*", "", re.sub(r"^===\s*", "", o)).strip() for o in opts]
    if corr:
        corr = re.sub(r"^[*+]\s*", "", re.sub(r"^===\s*", "", corr)).strip()

    has_marked = any(_is_correct_marker(l)[0] for l in lines[1:] if l.strip())

    result = {
        "type":             qtype,
        "question":         q_text,
        "options":          clean_opts if qtype in ("multiple_choice", "multi_select") else [],
        "correct":          corr or "",
        "explanation":      expl,
        "accepted_answers": acc,
        "points":           1,
        "_marked":          has_marked,
    }
    if photo_id:
        result["photo"] = photo_id
    return result
