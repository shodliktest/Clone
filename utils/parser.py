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
        elif ext in (".txt", ".csv"):
            return _parse_txt(path)
        elif ext in (".xlsx", ".xls", ".xlsm"):
            return _parse_xlsx(path)
        else:
            return []
    except Exception as e:
        log.error(f"parse_file xato ({ext}): {e}", exc_info=True)
        return []


def _convert_doc(path: str) -> str:
    """
    .doc → .docx konvertatsiya.
    1. LibreOffice (mavjud bo'lsa)
    2. python-docx2txt (fallback)
    3. antiword (fallback)
    """
    outdir = tempfile.mkdtemp()

    # 1. LibreOffice — eng yaxshi natija
    try:
        r = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "docx",
             path, "--outdir", outdir],
            capture_output=True, timeout=60
        )
        new = os.path.join(outdir, Path(path).stem + ".docx")
        if os.path.exists(new) and os.path.getsize(new) > 100:
            log.info(f"DOC → DOCX (LibreOffice): {Path(path).name}")
            return new
    except Exception as e:
        log.warning(f"LibreOffice yo'q yoki xato: {e}")

    # 2. python-docx to'g'ridan o'qib ko'ramiz (ba'zi .doc lar ishlaydi)
    try:
        import docx as _docx
        _docx.Document(path)  # Agar ishlasa — .doc aslida .docx ekan
        log.info(f"DOC to'g'ridan DOCX sifatida o'qildi: {Path(path).name}")
        return path
    except Exception:
        pass

    # 3. Matn sifatida o'qish (oxirgi fallback)
    try:
        import docx2txt
        txt = docx2txt.process(path)
        if txt and len(txt) > 50:
            txt_path = os.path.join(outdir, Path(path).stem + ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(txt)
            log.info(f"DOC → TXT (docx2txt): {Path(path).name}")
            return txt_path
    except Exception:
        pass

    log.error(f"DOC convert qilinmadi: {path}")
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

    # FORMAT B ni BIRINCHI tekshiramiz — ==== + # + ++++ eng aniq marker
    single = [t for t in doc.tables if 1 <= len(t.columns) <= 2]
    if single:
        tlines = []
        for t in single:
            for row in t.rows:
                tlines.append(row.cells[0].text.strip())
            tlines.append("+++++")
        if _is_eq_format(tlines):
            q = _parse_eq_hash(tlines)
            if q:
                return q

    # FORMAT D1/D2/D3: Ko'p ustunli jadvallar
    def _is_real_table(t):
        if len(t.rows) < 5:
            return False
        hdr = " ".join(c.text.strip().lower() for c in t.rows[0].cells)
        return any(k in hdr for k in ["savol","вопрос","topshiriq","question","test"]) or len(t.rows) >= 15

    multicol = [t for t in doc.tables if len(t.columns) >= 4 and _is_real_table(t)]
    if multicol:
        # FORMAT D3: A|B|C|D ustunli jadval
        hdr_upper = [c.text.strip().upper() for c in multicol[0].rows[0].cells]
        if any(h in ("A","B","C","D") for h in hdr_upper):
            q = _parse_abcd_table(multicol)
            if q:
                return q

        # FORMAT D1: Sarlavhali jadval (Savol|To'g'ri|Muqobil)
        q = _parse_table_multicol(multicol)
        if q:
            return q

    # FORMAT D2: Juft ustunli jadval
    double_col = [t for t in doc.tables if len(t.columns) >= 8 and _is_real_table(t)]
    if double_col:
        q = _parse_table_double_col(double_col)
        if q:
            return q

    # FORMAT E: 5x1 jadval (savol + 4 variant, har jadval = 1 savol)
    # ==== belgisi yo'q bo'lsa ishlaydi
    single_1col = [t for t in doc.tables
                   if len(t.columns) == 1 and 3 <= len(t.rows) <= 8]
    if single_1col:
        q = _parse_5x1_tables(single_1col)
        if q:
            return q

    # Paragraflardan
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # FORMAT B: paragraflar ==== + # + ++++
    if _is_eq_format(lines):
        q = _parse_eq_hash(lines)
        if q:
            return q

    # FORMAT G: Har paragraf = 1 savol (ichida \n bilan variantlar)
    if any('\n' in l for l in lines):
        q = _parse_paragraph_per_question(lines)
        if q:
            return q

    # FORMAT F: Standart raqamli
    full_text = "\n".join(lines)
    q = parse_text(full_text)
    if q:
        return q

    # FORMAT F2: Variantsiz
    return _parse_question_list_only(lines)


def _parse_table_double_col(tables) -> list:
    """
    FORMAT D2: Juft ustunli jadval
    Har ustun 2 marta takrorlangan:
    | № | № | Savol | Savol | To'g'ri | To'g'ri | Muqobil | Muqobil |
    Faqat juft indeksli ustunlarni olamiz: 0,2,4,6,8...
    """
    LBL = ["A", "B", "C", "D", "E", "F", "G", "H"]
    questions = []
    for table in tables:
        if not table.rows or len(table.columns) < 6:
            continue
        # Header dan unique ustunlarni topamiz (har 2-ustun)
        header = [c.text.strip().lower() for c in table.rows[0].cells]
        # Juft indeksli ustunlar (0,2,4,6...)
        unique_cols = list(range(0, len(header), 2))

        q_col = -1; corr_col = -1; alt_cols = []
        for idx in unique_cols:
            h = header[idx] if idx < len(header) else ""
            if any(k in h for k in ["savol","topshiriq","вопрос"]):
                q_col = idx
            elif any(k in h for k in ["to'g'ri","tog'ri","правильн","correct","to`g`ri"]):
                corr_col = idx
            elif any(k in h for k in ["muqobil","variant","альт","incorrect"]):
                alt_cols.append(idx)

        if q_col == -1 or corr_col == -1:
            # Avtomatik: 2-ustun savol, 4-ustun to'g'ri, 6+ muqobil
            if len(unique_cols) >= 3:
                q_col = unique_cols[1] if len(unique_cols) > 1 else 2
                corr_col = unique_cols[2] if len(unique_cols) > 2 else 4
                alt_cols = [unique_cols[i] for i in range(3, min(len(unique_cols), 8))]
            else:
                continue

        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) <= max(q_col, corr_col):
                continue
            q_text  = cells[q_col] if q_col < len(cells) else ""
            correct = cells[corr_col] if corr_col < len(cells) else ""
            alts    = [cells[i] for i in alt_cols if i < len(cells) and cells[i]]
            if not q_text or not correct:
                continue
            # Takrorlanganlarni olib tashlaymiz
            if q_text == (cells[q_col+1] if q_col+1 < len(cells) else ""):
                pass  # Takrorlangan — normaldir
            all_opts = list(dict.fromkeys([correct] + alts))  # unique
            opts = []
            for i, o in enumerate(all_opts):
                lbl = LBL[i] if i < len(LBL) else str(i+1)
                opts.append(o if re.match(r"^[A-Ha-h]\s*[).]", o) else f"{lbl}) {o}")
            questions.append({
                "type":"multiple_choice","question":q_text,
                "options":opts,"correct":opts[0],
                "explanation":"","accepted_answers":[],"points":1,
                "_marked": True,
            })
    return questions


