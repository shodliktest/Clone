# PRO FIX — QuizBot Forward / Poll Order

## Guaranteed logic
- Incoming QuizBot photo/poll events are buffered per user and sorted by Telegram chat message_id.
- Photo events are stored in a FIFO photo queue.
- Each photo is attached to exactly the next quiz poll.
- A quiz with no preceding photo remains standalone.
- Sequence example: Photo1, Quiz1, Quiz2, Photo3, Quiz3 -> Photo1+Quiz1, Quiz2, Photo3+Quiz3.
- Storage channel message_id and channel_id are persisted for imported images and forwarded QuizBot images.
- Test solving uses copy_message from the storage channel when IDs exist, with file_id fallback.
- Long poll questions (>300 Telegram UTF-16 units) are sent as one or more ordinary messages first, then a separate Quiz Poll containing only the short prompt and answer options.
- Ordinary message chunks respect Telegram's 4096 UTF-16-unit limit.
- Poll options and explanations respect Telegram limits.
- Finish waits for pending forward events so a fast "Tayyor" click does not lose queued polls.
- Cancel clears queued forward events and pending photos.

## Validation
- All Python files compile with `python -m compileall`.
- `utils/poll_safe.py` functional limit/order tests pass.

## Important runtime prerequisites
- Bot must be admin in STORAGE_CHANNEL_ID channel with permission to post.
- STORAGE_CHANNEL_ID must be configured.
