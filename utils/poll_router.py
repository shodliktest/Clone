"""🔀 POLL ANSWER ROUTER — Yagona markaziy handler"""
import logging
from aiogram import Router
from aiogram.types import PollAnswer
from aiogram.fsm.context import FSMContext

log    = logging.getLogger(__name__)
router = Router()


@router.poll_answer()
async def universal_poll_router(poll_answer: PollAnswer, state: FSMContext,
                                 bot=None):
    try:
        from handlers.group          import route_poll_answer as group_handler
        from handlers.poll_test      import route_poll_answer as private_handler
        from handlers.group_scheduler import scheduler_poll_answer

        # 0. Scheduler ovoz pollimi? (eng avval tekshiramiz)
        await scheduler_poll_answer(poll_answer)

        # 1. Guruh sessiyasiga tegishlimi?
        handled = await group_handler(poll_answer)
        if handled:
            return True

        # 2. Private poll
        await private_handler(poll_answer, state, bot)
        return True
    except Exception as e:
        log.error(f"poll_router xato: {e}")
        return True