def _parse_abcd_table(tables) -> list:
    """
    FORMAT D3: A|B|C|D ustunli jadval
    Header: [FanBobi, Savol, A, B, C, D]
    To'g'ri javob belgilanmagan → _marked=False
    """
    LBL = ["A","B","C","D","E","F","G","H"]
    questions = []

    for table in tables:
        if len(table.columns) < 4 or not table.rows:
            continue
        header = [c.text.strip().upper() for c in table.rows[0].cells]

        # A, B, C, D ustunlarini topamiz
        opt_cols = [i for i, h in enumerate(header)
                    if h in ("A","B","C","D","E","F","G","H")]
        q_col    = next((i for i, h in enumerate(header)
                         if any(k in h.lower() for k in
                                ["SAVOL","TEST","TOPSHIRIG","ВОПРОС","TOPSHIRIQ"])), None)

        if not opt_cols:
            continue
        if q_col is None:
            # Avtomatik: birinchi A dan oldingi ustun = savol
            q_col = opt_cols[0] - 1 if opt_cols[0] > 0 else None
        if q_col is None or q_col >= len(header):
            continue
        if len(opt_cols) < 2:
            continue

        for row in table.rows[1:]:
            cells = [re.sub(r"\s+", " ", c.text).strip() for c in row.cells]
            if len(cells) <= max(q_col, max(opt_cols)):
                continue
            q_text = cells[q_col] if q_col < len(cells) else ""
            if not q_text or len(q_text) < 5:
                continue
            variants = [cells[ci] for ci in opt_cols if ci < len(cells) and cells[ci]]
            if len(variants) < 2:
                continue
            opts = []
            for i, v in enumerate(variants):
                lbl = LBL[i] if i < len(LBL) else str(i+1)
                opts.append(v if re.match(r"^[A-Ha-h]\s*[).]", v) else f"{lbl}) {v}")
            questions.append({
                "type": "multiple_choice", "question": q_text,
                "options": opts, "correct": opts[0],
                "explanation": "", "accepted_answers": [], "points": 1,
                "_marked": False,
            })
    return questions


