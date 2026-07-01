"""
📊 PREMIUM PDF REPORT — Test natijalari uchun elegant hisobot
reportlab asosida premium dizayn
"""
import io
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# ── Ranglar palitasi (premium dark-accent) ──────────────────────
C_BG_DARK    = colors.HexColor("#0F1923")   # sarlavha fon
C_ACCENT     = colors.HexColor("#2563EB")   # ko'k accent
C_ACCENT2    = colors.HexColor("#1E40AF")   # to'q ko'k
C_GOLD       = colors.HexColor("#F59E0B")   # oltin — top 3
C_GREEN      = colors.HexColor("#10B981")   # yashil — o'tdi
C_RED        = colors.HexColor("#EF4444")   # qizil — o'tmadi
C_ORANGE     = colors.HexColor("#F97316")   # to'q sariq
C_WHITE      = colors.white
C_LIGHT_GRAY = colors.HexColor("#F8FAFC")
C_BORDER     = colors.HexColor("#E2E8F0")
C_TEXT_DARK  = colors.HexColor("#1E293B")
C_TEXT_MID   = colors.HexColor("#475569")
C_TEXT_LIGHT = colors.HexColor("#94A3B8")
C_ROW_ALT    = colors.HexColor("#F1F5F9")
C_STARTED    = colors.HexColor("#FEF3C7")   # boshlagan (sariq ochiq)

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

# ── Shrift: DejaVuSans (Unicode, o'zbek/kirill to'liq qo'llab-quvvatlaydi) ──
import os as _os

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

def _register_fonts():
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans",     _FONT_PATHS[0]))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", _FONT_PATHS[1]))
        return "DejaVuSans", "DejaVuSans-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"

FONT_REG, FONT_BOLD = _register_fonts()

# ── Baholar tizimi ───────────────────────────────────────────────
def _grade(pct: float) -> tuple[str, object]:
    """(harf baho, rang)"""
    if pct >= 90:  return "A+", C_GREEN
    if pct >= 85:  return "A",  C_GREEN
    if pct >= 80:  return "A-", C_GREEN
    if pct >= 75:  return "B+", C_ACCENT
    if pct >= 70:  return "B",  C_ACCENT
    if pct >= 65:  return "B-", C_ACCENT
    if pct >= 60:  return "C+", C_ORANGE
    if pct >= 55:  return "C",  C_ORANGE
    if pct >= 50:  return "C-", C_ORANGE
    if pct >= 40:  return "D",  C_RED
    return "F", C_RED


def _rank_icon(rank: int) -> str:
    if rank == 1: return "1"
    if rank == 2: return "2"
    if rank == 3: return "3"
    return str(rank)


