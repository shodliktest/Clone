"""
📄 PARSER — TXT/PDF/DOCX fayllardan savollar ajratish

TO'G'RI JAVOB BELGILASH USULLARI:
  *A) Toshkent      ← yulduzcha oldida (yangi)
  +A) Toshkent      ← plus oldida (yangi)
  ===A) Toshkent    ← uch tenglik (eski, qo'llab-quvvatlanadi)

MISOL:
  1. O'zbekiston poytaxti?
  *A) Toshkent
  B) Samarqand
  C) Buxoro

  TYPE: true_false
  2. Yer yumaloqmi?
  Javob: Ha

  TYPE: fill_blank
  3. Pi = ___
  Javob: 3.14
  Qabul: 3.141, 3.14159
"""
import re, logging
from pathlib import Path

log = logging.getLogger(__name__)


def parse_file(path: str) -> list:
    ext = Path(path).suffix.lower()
    try:
        if ext == ".txt":
            text = _read_txt(path)
        elif ext == ".pdf":
            text = _read_pdf(path)
        elif ext in (".docx", ".doc"):
            text = _read_docx(path)
        else:
            return []
        return parse_text(text)
    except Exception as e:
        log.error(f"Parser xato: {e}")
        return []


def _read_txt(path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            pass
    return ""


def _read_pdf(path: str) -> str:
    import pdfplumber
    pages = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            t = p.extract_text()
            if t:
                pages.append(t)
    return "\n".join(pages)


def _read_docx(path: str) -> str:
    from docx import Document
    return "\n".join(p.text for p in Document(path).paragraphs)


def parse_text(text: str) -> list:
    text   = text.replace("\r\n", "\n")
    # Savol boshlarini topish: 1. yoki 1)
    blocks = re.split(r"\n(?=\d+[\.)]\s*\S)", "\n" + text.strip())
    result = []
    for b in blocks:
        q = _parse_block(b.strip())
        if q:
            result.append(q)
    return result


def _is_correct_marker(line: str) -> tuple[bool, str]:
    """
    To'g'ri javob belgisini tekshiradi.
    Qaytaradi: (is_correct, cleaned_option)

    Qo'llab-quvvatlanadigan formatlar:
      *A) Matn       → yulduzcha oldida
      +A) Matn       → plus oldida
      ===A) Matn     → uch tenglik oldida
      * A) Matn      → yulduzcha + bo'sh joy
      + A) Matn      → plus + bo'sh joy
    """
    ls = line.strip()

    # === (eski format)
    if ls.startswith("==="):
        return True, ls[3:].strip()

    # * yoki + (yangi format) — harf yoki raqam bilan davom etishi kerak
    if re.match(r"^[*+]\s*[A-Za-zA-Яа-яёЁ0-9]", ls):
        return True, ls[1:].strip()

    return False, ls


def _parse_block(block: str) -> dict | None:
    lines  = [l.rstrip() for l in block.split("\n") if l.strip()]
    if not lines:
        return None

    # TYPE: ko'rsatmasi
    forced = None
    if lines[0].upper().startswith("TYPE:"):
        forced = lines[0].split(":", 1)[1].strip().lower()
        lines  = lines[1:]
    if not lines:
        return None

    # Savol matni (1. yoki 1) ni olib tashlaymiz)
    q_text = re.sub(r"^\d+[\.)]\s*", "", lines[0]).strip()
    if not q_text:
        return None

    opts     = []
    corr     = None
    expl     = ""
    javob    = None
    acc      = []
    photo_id = None

    # Savol matni ichida [rasm: file_id] bor-yo'qligini tekshirish
    pm_match = re.match(r'^\[rasm:\s*([^\]]+)\]\s*', q_text)
    if pm_match:
        photo_id = pm_match.group(1).strip()
        q_text   = q_text[pm_match.end():].strip()

    for line in lines[1:]:
        ls = line.strip()
        if not ls:
            continue

        # [rasm: file_id] — alohida qatorda
        if ls.startswith("[rasm:") and ls.endswith("]"):
            photo_id = ls[6:-1].strip()
            continue

        # Izoh
        if ls.lower().startswith("izoh:"):
            expl = ls.split(":", 1)[1].strip()
            continue

        # Qabul qilinadigan javoblar
        if re.match(r"^(qabul|accepted)\s*:", ls, re.IGNORECASE):
            acc = [a.strip() for a in re.split(r"[,;]", ls.split(":", 1)[1]) if a.strip()]
            continue

        # Javob:
        if ls.lower().startswith("javob:"):
            javob = ls.split(":", 1)[1].strip()
            continue

        # To'g'ri javob belgisini tekshirish
        is_correct, cleaned = _is_correct_marker(ls)

        if is_correct:
            opts.append(cleaned)
            corr = cleaned
            continue

        # Oddiy variant: harf yoki raqam bilan boshlanadi
        if re.match(r"^[A-Za-zA-Яа-яёЁ0-9]\s*[\).]\s*", ls):
            opts.append(ls)
            continue

        # Variant bo'lmasa ham opts ga qo'shamiz (agar boshqa format)
        # (masalan faqat matn, raqamsiz)

    # Tur aniqlash
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

    # To'g'ri javobni yakunlashtirish
    if qtype == "true_false":
        corr = "Ha" if (javob or "").lower().strip() in ("ha", "true", "yes") else "Yo'q"
    elif qtype in ("text_input", "fill_blank"):
        corr = javob or corr or ""
    elif corr is None and opts:
        corr = opts[0]  # Birinchi variant to'g'ri (agar belgilanmagan bo'lsa)

    # Variant matnlarini tozalash (A) yoki A. ni qoldiramiz)
    clean_opts = []
    for opt in opts:
        # Agar * yoki + qolgan bo'lsa tozalaymiz
        o = re.sub(r"^[*+]\s*", "", opt).strip()
        clean_opts.append(o)

    # corr ham tozalansin
    if corr:
        corr = re.sub(r"^[*+]\s*", "", corr).strip()
        corr = re.sub(r"^===\s*", "", corr).strip()

    result = {
        "type":             qtype,
        "question":         q_text,
        "options":          clean_opts if qtype in ("multiple_choice", "multi_select") else [],
        "correct":          corr or "",
        "explanation":      expl,
        "accepted_answers": acc,
        "points":           1,
    }
    if photo_id:
        result["photo"] = photo_id
    return result