def _parse_5x1_tables(tables) -> list:
    """
    FORMAT E: 5x1 jadval — har jadval = 1 savol
    Qator 0: Savol matni
    Qator 1-4: Variantlar (to'g'ri javob belgilanmagan → differential)
    """
    LBL = ["A","B","C","D","E","F","G","H"]
    questions = []
    for table in tables:
        if len(table.columns) != 1:
            continue
        rows = [r.cells[0].text.strip() for r in table.rows if r.cells[0].text.strip()]
        if len(rows) < 3:
            continue
        q_text   = rows[0]
        variants = rows[1:]

        # Differential analysis bilan to'g'ri javobni topamiz
        raw = [f"= {v}" for v in variants]  # = prefix qo'shamiz
        clean_v, correct_idx = _find_correct_by_diff(raw)

        opts = []
        for i, v in enumerate(variants[:8]):
            lbl = LBL[i] if i < len(LBL) else str(i+1)
            opts.append(v if re.match(r"^[A-Ha-h]\s*[).]", v) else f"{lbl}) {v}")

        questions.append({
            "type":"multiple_choice","question":q_text,
            "options":opts,
            "correct":opts[correct_idx] if correct_idx >= 0 else opts[0],
            "explanation":"","accepted_answers":[],"points":1,
            "_marked": False,  # Belgilanmagan — AI/serial kerak
        })
    return questions


def _parse_paragraph_per_question(lines: list) -> list:
    """
    FORMAT G: Har paragraf = 1 to'liq savol (raqam yo'q)

    Har element ichida \n bilan ajratilgan:
      Savol matni
      A) Variant 1
      B) ✅ To'g'ri variant
      C) Variant 3

    Har paragraf MUSTAQIL parse qilinadi.
    """
    LBL = ["A","B","C","D","E","F","G","H"]
    questions = []

    for raw_para in lines:
        # \n bo'lmasa — bu format emas
        if '\n' not in raw_para:
            continue

        sub = [l.strip() for l in raw_para.split('\n') if l.strip()]
        if len(sub) < 3:
            continue

        # Birinchi variant qatorini topamiz
        first_opt = None
        for idx, l in enumerate(sub):
            if re.match(r'^[A-Ha-h1-9]\s*[).]', l):
                first_opt = idx
                break

        if first_opt is None or first_opt == 0:
            continue

        # Savol matni
        q_text = ' '.join(sub[:first_opt]).strip()
        if not q_text:
            continue

        # Variantlar — FAQAT bu paragraf ichidagi
        opts = []
        correct_idx = -1

        for opt_line in sub[first_opt:]:
            vm = re.match(r'^([A-Ha-h1-9])\s*[).](.*)', opt_line)
            if not vm:
                continue

            label = vm.group(1).upper()
            rest  = vm.group(2).strip()
            is_correct = False

            # Boshida marker: ✅ * + # ...
            m_start = re.match(
                r'^([✅✓✔★☑•►→√■●▶◆*#+@]|={1,}[*+#]?|-{1,2})\s*(.+)',
                rest
            )
            if m_start:
                is_correct = True
                rest = m_start.group(2).strip()
            else:
                # Oxirida marker
                m_end = re.match(r'^(.+?)\s*([✅✓✔★☑•►→√■●▶◆*#+@])\s*$', rest)
                if m_end:
                    is_correct = True
                    rest = m_end.group(1).strip()

            if not rest:
                continue

            clean = f"{label}) {rest}"
            if is_correct and correct_idx == -1:
                correct_idx = len(opts)
            opts.append(clean)

        if len(opts) < 2:
            continue

        has_mark = correct_idx >= 0
        if correct_idx == -1:
            correct_idx = 0

        questions.append({
            "type":             "multiple_choice",
            "question":         q_text,
            "options":          opts,
            "correct":          opts[correct_idx],
            "explanation":      "",
            "accepted_answers": [],
            "points":           1,
            "_marked":          has_mark,
        })

    return questions