def generate_solvers_pdf(meta: dict, solvers: list, bot_name: str = "QuizMarkerBot") -> bytes:
    """
    PDF bayt qatori qaytaradi.
    solvers: get_all_solvers_for_test() natijalari
    """
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=16*mm, bottomMargin=16*mm,
        title=f"Test natijalari — {meta.get('title', '')}",
        author=bot_name,
    )

    story = []
    W = PAGE_W - 2 * MARGIN  # ishchi kenglik

    # ═══════════════════════════════════════════════════════════════
    # 1. HEADER BANNER
    # ═══════════════════════════════════════════════════════════════
    now_uz = datetime.now(timezone.utc).strftime("%d.%m.%Y  %H:%M UTC")
    test_title  = meta.get("title", "Nomsiz test")
    test_id     = meta.get("test_id", "")
    creator     = meta.get("creator_name") or meta.get("creator_username") or "Noma'lum"
    category    = meta.get("category") or "Umumiy"
    difficulty  = meta.get("difficulty", "medium")
    diff_labels = {"easy": "Oson", "medium": "O'rtacha", "hard": "Qiyin", "expert": "Ekspert"}
    diff_label  = diff_labels.get(difficulty, difficulty.capitalize())
    q_count     = meta.get("question_count", 0)
    pass_score  = meta.get("passing_score", 60)

    finished = [s for s in solvers if s.get("attempts", 0) > 0]
    started  = [s for s in solvers if s.get("attempts", 0) == 0]
    passed   = [s for s in finished if s.get("best_score", 0) >= pass_score]
    avg_best = (sum(s["best_score"] for s in finished) / len(finished)) if finished else 0

    # --- Header jadval (banner) ---
    header_data = [[
        Paragraph(
            f'<font name="{FONT_BOLD}" size="18" color="white">{_esc(test_title)}</font>',
            ParagraphStyle("hdr", fontName=FONT_BOLD, fontSize=18,
                           textColor=C_WHITE, alignment=TA_LEFT)
        ),
        Paragraph(
            f'<font name="{FONT_BOLD}" size="11" color="#93C5FD">{_esc(bot_name)}</font>',
            ParagraphStyle("bot", fontName=FONT_BOLD, fontSize=11,
                           textColor=colors.HexColor("#93C5FD"), alignment=TA_RIGHT)
        ),
    ]]
    ht = Table(header_data, colWidths=[W * 0.65, W * 0.35])
    ht.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), C_BG_DARK),
        ("LEFTPADDING",  (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING",   (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 14),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [6, 6, 0, 0]),
    ]))
    story.append(ht)

    # --- Sub-header: meta ma'lumotlar ---
    sub_data = [[
        Paragraph(f'<font name="{FONT_REG}" size="8.5" color="#94A3B8">'
                  f'Tuzgan: <b>{_esc(creator)}</b></font>',
                  _ps(8.5, C_TEXT_LIGHT)),
        Paragraph(f'<font name="{FONT_REG}" size="8.5" color="#94A3B8">'
                  f'Fan: <b>{_esc(category)}</b></font>',
                  _ps(8.5, C_TEXT_LIGHT, TA_CENTER)),
        Paragraph(f'<font name="{FONT_REG}" size="8.5" color="#94A3B8">'
                  f'Savollar: <b>{q_count} ta</b>  |  O\'tish: <b>{pass_score}%</b></font>',
                  _ps(8.5, C_TEXT_LIGHT, TA_CENTER)),
        Paragraph(f'<font name="{FONT_REG}" size="8.5" color="#94A3B8">'
                  f'{now_uz}</font>',
                  _ps(8.5, C_TEXT_LIGHT, TA_RIGHT)),
    ]]
    st = Table(sub_data, colWidths=[W*0.28, W*0.22, W*0.28, W*0.22])
    st.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#1E293B")),
        ("LEFTPADDING",  (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [0, 0, 6, 6]),
    ]))
    story.append(st)
    story.append(Spacer(1, 10))

    # ═══════════════════════════════════════════════════════════════
    # 2. STATISTIKA KARTALAR (4 ta)
    # ═══════════════════════════════════════════════════════════════
    def _stat_card(label, value, sub="", color=C_ACCENT):
        inner = [
            [Paragraph(f'<font name="{FONT_BOLD}" size="22">{_esc(str(value))}</font>',
                       _ps(22, color, TA_CENTER))],
            [Paragraph(f'<font name="{FONT_BOLD}" size="8">{_esc(label)}</font>',
                       _ps(8, C_TEXT_MID, TA_CENTER))],
        ]
        if sub:
            inner.append([Paragraph(f'<font name="{FONT_REG}" size="7">{_esc(sub)}</font>',
                                    _ps(7, C_TEXT_LIGHT, TA_CENTER))])
        t = Table(inner, colWidths=[W/4 - 6])
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), C_LIGHT_GRAY),
            ("BOX",          (0, 0), (-1, -1), 1, C_BORDER),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING",   (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    pass_rate = f"{round(len(passed)/len(finished)*100)}%" if finished else "0%"
    cards_row = [[
        _stat_card("JAMI ISHTIROKCHI", len(solvers),
                   f"{len(finished)} tugatdi / {len(started)} boshladi"),
        _stat_card("O'RTACHA BAL",     f"{round(avg_best, 1)}%",
                   "Eng yaxshi urinishlar bo'yicha", C_ACCENT),
        _stat_card("O'TDI",            len(passed),
                   pass_rate + " o'tish darajasi", C_GREEN),
        _stat_card("O'TMADI",          len(finished) - len(passed),
                   f"Chegara: {pass_score}%", C_RED),
    ]]
    cards_t = Table(cards_row, colWidths=[W/4]*4, hAlign="LEFT")
    cards_t.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(cards_t)
    story.append(Spacer(1, 12))

    # ═══════════════════════════════════════════════════════════════
    # 3. ASOSIY JADVAL — tugatganlar
    # ═══════════════════════════════════════════════════════════════
    if finished:
        story.append(_section_title("NATIJALAR REYTINGI", W))
        story.append(Spacer(1, 4))

        # Sarlavha qatori
        col_w = [10*mm, W*0.26, W*0.12, W*0.10, W*0.10, W*0.10, W*0.10, W*0.10]
        headers = ["#", "Ishtirokchi", "Urinish", "Eng yaxshi", "O'rtacha", "Foizlar", "Baho", "Holat"]
        hrow = [Paragraph(f'<font name="{FONT_BOLD}" size="8" color="white">{h}</font>',
                           _ps(8, C_WHITE, TA_CENTER)) for h in headers]

        table_data = [hrow]

        for rank, sv in enumerate(finished, 1):
            best   = float(sv.get("best_score", 0))
            avg    = float(sv.get("avg_score",  0))
            att    = sv.get("attempts", 0)
            pcts   = sv.get("all_pcts", [])
            grade, grade_color = _grade(best)
            passed_this = best >= pass_score

            # Rank belgisi
            rank_txt = _rank_icon(rank)

            # Urinishlar foizlari (qisqa)
            if len(pcts) <= 4:
                pcts_str = " → ".join(f"{p}%" for p in pcts)
            else:
                pcts_str = f"{pcts[0]}% ... {pcts[-1]}%\n({len(pcts)}x)"

            name = sv.get("name", f"User {sv['uid']}")
            uname = f"@{sv['username']}" if sv.get("username") else ""
            name_cell = Paragraph(
                f'<font name="{FONT_BOLD}" size="8">{_esc(name[:22])}</font>'
                + (f'<br/><font name="{FONT_REG}" size="7" color="#64748B">{_esc(uname)}</font>' if uname else ""),
                _ps(8, C_TEXT_DARK)
            )

            status_txt = "O'TDI" if passed_this else "O'TMADI"
            status_col = C_GREEN if passed_this else C_RED

            row = [
                Paragraph(f'<font name="{FONT_BOLD}" size="9">{rank_txt}</font>',
                           _ps(9, C_GOLD if rank <= 3 else C_TEXT_MID, TA_CENTER)),
                name_cell,
                Paragraph(f'<font name="{FONT_REG}" size="8">{att}x</font>',
                           _ps(8, C_TEXT_MID, TA_CENTER)),
                Paragraph(f'<font name="{FONT_BOLD}" size="9">{best}%</font>',
                           _ps(9, C_GREEN if best >= pass_score else C_RED, TA_CENTER)),
                Paragraph(f'<font name="{FONT_REG}" size="8">{round(avg,1)}%</font>',
                           _ps(8, C_TEXT_MID, TA_CENTER)),
                Paragraph(f'<font name="{FONT_REG}" size="7">{_esc(pcts_str)}</font>',
                           _ps(7, C_TEXT_MID, TA_CENTER)),
                Paragraph(f'<font name="{FONT_BOLD}" size="10">{grade}</font>',
                           _ps(10, grade_color, TA_CENTER)),
                Paragraph(f'<font name="{FONT_BOLD}" size="7">{status_txt}</font>',
                           _ps(7, status_col, TA_CENTER)),
            ]
            table_data.append(row)

        main_t = Table(table_data, colWidths=col_w, repeatRows=1)
        style = [
            # Header
            ("BACKGROUND",    (0, 0), (-1, 0), C_ACCENT2),
            ("TEXTCOLOR",     (0, 0), (-1, 0), C_WHITE),
            ("TOPPADDING",    (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("ALIGN",         (0, 0), (-1, 0), "CENTER"),
            # Rows
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_ROW_ALT]),
            ("TOPPADDING",    (0, 1), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("GRID",          (0, 0), (-1, -1), 0.3, C_BORDER),
            # Top 3 highlight
        ]
        # Top 3 chiziq
        for i in range(1, min(4, len(table_data))):
            style.append(("LEFTPADDING", (0, i), (0, i), 3))
            if i == 1:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFFBEB")))
            elif i == 2:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")))
            elif i == 3:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFF7F0")))

        main_t.setStyle(TableStyle(style))
        story.append(main_t)
        story.append(Spacer(1, 12))

    # ═══════════════════════════════════════════════════════════════
    # 4. FAQAT BOSHLAGAN (0-natija) jadval
    # ═══════════════════════════════════════════════════════════════
    if started:
        story.append(_section_title(f"FAQAT BOSHLAGAN — {len(started)} KISHI", W,
                                    color=C_ORANGE))
        story.append(Spacer(1, 4))

        col_w2 = [10*mm, W*0.45, W*0.30, W*0.15]
        hrow2 = [Paragraph(f'<font name="{FONT_BOLD}" size="8" color="white">{h}</font>',
                            _ps(8, C_WHITE, TA_CENTER))
                 for h in ["#", "Ishtirokchi", "Username", "Holat"]]
        tdata2 = [hrow2]
        for i, sv in enumerate(started, 1):
            name  = sv.get("name", f"User {sv['uid']}")
            uname = f"@{sv['username']}" if sv.get("username") else "—"
            tdata2.append([
                Paragraph(f'<font name="{FONT_REG}" size="8">{i}</font>',
                           _ps(8, C_TEXT_MID, TA_CENTER)),
                Paragraph(f'<font name="{FONT_REG}" size="8">{_esc(name[:30])}</font>',
                           _ps(8, C_TEXT_DARK)),
                Paragraph(f'<font name="{FONT_REG}" size="8">{_esc(uname)}</font>',
                           _ps(8, C_TEXT_MID, TA_CENTER)),
                Paragraph(f'<font name="{FONT_BOLD}" size="7">BOSHLADI</font>',
                           _ps(7, C_ORANGE, TA_CENTER)),
            ])
        t2 = Table(tdata2, colWidths=col_w2, repeatRows=1)
        t2.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#92400E")),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_STARTED, C_WHITE]),
            ("GRID",          (0, 0), (-1, -1), 0.3, C_BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(t2)
        story.append(Spacer(1, 12))

    # ═══════════════════════════════════════════════════════════════
    # 5. BAHO TIZIMI IZOH
    # ═══════════════════════════════════════════════════════════════
    story.append(_section_title("BAHOLASH TIZIMI", W, color=C_TEXT_MID))
    story.append(Spacer(1, 4))

    grades_info = [
        ("A+", "90–100%", C_GREEN),
        ("A",  "85–89%",  C_GREEN),
        ("A-", "80–84%",  C_GREEN),
        ("B+", "75–79%",  C_ACCENT),
        ("B",  "70–74%",  C_ACCENT),
        ("B-", "65–69%",  C_ACCENT),
        ("C+", "60–64%",  C_ORANGE),
        ("C",  "55–59%",  C_ORANGE),
        ("C-", "50–54%",  C_ORANGE),
        ("D",  "40–49%",  C_RED),
        ("F",  "0–39%",   C_RED),
    ]
    grade_cells = []
    for g, rng, gc in grades_info:
        grade_cells.append(
            Paragraph(
                f'<font name="{FONT_BOLD}" size="9">{g}</font>  '
                f'<font name="{FONT_REG}" size="7" color="#64748B">{rng}</font>',
                _ps(8, gc)
            )
        )
    # 6 ta ustun
    rows_g = []
    for i in range(0, len(grade_cells), 6):
        chunk = grade_cells[i:i+6]
        while len(chunk) < 6:
            chunk.append(Paragraph("", _ps(8, C_WHITE)))
        rows_g.append(chunk)
    gt = Table(rows_g, colWidths=[W/6]*6)
    gt.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), C_LIGHT_GRAY),
        ("GRID",         (0, 0), (-1, -1), 0.3, C_BORDER),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(gt)
    story.append(Spacer(1, 14))

    # ═══════════════════════════════════════════════════════════════
    # 6. FOOTER
    # ═══════════════════════════════════════════════════════════════
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 5))
    footer_data = [[
        Paragraph(
            f'<font name="{FONT_REG}" size="7" color="#94A3B8">'
            f'Test ID: <b>{_esc(test_id)}</b>  |  Yaratilgan: <b>{_esc(bot_name)}</b></font>',
            _ps(7, C_TEXT_LIGHT)
        ),
        Paragraph(
            f'<font name="{FONT_REG}" size="7" color="#94A3B8">'
            f'Hisobot sanasi: {now_uz}</font>',
            _ps(7, C_TEXT_LIGHT, TA_RIGHT)
        ),
    ]]
    ft = Table(footer_data, colWidths=[W*0.6, W*0.4])
    ft.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(ft)

    # ─── Build ──────────────────────────────────────────────────
    doc.build(story, onFirstPage=_page_decorator, onLaterPages=_page_decorator)
    return buf.getvalue()


