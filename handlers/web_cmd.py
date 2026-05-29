"""
🔄 WEB CMD HANDLER
Sayt proxy.js → TG storage kanal → bot ushlab oladi → RAM yangilaydi

Xabar formati (kanalga yuboriladi):
  WEB_CMD:UPDATE:{tid}:{creator_id}:{old_qc}:{new_qc}
  WEB_CMD:SPLIT:{creator_id}:{tid1}:{title1}:{qc1}|{tid2}:{title2}:{qc2}...
"""
import logging, json
from aiogram import Router, F
from aiogram.types import Message

log    = logging.getLogger(__name__)
router = Router()

CMD_PREFIX = "WEB_CMD:"


def _is_storage_channel(message: Message) -> bool:
    from config import STORAGE_CHANNEL_ID
    return message.chat.id == STORAGE_CHANNEL_ID


@router.channel_post(F.text.startswith(CMD_PREFIX))
async def handle_web_cmd(message: Message):
    """Storage kanaldan kelgan web buyruqlarini bajarish."""
    from utils import tg_db, ram_cache as ram
    from keyboards.keyboards import test_created_kb

    if not _is_storage_channel(message):
        return

    text = message.text or ""
    log.info(f"WEB_CMD: {text[:120]}")

    # Xabarni o'chirish — kanalda qolmasin
    try:
        await message.delete()
    except Exception:
        pass

    # ─── UPDATE: bitta test yangilandi ───────────────────────
    # Format: WEB_CMD:UPDATE:{tid}:{creator_id}:{old_qc}:{new_qc}
    if text.startswith("WEB_CMD:UPDATE:"):
        parts = text.split(":")
        if len(parts) < 6:
            return
        tid        = parts[2].strip().upper()
        creator_id = int(parts[3]) if parts[3].isdigit() else 0
        old_qc     = int(parts[4]) if parts[4].isdigit() else 0
        new_qc     = int(parts[5]) if parts[5].isdigit() else 0

        # 1. Bot RAM dan eski savollarni o'chirish
        tg_db._tests_cache.pop(tid, None)
        ram.invalidate_cached_questions(tid)
        log.info(f"WEB_CMD UPDATE: {tid} cache tozalandi")

        # 2. Creator ga hisobot
        meta = ram.get_test_meta_any(tid) if hasattr(ram, "get_test_meta_any") else {}
        if not meta:
            meta = {"creator_id": creator_id, "title": tid}

        await tg_db._notify_updated_test(meta, tid, old_qc, new_qc)
        return

    # ─── SPLIT: testlar bo'lindi ─────────────────────────────
    # Format: WEB_CMD:SPLIT:{creator_id}:{tid}:{title}:{qc}|...
    if text.startswith("WEB_CMD:SPLIT:"):
        try:
            rest       = text[len("WEB_CMD:SPLIT:"):]
            creator_id = int(rest.split(":")[0])
            parts_str  = ":".join(rest.split(":")[1:])
            # Har qism: tid:title:qc | bilan ajratilgan
            chunks = parts_str.split("|")
            bu = (await message.bot.get_me()).username

            total_parts = len([x for x in chunks if x.strip()])
            part_num    = 0
            for ch in chunks:
                ch = ch.strip()
                if not ch:
                    continue
                sub = ch.split(":", 2)
                if len(sub) < 3:
                    continue
                part_num += 1
                tid   = sub[0].strip().upper()
                title = sub[1].strip()
                qc    = int(sub[2]) if sub[2].isdigit() else 0
                # Bo'lak nomi: "Biologiya - 1-qism" yoki "Biologiya - 2-qism"
                if total_parts > 1:
                    title = f"{title} — {part_num}-qism"

                meta = {"creator_id": creator_id, "title": title,
                        "question_count": qc, "source": "web_split"}
                try:
                    NL  = "\n"
                    txt = (
                        "✂️ <b>Test bo'linmasi saqlandi!</b>" + NL
                        + "━" * 24 + NL
                        + f"📝 <b>{title}</b>" + NL
                        + f"📋 {qc} ta savol" + NL
                        + f"🆔 <code>{tid}</code>" + NL + NL
                        + "👇 Boshlash usulini tanlang:"
                    )
                    await message.bot.send_message(
                        creator_id, txt,
                        reply_markup=test_created_kb(tid, bu)
                    )
                except Exception as e:
                    log.warning(f"SPLIT notify {tid}: {e}")

                # Baza guruhiga ham yuborish
                try:
                    from utils.baza_publisher import publish_to_baza
                    from utils import tg_db
                    full = await tg_db.get_test_full(tid)
                    if full and full.get("questions"):
                        await publish_to_baza(
                            bot           = message.bot,
                            tid           = tid,
                            title         = title,
                            questions     = full["questions"],
                            creator_id    = creator_id,
                            bot_username  = bu,
                        )
                except Exception as _bp:
                    log.warning(f"SPLIT baza publish {tid}: {_bp}")

        except Exception as e:
            log.error(f"WEB_CMD SPLIT: {e}")