def _parse_question_no_marker(lines: list) -> list:
    """
    FORMAT C2: ? savol, keyingi qatorlar = variantlar (marker yo'q)

    ?Savol matni
    Variant 1
    Variant 2
    Variant 3     ← to'g'ri javob belgilanmagan
    Variant 4
    ?Keyingi savol

    Yoki ? oldida bo'sh joy bo'lishi mumkin:
    ? Savol matni
    ? Savol (bo'sh joy bilan)
    """
    LBL = ["A","B","C","D","E","F","G","H"]
    questions = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Savol: ? bilan boshlanadi
        if not line.startswith("?"):
            i += 1
            continue

        q_text = line[1:].strip()
        i += 1

        # Savol matni tayyor (? dan keyin)
        if not q_text:
            continue

        # Variantlarni yig'amiz — ? bilan tugaguncha
        variants = []
        while i < len(lines):
            vl = lines[i].strip()
            # Keyingi savol
            if vl.startswith("?"):
                break
            # Variant markeri (= * + # ...) — boshqa format, to'xtaymiz
            if any(vl.startswith(v) for v in _VAR_STARTS):
                break
            # Bo'sh qator
            if not vl:
                i += 1
                continue
            variants.append(vl)
            i += 1

        if len(variants) < 2:
            continue

        # Label qo'shamiz
        opts = []
        for j, v in enumerate(variants):
            lbl = LBL[j] if j < len(LBL) else str(j+1)
            opts.append(f"{lbl}) {v}" if not re.match(r"^[A-Ha-h]\s*[).]", v) else v)

        questions.append({
            "type":             "multiple_choice",
            "question":         q_text,
            "options":          opts,
            "correct":          opts[0],  # Belgilanmagan
            "explanation":      "",
            "accepted_answers": [],
            "points":           1,
            "_marked":          False,    # AI/Serial kerak
        })

    return questions



def _parse_xlsx(path: str) -> list:
    """
    XLSX/XLS formatidan savollar ajratish.

    FORMAT X1 — Sarlavhali jadval:
      Savol | To'g'ri javob | Noto'g'ri 1 | Noto'g'ri 2 | Noto'g'ri 3

    FORMAT X2 — A/B/C/D ustunlar (belgilanmagan):
      Savol | A | B | C | D

    FORMAT X3 — Marker bilan (*To'g'ri):
      Savol | *To'g'ri | Xato 1 | Xato 2

    FORMAT X4 — To'g'ri raqam bilan:
      Savol | A | B | C | D | To'g'ri(1)
    """
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas o'rnatilmagan: pip install pandas openpyxl")
        return []

    try:
        xl = pd.ExcelFile(path)
    except Exception as e:
        log.error(f"XLSX ochilmadi: {e}")
        return []

    all_questions = []

    for sheet_name in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet_name, header=None)
            qs = _parse_xlsx_sheet(df)
            all_questions.extend(qs)
        except Exception as e:
            log.warning(f"Sheet '{sheet_name}' xato: {e}")

    return all_questions


