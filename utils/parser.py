"""
📄 UNIVERSAL PARSER — 20+ formatdagi test fayllarini qabul qiladi

Qo'llab-quvvatlanadigan formatlar:
  1. Standart: 1. Savol? *A) To'g'ri  B) Xato
  2. Plus: +A) To'g'ri
  3. Tenglik: ===A) To'g'ri
  4. Raqamli to'g'ri: (1) yoki [1] yoki {1}
  5. Harf qavssiz: A. To'g'ri  B. Xato
  6. Savol raqamsiz: to'g'ri javob belgisi bilan
  7. Javob: qatori bilan
  8. Ha/Yo'q formati
  9. Matn kiritish (fill blank)
  10. Numbered list: 1) 2) 3) 4) variantlar
  11. Dash: - To'g'ri  - Xato
  12. Bold: **To'g'ri javob**
  13. Bracket correct: [To'g'ri]
  14. Ko'p to'g'ri: multi_select
  15. Inline format: 1.Savol? a)Var b)*Var c)Var
  16. Tab-separated: Savol\tA\tB\t*C\tD
  17. CSV-like: "Savol","A","B","*C","D"
  18. Numbered correct: To'g'ri: 2 (2-variant to'g'ri)
  19. Arrow: Savol → To'g'ri javob
  20. DOCX rang: qizil/yashil/qalin belgilangan
"""
import re, logging, io, json
from pathlib import Path

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# FAYL O'QISH
# ══════════════════════════════════════════════════════════════

def parse_file(path: str) -> list:
    ext = Path(path).suffix.lower()
    try:
        # .doc ni avval .docx ga convert qilamiz
        if ext == ".doc":
            import subprocess, tempfile
            outdir = tempfile.mkdtemp()
            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "docx",
                 path, "--outdir", outdir],
                capture_output=True, timeout=30
            )
            new_name = Path(path).stem + ".docx"
            converted = Path(outdir) / new_name
            if converted.exists():
                path = str(converted)
                ext = ".docx"

        if ext == ".txt":
            text = _read_txt(path)
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            # ZIP formatmi?
            if _is_zip_format(lines):
                q = _parse_equals_hash(lines)
                if q:
                    return q
            return parse_text(text)

        elif ext == ".pdf":
            text = _read_pdf(path)
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            # ZIP formatmi?
            if _is_zip_format(lines):
                q = _parse_equals_hash(lines)
                if q:
                    return q
            # ? = formatmi?
            q_cnt = sum(1 for l in lines if l.startswith("?"))
            eq_cnt = sum(1 for l in lines if l.startswith("="))
            if q_cnt > 0 and eq_cnt > q_cnt:
                q = _parse_question_eq(text)
                if q:
                    return q
            return parse_text(text)

        elif ext == ".docx":
            return _parse_docx_smart(path)

        else:
            return parse_text(_read_txt(path))

    except Exception as e:
        log.error(f"parse_file {path}: {e}")
        return []


def _is_zip_format(lines: list) -> bool:
    """ZIP fayllaridagi ==== + ++++ formatni aniqlaydi"""
    has_eq   = any(re.match(r'^={3,}$', l) for l in lines)
    has_plus = any(re.match(r'^\+{3,}$', l) for l in lines)
    return has_eq and has_plus


