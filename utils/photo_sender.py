"""Reliable Telegram test-image delivery helpers."""
import logging
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

log = logging.getLogger(__name__)

async def send_test_photo(bot, chat_id, q):
    """Send a question image without any caption/metadata.

    Uses the saved Telegram file_id first. If that fails and the question
    contains storage chat/message ids, re-fetches the storage message and
    sends the photo again with an empty caption.
    """
    photo_id = q.get("photo") or q.get("image")
    if not photo_id:
        return False

    try:
        await bot.send_photo(chat_id, photo_id, caption=None, protect_content=True)
        return True
    except (TelegramBadRequest, TelegramForbiddenError) as first_error:
        storage_chat = q.get("photo_storage_chat_id")
        storage_msg = q.get("photo_storage_message_id")
        if not storage_chat or not storage_msg:
            log.error("Test rasm yuborilmadi: file_id ishlamadi va storage message id yo'q: %s", first_error)
            return False
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=storage_chat,
                message_id=storage_msg,
                caption="",
                protect_content=True,
            )
            return True
        except Exception as second_error:
            log.error("Storage fallback rasm yuborishda xato: %s", second_error)
    except Exception as e:
        log.error("Test rasm yuborishda xato: %s", e)
    return False