def _parse_xlsx_sheet(df) -> list:
    """Bitta sheet dan savollar ajratadi"""
    import pandas as pd

    LBL = ["A","B","C","D","E","F","G","H"]

    # Sarlavha qatorini topamiz (birinchi 5 qator ichida)
    header_row = None
    Q_KW   = ["savol","вопрос","question","topshiriq","топшириқ"]
    C_KW   = ["to'g'ri","tog'ri","to`g`ri","правильн","correct","answer","togri"]
    BAD_KW = ["noto'g'ri","xato","муқобил","incorrect","wrong","notogri","нот"]

    for ri in range(min(5, len(df))):
        row_vals = [str(v).strip().lower() for v in df.iloc[ri] if str(v).strip() and str(v) != "nan"]
        if any(any(k in v for k in Q_KW) for v in row_vals):
            header_row = ri
            break

    if header_row is None:
        # Sarlavha yo'q — birinchi qatordan boshlaymiz
        header_row = -1

    header = [str(v).strip().lower() if str(v) != "nan" else ""
              for v in df.iloc[header_row]] if header_row >= 0 else []

    # Ustunlarni aniqlaymiz
    q_col   = -1
    corr_col = -1
    num_col  = -1   # To'g'ri raqam ustuni (FORMAT X4)
    opt_cols = []   # Variant ustunlari

    if header:
        for i, h in enumerate(header):
            if any(k in h for k in Q_KW):
                q_col = i
            elif any(k in h for k in C_KW) and not any(k in h for k in BAD_KW):
                if re.search(r'\d', h):  # "to'g'ri(1-4)" kabi
                    num_col = i
                else:
                    corr_col = i
            elif any(k in h for k in BAD_KW):
                opt_cols.append(i)
            elif h in ('a','b','c','d','e','f','g','h'):
                opt_cols.append(i)

    # Ustunlar topilmasa — avtomatik aniqlash
    if q_col == -1:
        q_col = 0
    if corr_col == -1 and num_col == -1 and not opt_cols:
        # Birinchi variant to'g'ri (FORMAT X2/belgilanmagan)
        corr_col = 1
        opt_cols = list(range(2, min(df.shape[1], 7)))

    # Data qatorlari
    data_start = header_row + 1 if header_row >= 0 else 0
    questions  = []

    for ri in range(data_start, len(df)):
        row = df.iloc[ri]
        vals = [str(v).strip() if str(v) != "nan" and v == v else ""
                for v in row]

        # Savol matni
        q_text = vals[q_col] if q_col < len(vals) else ""
        q_text = re.sub(r"^\d+[\.\)	]\s*", "", q_text).strip()
        if not q_text or len(q_text) < 3:
            continue

        marked   = False
        correct  = ""
        variants = []

        if corr_col >= 0:
            # FORMAT X1: To'g'ri javob alohida ustunda
            correct = vals[corr_col] if corr_col < len(vals) else ""
            wrong   = [vals[i] for i in opt_cols if i < len(vals) and vals[i]]
            if not correct:
                continue
            # Marker tekshirish (FORMAT X3: *To'g'ri)
            is_c, clean = _is_correct_marker(correct)
            if is_c:
                correct = clean
            variants = [correct] + wrong
            marked   = True

        elif num_col >= 0:
            # FORMAT X4: To'g'ri raqam bilan ko'rsatilgan
            num_str = vals[num_col] if num_col < len(vals) else ""
            try:
                corr_idx = int(float(num_str)) - 1
            except (ValueError, TypeError):
                corr_idx = 0
            variants = [vals[i] for i in opt_cols if i < len(vals) and vals[i]]
            if not variants:
                continue
            corr_idx = max(0, min(corr_idx, len(variants)-1))
            correct  = variants[corr_idx]
            # Tartibi: to'g'ri birinchiga
            variants = [variants[corr_idx]] + [v for i, v in enumerate(variants) if i != corr_idx]
            marked   = True

        else:
            # FORMAT X2: Belgilanmagan — birinchi variant to'g'ri
            opt_pool = [vals[i] for i in opt_cols if i < len(vals) and vals[i]]
            if not opt_pool:
                opt_pool = [vals[i] for i in range(q_col+1, min(len(vals), q_col+6)) if vals[i]]

            # FORMAT X3: Marker tekshirish
            corr_idx = -1
            clean_pool = []
            for vi, v in enumerate(opt_pool):
                is_c, clean = _is_correct_marker(v)
                if is_c and corr_idx == -1:
                    corr_idx = vi
                    clean_pool.append(clean)
                else:
                    clean_pool.append(v)
            opt_pool = clean_pool

            if corr_idx >= 0:
                # Marker topildi
                correct  = opt_pool[corr_idx]
                variants = [opt_pool[corr_idx]] + [v for i,v in enumerate(opt_pool) if i != corr_idx]
                marked   = True
            else:
                # Belgilanmagan
                if not opt_pool:
                    continue
                correct  = opt_pool[0]
                variants = opt_pool
                marked   = False

        if len(variants) < 2:
            continue

        # Label qo'shamiz
        opts = []
        for i, v in enumerate(variants):
            lbl = LBL[i] if i < len(LBL) else str(i+1)
            opts.append(v if re.match(r"^[A-Ha-h]\s*[).]", v) else f"{lbl}) {v}")

        questions.append({
            "type":             "multiple_choice",
            "question":         q_text,
            "options":          opts,
            "correct":          opts[0],
            "explanation":      "",
            "accepted_answers": [],
            "points":           1,
            "_marked":          marked,
        })

    return questions