def _parse_equals_hash(lines: list) -> list:
    """
    ZIP fayllaridagi asosiy format:

    Savol matni
    ====
    #To'g'ri javob       <- # bilan to'g'ri belgilangan
    ====
    Xato javob
    ====
    Xato javob
    ++++                 <- keyingi savol

    Yoki # yo'q bo'lsa birinchi variant to'g'ri hisoblanadi.
    """
    questions = []
    labels = ['A','B','C','D','E','F','G','H']

    blocks = []
    current = []
    for line in lines:
        s = line.strip()
        if re.match(r'^\+{3,}$', s):
            if current:
                blocks.append(current[:])
            current = []
        else:
            if s:
                current.append(s)
    if current:
        blocks.append(current)

    for block in blocks:
        parts = []
        cur = []
        for line in block:
            if re.match(r'^={3,}$', line):
                joined = ' '.join(cur).strip()
                if joined:
                    parts.append(joined)
                cur = []
            else:
                cur.append(line)
        if cur:
            joined = ' '.join(cur).strip()
            if joined:
                parts.append(joined)

        if len(parts) < 3:
            continue

        q_text = re.sub(r'^\d+\s*[.)]\s*', '', parts[0]).strip()
        if not q_text:
            continue

        variants = list(parts[1:])
        correct_idx = -1

        for i, v in enumerate(variants):
            if v.startswith('#'):
                correct_idx = i
                variants[i] = v[1:].strip()
                break

        variants = [v for v in variants if v]
        if not variants:
            continue

        # # belgisi bor = aniq belgilangan
        has_hash = correct_idx != -1

        # # belgi yo'q bo'lsa birinchi variant to'g'ri (ba'zi fayllar shunday)
        if correct_idx == -1:
            correct_idx = 0

        if correct_idx >= len(variants):
            continue

        opts = []
        for i, v in enumerate(variants):
            lbl = labels[i] if i < len(labels) else str(i+1)
            if not re.match(r'^[A-Ha-h]\s*[).]', v):
                v = f"{lbl}) {v}"
            opts.append(v)

        questions.append({
            "type":        "multiple_choice",
            "question":    q_text,
            "text":        q_text,
            "options":     opts,
            "correct":     opts[correct_idx],
            "explanation": "",
            "points":      1,
            "_marked":     has_hash,  # True = # bilan aniq belgilangan
        })

    return questions


def _parse_question_eq(text: str) -> list:
    """
    PDF ? = formati:
    ? Savol matni
    = Xato variant
    =To'g'ri (bo'sh joy yo'q = to'g'ri)
    = Xato
    """
    questions = []
    labels = ['A','B','C','D','E','F','G','H']
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    i = 0
    while i < len(lines):
        if not lines[i].startswith('?'):
            i += 1
            continue
        q_parts = [lines[i][1:].strip()]
        i += 1
        while i < len(lines) and not lines[i].startswith('=') and not lines[i].startswith('?'):
            q_parts.append(lines[i])
            i += 1
        q_text = ' '.join(q_parts).strip()
        options = []; correct_idx = -1
        while i < len(lines) and lines[i].startswith('='):
            opt = lines[i]
            if len(opt) > 1 and opt[1] != ' ':
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
            lbl = labels[j] if j < len(labels) else str(j+1)
            if not re.match(r'^[A-Ha-h]\s*[).]', o):
                o = f"{lbl}) {o}"
            opts.append(o)
        questions.append({
            "type":"multiple_choice","question":q_text,"text":q_text,
            "options":opts,"correct":opts[correct_idx],"explanation":"","points":1,
            "_marked": correct_idx != -1 or True,  # = formati aniq belgilangan
        })
    return questions


def _read_txt(path):
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return Path(path).read_text(encoding=enc)
        except Exception:
            continue
    return ""


def _read_pdf(path):
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        return "\n".join(pages)
    except Exception:
        pass
    try:
        import PyPDF2
        with open(path, "rb") as f:
            r = PyPDF2.PdfReader(f)
            return "\n".join(p.extract_text() or "" for p in r.pages)
    except Exception:
        return ""


def _parse_multicol_docx(tables) -> list:
    """Ko'p ustunli jadval: Savol | To'g'ri javob | Muqobil | Muqobil"""
    import re
    questions = []
    labels = ['A','B','C','D','E','F','G','H']
    for table in tables:
        if not table.rows or len(table.columns) < 4:
            continue
        header = [c.text.strip().lower() for c in table.rows[0].cells]
        q_col = -1; correct_col = -1; alt_cols = []
        for i, h in enumerate(header):
            if any(kw in h for kw in ["savol","topshiriq","test","вопрос"]):
                q_col = i
            elif any(kw in h for kw in ["to'g'ri","tog'ri","правильн","correct"]):
                correct_col = i
            elif any(kw in h for kw in ["muqobil","variant","альт"]):
                alt_cols.append(i)
        if q_col == -1 or correct_col == -1:
            if len(header) >= 4:
                q_col = 1; correct_col = 2
                alt_cols = list(range(3, min(len(header), 7)))
            else:
                continue
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) <= max(q_col, correct_col):
                continue
            q_text  = cells[q_col]
            correct = cells[correct_col]
            alts    = [cells[i] for i in alt_cols if i < len(cells) and cells[i]]
            if not q_text or not correct:
                continue
            all_opts = [correct] + alts
            opts = []
            for i, o in enumerate(all_opts):
                lbl = labels[i] if i < len(labels) else str(i+1)
                if not re.match(r'^[A-Ha-h]\s*[).]', o):
                    o = f"{lbl}) {o}"
                opts.append(o)
            questions.append({
                "type":"multiple_choice","question":q_text,"text":q_text,
                "options":opts,"correct":opts[0],"explanation":"","points":1,
                "_marked": True,
            })
    return questions


