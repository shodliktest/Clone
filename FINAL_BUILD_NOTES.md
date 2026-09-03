# QuizBot — Final Pro Build

This build is based on the latest supplied working Clone project.

## Included
- Existing Premium ID system using the existing `premium_users` table.
- Admin Premium management: add, extend, revoke, active list.
- Restricted tests: `allowed_users` OR active Premium access.
- Group restricted tests cannot be started by unauthorized users.
- Group persistence: newly discovered groups are immediately persisted to Supabase.
- QuizBot forwarded images are uploaded to `STORAGE_CHANNEL_ID` without caption and the NEW storage-channel `file_id` is saved to the question.
- Forwarded image/question pairing uses Telegram source `message_id` order and async futures to avoid race conditions.
- Existing Telegram flood-control throttling/retry logic is preserved.
- Existing functionality and database structure are preserved; no new Premium table/migration is added.

## Validation
- `compileall` is run on all Python sources.
- Premium access test is run.
- Premium admin parser test is run.