def _parse_question_list_only(lines: list) -> list:
    """
    FORMAT F: Faqat savollar ro'yxati (variantsiz)
    Har qator = alohida savol. Variantlar yo'q → AI kerak.
    """
    questions = []
    for line in lines:
        line = line.strip()
        if len(line) < 10:
            continue
        q_text = re.sub(r"^\d+\s*[.)]\s*", "", line).strip()
        if not q_text:
            continue
        questions.append({
            "type":"multiple_choice","question":q_text,
            "options":["A) —","B) —","C) —","D) —"],
            "correct":"A) —",
            "explanation":"","accepted_answers":[],"points":1,
            "_marked": False,
        })
    return questions


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

    # FORMAT C: ? savol, variantlar (differential analysis)
    q_cnt   = sum(1 for l in lines if l.startswith("?"))
    var_cnt = sum(1 for l in lines
                  if any(l.startswith(v) for v in _VAR_STARTS))
    if q_cnt > 0 and var_cnt > q_cnt:
        q = _parse_question_eq(full_text)
        if q:
            return q

    # FORMAT C2: ? savol, keyingi qatorlar variant (= yo'q, marker yo'q)
    # Misol: "?Savol\nVariant1\nVariant2\nVariant3\n?Keyingi..."
    if q_cnt > 0:
        q = _parse_question_no_marker(lines)
        if q:
            return q

    # FORMAT A: standart
    return parse_text(full_text)




# ═══════════════════════════════════════════════════════════
#  CORRECT MARKERS — Differential Analysis
# ═══════════════════════════════════════════════════════════
#
#  Mohiyat: variantlarni o'zaro taqqosla.
#  Qaysi variant BOSHQALARDAN FARQ QILSA — o'sha TO'G'RI.
#  Hammasi bir xil bo'lsa — BELGILANMAGAN.
#
#  Misol:
#    = Xato 1      marker: "= "
#    =+To'g'ri     marker: "=+"   ← FARQLI → TO'G'RI
#    = Xato 2      marker: "= "
#    = Xato 3      marker: "= "
# ═══════════════════════════════════════════════════════════

# Barcha taniqli variant belgilari (variant boshlanishi)
_VAR_STARTS = (
    '=', '+', '*', '#', '•', '►', '→', '✓', '✔', '√',
    '■', '●', '▶', '◆', '★', '☑', '–', '—',
)


def _extract_prefix(line: str) -> tuple:
    """
    Qatordan prefiks (marker) va toza matnni ajratadi.
    
    Qaytaradi: (prefix: str, clean: str) | (None, None) variant emas
    
    Misol:
      "=+To'g'ri"   → ("=+", "To'g'ri")
      "= Xato"      → ("= ", "Xato")
      "=Xato"       → ("=", "Xato")
      "*To'g'ri"    → ("*", "To'g'ri")
      "Oddiy matn"  → (None, None)
    """
    s = line.strip()
    if not s:
        return None, None
    
    # Variant belgisi bilan boshlanadimi?
    starts_with_marker = any(s.startswith(v) for v in _VAR_STARTS)
    if not starts_with_marker:
        return None, None
    
    # Prefiksni olish: harf yoki raqam kelguncha
    prefix = ""
    for ch in s:
        if ch.isalpha() or ch.isdigit():
            break
        prefix += ch
    
    clean = s[len(prefix):].strip()
    if not clean:
        return None, None
    
    return prefix, clean