def _parse_docx_smart(path: str) -> list:
    """DOCX dan savollar - barcha formatlarni qo'llab-quvvatlaydi"""
    try:
        from docx import Document
        from docx.shared import RGBColor
        doc = Document(path)
    except Exception as e:
        log.warning(f"docx open: {e}")
        return _parse_docx_text(path)

    # FORMAT 1: Ko'p ustunli jadval (Ona tili formati)
    multicol = [t for t in doc.tables if len(t.columns) >= 4]
    if multicol:
        q = _parse_multicol_docx(multicol)
        if q:
            return q

    # FORMAT 2: 1-2 ustunli jadvallar (==== + # + +++++)
    single_col = [t for t in doc.tables if 1 <= len(t.columns) <= 2]
    if single_col:
        lines = []
        for t in single_col:
            for row in t.rows:
                lines.append(row.cells[0].text.strip())
            lines.append("+++++")
        if _is_zip_format(lines):
            q = _parse_equals_hash(lines)
            if q:
                return q

    # FORMAT 3: Paragraflar - ==== + # + +++++
    para_lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if _is_zip_format(para_lines):
        q = _parse_equals_hash(para_lines)
        if q:
            return q

    # FORMAT 4: Rang/marker bilan (mavjud logika davomi)
    try:
        from docx import Document
        from docx.shared import RGBColor
        doc = Document(path)
    except Exception as e:
        log.warning(f"docx open: {e}")
        return _parse_docx_text(path)

    questions = []
    current_q = None
    current_opts = []
    current_corr = None
    current_expl = ""
    current_photo = None
    q_num = 0

    def _is_correct_para(para):
        """Paragraf to'g'ri javobmi? Rang/qalinlik tekshirish"""
        full_text = para.text.strip()
        # 1. Marker bilan: * + ===
        is_c, _ = _is_correct_marker(full_text)
        if is_c:
            return True
        # 2. Qizil yoki yashil rang
        for run in para.runs:
            if run.font.color and run.font.color.type:
                try:
                    rgb = run.font.color.rgb
                    r, g, b = rgb.red, rgb.green, rgb.blue
                    # Yashil (to'g'ri)
                    if g > 150 and r < 100 and b < 100:
                        return True
                    # Qizil (ba'zi formatlarda to'g'ri)
                    if r > 150 and g < 100 and b < 100:
                        return True
                except Exception:
                    pass
        # 3. Qalin (bold) - faqat variant qatori bo'lsa
        for run in para.runs:
            if run.bold and re.match(r'^[A-Za-z0-9А-Яа-я]\s*[).\s]', full_text):
                return True
        return False

    def flush():
        nonlocal current_q, current_opts, current_corr, current_expl, current_photo, q_num
        if current_q and current_opts and current_corr:
            q = _build_question(current_q, current_opts, current_corr,
                                current_expl, current_photo)
            if q:
                questions.append(q)
        current_q = None
        current_opts = []
        current_corr = None
        current_expl = ""
        current_photo = None

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # Savol boshi: raqam bilan
        q_match = re.match(r'^(\d+)\s*[.)]\s*(.+)', text)
        if q_match:
            flush()
            q_num += 1
            current_q = q_match.group(2).strip()
            continue

        # Variant qatori
        if current_q is not None:
            is_opt = re.match(r'^([A-Za-zA-Яа-яёЁ*+])\s*[).]\s*(.+)', text)
            if is_opt or re.match(r'^[*+===]', text):
                is_corr = _is_correct_para(para)
                is_c_marker, cleaned = _is_correct_marker(text)
                if is_c_marker:
                    is_corr = True
                    opt_text = cleaned
                else:
                    opt_text = text

                current_opts.append(opt_text)
                if is_corr and current_corr is None:
                    current_corr = opt_text
                continue

            # Izoh
            if text.lower().startswith("izoh:"):
                current_expl = text.split(":", 1)[1].strip()
                continue

    flush()

    if not questions:
        return _parse_docx_text(path)
    return questions