# ── Yordamchi funksiyalar ────────────────────────────────────────

def _esc(txt: str) -> str:
    """ReportLab XML uchun maxsus belgilarni escape qilish"""
    return (str(txt)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("'", "&#39;"))


def _ps(size, color=None, align=TA_LEFT):
    return ParagraphStyle(
        f"s{size}",
        fontName=FONT_REG,
        fontSize=size,
        leading=size * 1.3,
        textColor=color or C_TEXT_DARK,
        alignment=align,
    )


def _section_title(text: str, width: float, color=C_ACCENT2):
    data = [[
        Paragraph(
            f'<font name="{FONT_BOLD}" size="9" color="white">{_esc(text)}</font>',
            ParagraphStyle("sec", fontName=FONT_BOLD, fontSize=9,
                           textColor=C_WHITE, alignment=TA_LEFT)
        )
    ]]
    t = Table(data, colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), color),
        ("LEFTPADDING",  (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
    ]))
    return t


def _page_decorator(canvas, doc):
    """Har sahifada sahifa raqami"""
    canvas.saveState()
    canvas.setFont(FONT_REG, 7)
    canvas.setFillColor(C_TEXT_LIGHT)
    canvas.drawRightString(
        PAGE_W - MARGIN, 8 * mm,
        f"Sahifa {doc.page}"
    )
    canvas.restoreState()