def _find_correct_by_diff(raw_variants: list) -> tuple:
    """
    Differential analysis bilan to'g'ri javobni topadi.
    
    Qaytaradi: (variants: list[str], correct_idx: int)
      correct_idx = -1 → belgilanmagan
    
    Algoritm:
      1. Har variantdan prefiks ajrat
      2. Prefikslar orasidan ENG KAM UCHRAGANINI top
      3. Faqat 1 marta uchrasa → o'sha TO'G'RI
      4. Hammasi teng → BELGILANMAGAN
    """
    from collections import Counter
    
    parsed = []  # [(prefix, clean_text), ...]
    for raw in raw_variants:
        prefix, clean = _extract_prefix(raw)
        if prefix is None:
            continue
        parsed.append((prefix, clean))
    
    if not parsed:
        return [], -1
    
    # Prefikslarni sanab chiqamiz
    prefixes = [p for p, _ in parsed]
    counts = Counter(prefixes)
    
    correct_idx = -1
    
    if len(counts) > 1:
        # Eng kam uchraydigan prefiks
        min_count = min(counts.values())
        rarest = [p for p, c in counts.items() if c == min_count]
        
        # Faqat bitta farqli prefiks bo'lsa — o'sha to'g'ri
        if len(rarest) == 1:
            rare_prefix = rarest[0]
            for i, (p, _) in enumerate(parsed):
                if p == rare_prefix:
                    correct_idx = i
                    break
    
    # Toza variantlarni qaytaramiz
    clean_variants = [clean for _, clean in parsed]
    return clean_variants, correct_idx


