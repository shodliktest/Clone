"""
Leaderboard Card — sodda, ishonchli, DejaVu shrift
"""
import io, asyncio, logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Shrift qidirish: Noto (packages.txt) → DejaVu (default) → fallback
def _find_font(bold=False):
    import os
    candidates_bold = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-ExtraBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSans-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    candidates_reg = [
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSans-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in (candidates_bold if bold else candidates_reg):
        if os.path.exists(path):
            return path
    return None

FB = _find_font(bold=True)  or "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = _find_font(bold=False) or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

BG   = (18, 20, 40)
CARD = (26, 29, 54)
ACC  = (100, 105, 220)
WHT  = (255, 255, 255)
GRY  = (136, 144, 176)
GRN  = (60, 210, 140)
YLW  = (249, 190, 40)
RED  = (240, 90, 90)
BBG  = (40, 44, 75)
BRD  = (45, 50, 85)
M    = [(255,190,50),(160,170,200),(200,130,60)]

def _f(size, bold=False):
    from PIL import ImageFont
    try: return ImageFont.truetype(FB if bold else FR, size)
    except: return ImageFont.load_default()

def _col(p, ps):
    return GRN if p >= ps else (YLW if p >= ps*0.7 else RED)

def _tw(draw, t, f):
    b = draw.textbbox((0,0), t, font=f); return b[2]-b[0]

def _th(draw, t, f):
    b = draw.textbbox((0,0), t, font=f); return b[3]-b[1]

def _clean_name(name: str, max_len: int) -> str:
    """Emoji, maxsus Unicode (𒐫 kabi), nazorat belgilarini olib tashlaydi, keyin qisqartiradi."""
    import unicodedata
    result = []
    for ch in name:
        cat = unicodedata.category(ch)
        if cat.startswith(('L', 'N', 'P', 'Z')) and ord(ch) < 0x10000:
            result.append(ch)
    cleaned = ''.join(result).strip()
    if not cleaned:
        cleaned = "NoName"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "…"
    return cleaned

def generate_leaderboard_image(
    quiz_title, results, passing_score=60.0, total_questions=0
):
    if not results: return None
    try:
        from PIL import Image, ImageDraw

        W   = 900
        PAD = 30
        GAP = 8

        top3 = results[:3]
        rest = results[3:15]
        avg  = sum(r["score"] for r in results)/len(results)
        passed = sum(1 for r in results if r["score"] >= passing_score)
        n = len(results)

        # Balandlikni hisoblash
        H = (PAD + 110 + GAP +   # header
             36 + GAP +           # stats
             2  + GAP +           # divider
             len(top3)*(90+GAP) + # top3
             (28+GAP if rest else 0) +
             len(rest)*(62+GAP) + # rest
             2  + GAP +           # footer divider
             44 + PAD)            # footer

        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        y    = PAD

        # ── HEADER ──
        R = 30
        cx, cy = PAD+R, y+55
        draw.ellipse([cx-R,cy-R,cx+R,cy+R], fill=ACC, outline=WHT, width=2)
        draw.text((cx,cy), "#", font=_f(22,True), fill=WHT, anchor="mm")

        title = (quiz_title[:30]+"…") if len(quiz_title)>31 else quiz_title
        draw.text((cx+R+14, cy-18), title, font=_f(32,True), fill=WHT)
        y += 110 + GAP

        # ── STATS ──
        sx = PAD
        for txt, col in [
            (f"{n} ishtirokchi", WHT),
            (f"{passed} o'tdi ({passed*100//n if n else 0}%)", GRN),
            (f"O'rtacha: {avg:.0f}%", GRY),
        ]:
            f0 = _f(18)
            draw.text((sx, y+4), txt, font=f0, fill=col)
            sx += _tw(draw, txt, f0) + 24
        y += 36 + GAP

        # ── DIVIDER ──
        draw.rectangle([PAD, y, W-PAD, y+2], fill=ACC)
        y += 2 + GAP

        # ── TOP 3 ──
        for i, r in enumerate(top3):
            pct  = r["score"]
            cor  = r["correct"]
            tot  = r["total"] or total_questions or 1
            name = _clean_name(r.get("first_name") or r.get("username") or "?", 25)
            bc   = M[i]
            col  = _col(pct, passing_score)
            H3   = 90

            draw.rectangle([PAD, y, W-PAD, y+H3], fill=CARD, outline=bc, width=2)

            # Rank doira
            rcx, rcy = PAD+40, y+H3//2
            draw.ellipse([rcx-22,rcy-22,rcx+22,rcy+22], fill=bc)
            draw.text((rcx,rcy), str(i+1), font=_f(20,True), fill=BG, anchor="mm")

            nx = rcx + 34
            ny = y + 14

            # Foiz
            fp     = _f(28,True)
            pt     = f"{pct:.0f}%"
            pw     = _tw(draw, pt, fp)
            px     = W - PAD - 14 - pw
            draw.text((px, ny), pt, font=fp, fill=col)

            # correct/total
            fi  = _f(18)
            it  = f"{cor}/{tot}"
            iw  = _tw(draw, it, fi)
            draw.text((px - iw - 14, ny+5), it, font=fi, fill=GRY)

            # Ism
            draw.text((nx, ny), name, font=_f(22,True), fill=WHT)

            # Bar
            bx0, bx1 = nx, W-PAD-14
            by = ny + 38
            draw.rectangle([bx0, by, bx1, by+8], fill=BBG)
            fw = int((bx1-bx0)*pct/100)
            if fw > 4:
                draw.rectangle([bx0, by, bx0+fw, by+8], fill=col)

            y += H3 + GAP

        # ── QOLGANLAR ──
        if rest:
            draw.text((PAD, y+4), f"Qolgan {len(rest)} ishtirokchi:",
                      font=_f(17), fill=GRY)
            y += 28 + GAP

            for i, r in enumerate(rest):
                rank = i+4
                pct  = r["score"]
                cor  = r["correct"]
                tot  = r["total"] or total_questions or 1
                name = _clean_name(r.get("first_name") or r.get("username") or "?", 27)
                col  = _col(pct, passing_score)
                HR   = 62

                draw.rectangle([PAD, y, W-PAD, y+HR], fill=CARD, outline=BRD, width=1)

                nx = PAD + 46
                ny = y + 10

                draw.text((PAD+12, ny+2), f"{rank}.", font=_f(16), fill=GRY)

                fp  = _f(22,True)
                pt  = f"{pct:.0f}%"
                pw  = _tw(draw, pt, fp)
                px  = W - PAD - 14 - pw
                draw.text((px, ny+2), pt, font=fp, fill=col)

                fi  = _f(17)
                it  = f"{cor}/{tot}"
                iw  = _tw(draw, it, fi)
                draw.text((px-iw-12, ny+4), it, font=fi, fill=GRY)

                draw.text((nx, ny), name, font=_f(20,True), fill=WHT)

                bx0, bx1 = nx, W-PAD-14
                by = ny + 30
                draw.rectangle([bx0, by, bx1, by+7], fill=BBG)
                fw = int((bx1-bx0)*pct/100)
                if fw > 4:
                    draw.rectangle([bx0, by, bx0+fw, by+7], fill=col)

                y += HR + GAP

        # ── FOOTER ──
        draw.rectangle([PAD, y, W-PAD, y+1], fill=BRD)
        y += 1 + GAP
        ff  = _f(17)
        draw.text((PAD, y+10), f"O'tish bali: {passing_score:.0f}%", font=ff, fill=GRY)
        tq  = f"{total_questions} ta savol"
        draw.text((W-PAD-_tw(draw,tq,ff), y+10), tq, font=ff, fill=GRY)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Leaderboard xato: {e}")
        import traceback; traceback.print_exc()
        return None


async def send_leaderboard_card(
    bot, chat_id, quiz_title, results,
    passing_score=60.0, total_questions=0,
    caption=None, delete_after=0,
    reply_markup=None,
):
    from aiogram.types import BufferedInputFile
    loop = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(
        None, generate_leaderboard_image,
        quiz_title, results, passing_score, total_questions
    )
    if not img_bytes: return None
    try:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(img_bytes, filename="leaderboard.png"),
            caption=caption or None,
            parse_mode="HTML" if caption else None,
            reply_markup=reply_markup or None,
        )
        if delete_after > 0:
            async def _d():
                await asyncio.sleep(delete_after)
                try: await bot.delete_message(chat_id, msg.message_id)
                except: pass
            asyncio.create_task(_d())
        return msg.message_id
    except Exception as e:
        logger.error(f"Yuborishda xato: {e}")
        return None
