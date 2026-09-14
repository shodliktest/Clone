"""Telegram Bot wrapper with recipient-aware protect_content policy.

Telegram's protect_content is attached to each outgoing message.  The global
bot default cannot make an exception for a particular private recipient, so
this wrapper clears protection for security admins in private chats while
leaving group/channel messages unchanged.
"""
from aiogram import Bot


class SecureBot(Bot):
    """Bot that always allows configured admins to copy/forward screenshots.

    The exemption is only for private recipients (positive Telegram user IDs).
    Group/channel messages remain governed by the global security setting,
    because Telegram cannot apply protect_content differently per recipient
    inside one shared chat message.
    """

    @staticmethod
    def _admin_private(chat_id, kwargs):
        try:
            uid = int(chat_id)
        except (TypeError, ValueError):
            return
        if uid <= 0:
            return
        try:
            # Use the same role engine that the bot uses everywhere else.
            # This covers ADMIN_IDS and active role=admin users.
            from utils.roles import get_role
            if get_role(uid) == "admin":
                kwargs["protect_content"] = False
            else:
                from config import ADMIN_IDS
                if uid in (ADMIN_IDS or []):
                    kwargs["protect_content"] = False
        except Exception:
            # Never let the security helper break normal message delivery.
            pass

    async def send_message(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_message(chat_id, *args, **kwargs)

    async def send_photo(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_photo(chat_id, *args, **kwargs)

    async def send_video(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_video(chat_id, *args, **kwargs)

    async def send_document(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_document(chat_id, *args, **kwargs)

    async def send_audio(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_audio(chat_id, *args, **kwargs)

    async def send_animation(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_animation(chat_id, *args, **kwargs)

    async def send_voice(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_voice(chat_id, *args, **kwargs)

    async def send_video_note(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_video_note(chat_id, *args, **kwargs)

    async def send_sticker(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_sticker(chat_id, *args, **kwargs)

    async def send_poll(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_poll(chat_id, *args, **kwargs)

    async def send_media_group(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().send_media_group(chat_id, *args, **kwargs)

    async def forward_message(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().forward_message(chat_id, *args, **kwargs)

    async def copy_message(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().copy_message(chat_id, *args, **kwargs)

    async def forward_messages(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().forward_messages(chat_id, *args, **kwargs)

    async def copy_messages(self, chat_id, *args, **kwargs):
        self._admin_private(chat_id, kwargs)
        return await super().copy_messages(chat_id, *args, **kwargs)