def _parse_question_eq(text: str) -> list:
    """
    FORMAT C — ? savol, variantlar (differential analysis bilan):

    Qo'llab-quvvatlanadigan barcha holatlar:

    Holat 1 — Farqli marker (to'g'ri aniqladi):
      ? Savol
      = Xato 1
      =+ To'g'ri    ← =+ farqli → TO'G'RI
      = Xato 2
      = Xato 3

    Holat 2 — Bitta marker boshqacha:
      ? Savol
      = Variant 1
      * To'g'ri     ← * farqli → TO'G'RI
      = Variant 2
      = Variant 3

    Holat 3 — Hammasi bir xil (belgilanmagan):
      ? Savol
      = Variant 1
      = Variant 2
      = Variant 3
      = Variant 4

    Holat 4 — Eski format (bo'sh joysiz = to'g'ri):
      ? Savol
      = Xato 1
      =To'g'ri      ← bo'sh joy yo'q, boshqalari bo'sh joylik → FARQLI
      = Xato 2
    """
    LBL = ["A", "B", "C", "D", "E", "F", "G", "H"]
    questions = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    i = 0

    while i < len(lines):
        # Savol qatorini topamiz
        if not lines[i].startswith("?"):
            i += 1
            continue

        # Savol matni
        q_parts = [lines[i][1:].strip()]
        i += 1
        while i < len(lines):
            if lines[i].startswith("?"):
                break
            prefix, _ = _extract_prefix(lines[i])
            if prefix is not None:
                break
            q_parts.append(lines[i])
            i += 1

        q_text = " ".join(q_parts).strip()
        if not q_text:
            continue

        # Xom variantlarni yig'amiz
        raw_variants = []
        while i < len(lines) and not lines[i].startswith("?"):
            prefix, clean = _extract_prefix(lines[i])
            if prefix is not None:
                raw_variants.append(lines[i])
            i += 1

        if not raw_variants:
            continue

        # Differential analysis
        clean_variants, correct_idx = _find_correct_by_diff(raw_variants)

        if not clean_variants:
            continue

        # A) B) C) D) label qo'shish
        opts = []
        for j, v in enumerate(clean_variants):
            lbl = LBL[j] if j < len(LBL) else str(j + 1)
            opts.append(v if re.match(r"^[A-Ha-h]\s*[).]", v) else f"{lbl}) {v}")

        questions.append({
            "type":             "multiple_choice",
            "question":         q_text,
            "options":          opts,
            "correct":          opts[correct_idx] if correct_idx >= 0 else opts[0],
            "explanation":      "",
            "accepted_answers": [],
            "points":           1,
            "_marked":          correct_idx >= 0,
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
    blocks = re.split(r"\n(?=\s*\d+[\.)] *\S)", "\n" + text.strip())
    result = []
    for b in blocks:
        q = _parse_block(b.strip())
        if q:
            result.append(q)
    return result


def _is_correct_marker(line: str) -> tuple:
    """
    To'g'ri javob belgisini aniqlaydi — 3 ta holat:

    1. BOSHIDA marker:   *A) variant   +B) variant   ===C) variant
    2. LABEL+MARKER:     A)* variant   A)+ variant   A)# variant
    3. OXIRIDA marker:   A) variant*   A) variant +   A) variant#
    """
    ls = line.strip()
    if not ls:
        return False, ls

    _M = r'[*+#•►→✓✔√■●▶◆★☑\-=@~^]'

    # 1. BOSHIDA: ===... yoki marker+harf
    if ls.startswith("==="):
        return True, ls[3:].strip()

    # ==N (2+ teng belgi): ==To'g'ri, ==== ...
    m_eq = re.match(r'^={2,}\s*(.+)$', ls)
    if m_eq:
        return True, m_eq.group(1).strip()

    # --N (2+ tire): --To'g'ri, --- ...
    m_dash = re.match(r'^-{2,}\s*(.+)$', ls)
    if m_dash:
        return True, m_dash.group(1).strip()

    # =* =+ =# =- =• kombinatsiya (= + boshqa marker)
    m_comb = re.match(rf'^=[{re.escape("*+#•►→✓✔√■●▶◆★☑-@~^")}]\s*(.+)$', ls)
    if m_comb:
        return True, m_comb.group(1).strip()

    # marker + harf/raqam (bitta marker, keyin harf)
    if re.match(rf'^{_M}\s*[A-Za-zA-Яа-яёЁ0-9]', ls):
        return True, ls[1:].strip()

    # harfsiz: faqat marker + matn (masalan: * To'g'ri, + Javob)
    if re.match(rf'^{_M}\s+\S', ls):
        return True, ls[1:].strip()

    # 2. LABEL+MARKER O'RTADA: A)* variant, A)+ variant, A)# variant
    m = re.match(
        r'^([A-Ha-hА-Яа-яёЁ1-9])\s*[).]\s*'
        r'([*+#•►→✓✔√■●▶◆★☑\-=])\s*'
        r'(.+)$', ls
    )
    if m:
        label, marker, text = m.group(1), m.group(2), m.group(3).strip()
        if marker in ('-', '=') and not re.match(r'^[A-Za-zA-Яа-яёЁ0-9(«"\']', text):
            return False, ls
        return True, f"{label}) {text}"

    # 3. OXIRIDA: A) variant* yoki A) variant +
    m2 = re.match(
        r'^([A-Ha-hА-Яа-яёЁ1-9])\s*[).]\s*'
        r'(.+?)\s*'
        r'([*+#•►→✓✔√■●▶◆★☑=])\s*$', ls
    )
    if m2:
        label, text, marker = m2.group(1), m2.group(2).strip(), m2.group(3)
        if len(text) < 1:
            return False, ls
        return True, f"{label}) {text}"

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

    # Variantlardan markerlarni tozalaymiz
    # _is_correct_marker allaqachon toza matn qaytaradi
    # Lekin opts da hali marker qolgan bo'lishi mumkin
    def _strip_marker(text: str) -> str:
        ok, clean = _is_correct_marker(text)
        if ok:
            return clean
        # Oddiy variant — label ni saqlaymiz
        return re.sub(r"^===\s*", "", text).strip()

    clean_opts = [_strip_marker(o) for o in opts]
    if corr:
        corr = _strip_marker(corr)

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