def _parse_docx_text(path: str) -> list:
    """DOCX dan faqat matn olib parse qilish"""
    try:
        from docx import Document
        doc = Document(path)
        text = "\n".join(p.text for p in doc.paragraphs)
        return parse_text(text)
    except Exception as e:
        log.error(f"docx_text: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# UNIVERSAL TEXT PARSER
# ══════════════════════════════════════════════════════════════

def parse_text(text: str) -> list:
    """Universal parser - formatni avtomatik aniqlaydi"""
    if not text or not text.strip():
        return []

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Format aniqlash
    fmt = _detect_format(text)
    log.info(f"Parser format aniqlandi: {fmt}")

    if fmt == "tab_separated":
        return _parse_tab(text)
    elif fmt == "csv_like":
        return _parse_csv(text)
    elif fmt == "inline":
        return _parse_inline(text)
    elif fmt == "arrow":
        return _parse_arrow(text)
    else:
        return _parse_blocks(text)



def _merge_numbered_options(blocks: list) -> list:
    """
    1. Savol?
    1) Xato
    *2) To'g'ri
    kabi formatda savol va variantlar xato ajratilgan bo'lsa birlashtirish
    """
    if not blocks:
        return blocks
    
    result = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        lines = block.split("\n")
        
        # Bu blok savol boshi, lekin keyingi bloklar variant bo'lishi mumkin
        # Agar bu blokda variant yo'q va keyingisi 1) 2) 3) ko'rinishda bo'lsa
        has_opts = any(_match_option(l.strip()) for l in lines[1:] if l.strip())
        
        if not has_opts and i + 1 < len(blocks):
            # Keyingi bloklarda raqamli variantlar bormi?
            merged_lines = list(lines)
            j = i + 1
            while j < len(blocks):
                next_lines = blocks[j].split("\n")
                # Keyingi blok variant ko'rinishida
                first_line = next_lines[0].strip()
                if re.match(r'^[*+]?\d+[).\s]', first_line):
                    merged_lines.extend(next_lines)
                    j += 1
                else:
                    break
            
            if j > i + 1:
                # Birlashtirildi
                result.append("\n".join(merged_lines))
                i = j
                continue
        
        result.append(block)
        i += 1
    
    return result


def _detect_format(text: str) -> str:
    """Matn formatini aniqlash"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Tab-separated
    tab_lines = sum(1 for l in lines if "\t" in l)
    if tab_lines > len(lines) * 0.3:
        return "tab_separated"

    # CSV-like
    csv_lines = sum(1 for l in lines if l.count('"') >= 4 or l.count(';') >= 3)
    if csv_lines > len(lines) * 0.2:
        return "csv_like"

    # Arrow format: Savol → Javob
    arrow_lines = sum(1 for l in lines if '→' in l or '->' in l)
    if arrow_lines > len(lines) * 0.3:
        return "arrow"

    # Inline: 1.Savol? a)Var b)*Var
    inline = sum(1 for l in lines if re.search(r'\d+[.)].+[a-dA-D][).]', l))
    if inline > len(lines) * 0.2:
        return "inline"

    return "blocks"


# ══════════════════════════════════════════════════════════════
# BLOK PARSER (asosiy)
# ══════════════════════════════════════════════════════════════

def _parse_blocks(text: str) -> list:
    """Blok asosidagi universal parser"""
    # Savol boshlarini topish - ko'p variant
    patterns = [
        r"\n(?=\d+[.)]\s*\S)",           # 1. yoki 1)
        r"\n(?=\d+\s+[A-ZА-Я])",         # 1 Savol
        r"\n(?=Savol\s*\d+)",             # Savol 1
        r"\n(?=Q\d+[.):]\s*)",            # Q1: Q1.
        r"\n(?=#{1,3}\s)",                # ## Markdown
    ]

    blocks = None
    for pat in patterns:
        parts = re.split(pat, "\n" + text.strip())
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > 1:
            # Agar savollar ichida raqamli variantlar bo'lsa birlashtirish
            merged = _merge_numbered_options(parts)
            blocks = merged
            break

    if not blocks:
        # Ikki bo'sh qator bilan ajratilgan
        blocks = [b.strip() for b in re.split(r"\n\s*\n\s*\n", text) if b.strip()]
        if len(blocks) <= 1:
            blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]

    results = []
    for block in blocks:
        q = _parse_single_block(block)
        if q:
            results.append(q)

    return results


def _parse_single_block(block: str) -> dict | None:
    """Bitta blokni parse qilish - har xil formatni taniydi"""
    lines = [l.rstrip() for l in block.split("\n") if l.strip()]
    if not lines:
        return None

    # TYPE: ko'rsatmasi
    forced_type = None
    if lines[0].upper().startswith("TYPE:"):
        forced_type = lines[0].split(":", 1)[1].strip().lower()
        lines = lines[1:]
    if not lines:
        return None

    # Markdown header
    if lines[0].startswith("#"):
        lines[0] = re.sub(r'^#+\s*', '', lines[0])

    # Savol raqamini olib tashlash
    q_text = re.sub(r'^[Qq]?\d+\s*[.):\-]\s*', '', lines[0]).strip()
    if not q_text:
        return None

    # [rasm: file_id]
    photo_id = None
    pm = re.match(r'^\[rasm:\s*([^\]]+)\]\s*', q_text)
    if pm:
        photo_id = pm.group(1).strip()
        q_text = q_text[pm.end():].strip()

    opts = []
    corr = None
    expl = ""
    javob = None
    corr_num = None  # "To'g'ri: 2" formati uchun
    acc = []

    for line in lines[1:]:
        ls = line.strip()
        if not ls:
            continue

        # [rasm: ...]
        if ls.lower().startswith("[rasm:") and ls.endswith("]"):
            photo_id = ls[6:-1].strip()
            continue

        # Izoh/Explanation
        if re.match(r'^(izoh|explanation|exp|tafsir)\s*:', ls, re.I):
            expl = ls.split(":", 1)[1].strip()
            continue

        # Qabul/Accepted
        if re.match(r'^(qabul|accepted|variant)\s*:', ls, re.I):
            acc = [a.strip() for a in re.split(r'[,;]', ls.split(':', 1)[1]) if a.strip()]
            continue

        # Javob: qatori
        if re.match(r'^(javob|answer|ans|to.g.ri\s*javob)\s*:', ls, re.I):
            javob = ls.split(":", 1)[1].strip()
            continue

        # "To'g'ri: 2" yoki "Correct: B" formati
        if re.match(r'^(to.g.ri|correct|right)\s*:\s*\S', ls, re.I):
            val = ls.split(":", 1)[1].strip()
            if val.isdigit():
                corr_num = int(val) - 1  # 0-indexed
            else:
                corr_num = val
            continue

        # ** bold ** - to'g'ri javob
        bold_m = re.match(r'^\*\*(.+)\*\*$', ls)
        if bold_m:
            opt_text = bold_m.group(1).strip()
            # Variant formatidan tozalash
            opt_text = re.sub(r'^[A-Za-z0-9]\s*[).]\s*', '', opt_text)
            opts.append(opt_text)
            if corr is None:
                corr = opt_text
            continue

        # [To'g'ri javob] - bracket
        bracket_m = re.match(r'^\[(.+)\]$', ls)
        if bracket_m and not ls.startswith("[rasm"):
            opt_text = bracket_m.group(1).strip()
            opt_text = re.sub(r'^[A-Za-z0-9]\s*[).]\s*', '', opt_text)
            opts.append(opt_text)
            if corr is None:
                corr = opt_text
            continue

        # To'g'ri javob belgilari: * + ===
        is_c, cleaned = _is_correct_marker(ls)
        if is_c:
            # Variant raqamini tozalash
            cleaned = re.sub(r'^[A-Za-zA-Яа-яёЁ0-9]\s*[).]\s*', '', cleaned).strip()
            opts.append(cleaned)
            if corr is None:
                corr = cleaned
            continue

        # Variant satrlari - ko'p format
        opt_match = _match_option(ls)
        if opt_match:
            opt_clean = opt_match
            # To'g'ri javob belgisi variantda
            if ls.lstrip().startswith('*') or ls.lstrip().startswith('+'):
                if corr is None:
                    corr = opt_clean
            opts.append(opt_clean)
            continue

        # Dash yoki bullet - variant
        if re.match(r'^[-•·]\s+\S', ls):
            raw_opt = ls[1:].strip() if ls.startswith('-') else ls[2:].strip()
            is_c2, cleaned2 = _is_correct_marker(raw_opt)
            opt_clean = cleaned2.strip()
            if opt_clean:
                opts.append(opt_clean)
                if is_c2 and corr is None:
                    corr = opt_clean
            continue

    # corr_num ishlatish
    if corr_num is not None and opts:
        if isinstance(corr_num, int) and 0 <= corr_num < len(opts):
            corr = opts[corr_num]
        elif isinstance(corr_num, str):
            # Harf: A, B, C, D
            idx = ord(corr_num.upper()) - ord('A')
            if 0 <= idx < len(opts):
                corr = opts[idx]
            else:
                # Matn sifatida qidirish
                for o in opts:
                    if corr_num.lower() in o.lower():
                        corr = o
                        break

    # Tur aniqlash
    if forced_type:
        qtype = forced_type
    elif javob is not None:
        jl = (javob or "").lower().strip()
        if jl in ("ha", "yo'q", "yoq", "true", "false", "yes", "no",
                  "ha'", "to'g'ri", "noto'g'ri", "ха", "нет"):
            qtype = "true_false"
            corr = "Ha" if jl in ("ha", "ha'", "true", "yes", "to'g'ri", "ха") else "Yo'q"
        else:
            qtype = "fill_blank"
            corr = corr or javob
    elif opts:
        qtype = "multiple_choice"
    else:
        qtype = "text_input"

    # Agar opts bor, corr yo'q - birinchini olmaymiz (xato bo'ladi)
    if qtype == "multiple_choice" and corr is None:
        # Hech qanday belgi yo'q, birinchini to'g'ri deb qabul qilmaymiz
        # Faqat agar faqat 2 ta variant bo'lsa (True/False)
        if len(opts) == 2:
            qtype = "true_false"
            corr = opts[0]
        else:
            log.warning(f"To'g'ri javob belgilanmagan: {q_text[:50]}")
            # Birinchisini to'g'ri deymiz (hech bo'lmaganda)
            corr = opts[0] if opts else ""

    if not q_text:
        return None

    return _build_question(q_text, opts, corr, expl, photo_id, acc, qtype)


def _match_option(line: str) -> str | None:
    """Variant qatorini aniqlash va matnini qaytarish"""
    patterns = [
        r'^[A-Ha-hА-ЗА-За-з]\s*[).](.+)',        # A) A. gacha H
        r'^\(([A-Ha-h])\)\s*(.+)',               # (A) format
        r'^\[([A-Ha-h])\]\s*(.+)',               # [A] format
        r'^([1-9][0-9]?)\s*[).]\s*(.+)',         # 1) 2) 3. raqamli variant
    ]
    for pat in patterns:
        m = re.match(pat, line)
        if m:
            if len(m.groups()) == 1:
                return m.group(1).strip()
            else:
                return m.group(m.lastindex).strip()
    return None


def _is_correct_marker(line: str) -> tuple:
    """To'g'ri javob belgisini tekshiradi"""
    ls = line.strip()
    # === (eski format)
    if ls.startswith("==="):
        return True, ls[3:].strip()
    # * yoki + (yangi)
    if re.match(r'^[*+]\s*[A-Za-zA-Яа-яёЁ0-9([]', ls):
        return True, ls[1:].strip()
    # *** (markdown bold)
    if re.match(r'^\*{2,3}[^*]', ls):
        inner = re.sub(r'^\*+', '', ls).replace('***', '').replace('**', '').strip()
        return True, inner
    return False, ls


def _build_question(q_text, opts, corr, expl="", photo=None, acc=None, qtype=None):
    """Question dict yasash"""
    if not qtype:
        if opts:
            qtype = "multiple_choice"
        elif corr:
            qtype = "fill_blank"
        else:
            qtype = "text_input"

    # opts tozalash
    clean_opts = []
    for o in opts:
        o = re.sub(r'^[*+===]+\s*', '', o).strip()
        o = re.sub(r'^\*\*|\*\*$', '', o).strip()
        if o:
            clean_opts.append(o)

    # corr tozalash
    if corr:
        corr = re.sub(r'^[*+===]+\s*', '', corr).strip()
        corr = re.sub(r'^\*\*|\*\*$', '', corr).strip()

    result = {
        "type":             qtype,
        "question":         q_text,
        "options":          clean_opts if qtype in ("multiple_choice", "multi_select") else [],
        "correct":          corr or "",
        "explanation":      expl or "",
        "accepted_answers": acc or [],
        "points":           1,
    }
    if photo:
        result["photo"] = photo
    return result


# ══════════════════════════════════════════════════════════════
# MAXSUS FORMATLAR
# ══════════════════════════════════════════════════════════════

def _parse_tab(text: str) -> list:
    """Tab-separated format: Savol\tA\tB\t*C\tD"""
    results = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3:
            continue
        q_text = re.sub(r'^\d+[.)]\s*', '', parts[0]).strip()
        opts_raw = parts[1:]
        opts = []
        corr = None
        for o in opts_raw:
            if not o:
                continue
            is_c, cleaned = _is_correct_marker(o)
            opt_clean = re.sub(r'^[A-Ha-h]\s*[).]\s*', '', cleaned).strip()
            if opt_clean:
                opts.append(opt_clean)
                if is_c and corr is None:
                    corr = opt_clean
        if q_text and opts and corr:
            results.append(_build_question(q_text, opts, corr))
    return results


def _parse_csv(text: str) -> list:
    """CSV-like: "Savol","A","B","*C","D" yoki ; bilan ajratilgan"""
    import csv, io
    results = []
    # Ajratuvchini topish
    sep = ";" if text.count(";") > text.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=sep)
    for row in reader:
        row = [c.strip().strip('"') for c in row]
        if len(row) < 3:
            continue
        q_text = re.sub(r'^\d+[.)]\s*', '', row[0]).strip()
        opts_raw = row[1:]
        opts = []
        corr = None
        for o in opts_raw:
            if not o:
                continue
            is_c, cleaned = _is_correct_marker(o)
            opt_clean = re.sub(r'^[A-Ha-h]\s*[).]\s*', '', cleaned).strip()
            if opt_clean:
                opts.append(opt_clean)
                if is_c and corr is None:
                    corr = opt_clean
        if q_text and opts and corr:
            results.append(_build_question(q_text, opts, corr))
    return results


def _parse_inline(text: str) -> list:
    """Inline: 1. Savol? a) Var b)*To'g'ri c) Var"""
    results = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Savol qismi
        q_m = re.match(r'^(?:\d+[.)]\s*)(.+?)(?=[a-dA-D]\s*[).])', line)
        if not q_m:
            continue
        q_text = q_m.group(1).strip().rstrip("?").strip() + "?"
        # Variantlar
        parts = re.findall(r'([a-dA-D])\s*[).]\s*([^a-dA-D)]+?)(?=[a-dA-D]\s*[).]|$)', line)
        opts = []
        corr = None
        for ltr, val in parts:
            v = val.strip()
            is_c, cleaned = _is_correct_marker(v)
            if not is_c:
                is_c = v.startswith('*') or v.startswith('+')
                cleaned = v.lstrip('*+ ').strip()
            if cleaned:
                opts.append(cleaned)
                if is_c and corr is None:
                    corr = cleaned
        if q_text and opts and corr:
            results.append(_build_question(q_text, opts, corr))
    return results


def _parse_arrow(text: str) -> list:
    """Arrow: Savol → To'g'ri javob yoki Savol -> Javob"""
    results = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for sep in ['→', '->']:
            if sep in line:
                parts = line.split(sep, 1)
                q_text = re.sub(r'^\d+[.)]\s*', '', parts[0]).strip()
                corr   = parts[1].strip()
                if q_text and corr:
                    results.append(_build_question(q_text, [], corr,
                                                   qtype="fill_blank"))
                break
    return results
