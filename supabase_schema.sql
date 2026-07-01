-- ════════════════════════════════════════════════════════════════
-- QuizMarkerBot — Supabase (Postgres) sxemasi
-- ════════════════════════════════════════════════════════════════
-- Bu faylni Supabase Dashboard → SQL Editor da BIR MARTA ishga
-- tushiring (yangi loyiha yaratilgandan keyin).
--
-- Eski "Storage Channel" arxitekturasi to'liq shu jadvallarga
-- ko'chiriladi. JSONB ustunlar eski JSON strukturasini 1:1 saqlaydi,
-- shuning uchun handlers/ ichidagi kod o'zgarmaydi.
-- ════════════════════════════════════════════════════════════════

-- ─── TESTS ──────────────────────────────────────────────────────
-- Har bir test bitta qator. "questions" JSONB ichida saqlanadi —
-- eski test_{tid}.json fayli bilan bir xil struktura.
create table if not exists tests (
    test_id         text primary key,
    title           text not null default '',
    questions       jsonb not null default '[]'::jsonb,
    meta            jsonb not null default '{}'::jsonb,   -- title, subject, difficulty va h.k. (questions'siz)
    question_count  integer not null default 0,
    is_active       boolean not null default true,
    is_paused       boolean not null default false,
    solve_count     integer not null default 0,
    avg_score       numeric not null default 0,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index if not exists idx_tests_active on tests(is_active);
create index if not exists idx_tests_created on tests(created_at desc);

-- ─── USERS ──────────────────────────────────────────────────────
create table if not exists users (
    tg_id           bigint primary key,
    data            jsonb not null default '{}'::jsonb,   -- ism, username, role, referral va h.k.
    is_blocked      boolean not null default false,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index if not exists idx_users_blocked on users(is_blocked);

-- ─── USER STATS (kim, qaysi testni qachon yechgan) ─────────────
create table if not exists user_stats (
    tg_id           bigint primary key references users(tg_id) on delete cascade,
    data            jsonb not null default '{}'::jsonb,   -- {by_test:{tid:{attempts,best_score,...}}}
    updated_at      timestamptz not null default now()
);

-- ─── SETTINGS (bot global sozlamalari) ─────────────────────────
create table if not exists app_settings (
    id              integer primary key default 1,
    data            jsonb not null default '{}'::jsonb,
    updated_at      timestamptz not null default now(),
    constraint single_row check (id = 1)
);
insert into app_settings (id, data) values (1, '{}'::jsonb)
    on conflict (id) do nothing;

-- ─── BLOCKED USERS ──────────────────────────────────────────────
-- (users.is_blocked allaqachon bor, lekin tezkor set sifatida
--  alohida ham saqlanadi — eski API bilan moslik uchun)

-- ─── KNOWN GROUPS (bot admin bo'lgan guruhlar) ──────────────────
create table if not exists known_groups (
    chat_id         bigint primary key,
    data            jsonb not null default '{}'::jsonb,
    updated_at      timestamptz not null default now()
);

-- ─── LEADERBOARD (umumiy va guruh) ──────────────────────────────
create table if not exists leaderboard (
    scope           text primary key,    -- 'global' yoki 'group_{chat_id}'
    data            jsonb not null default '{}'::jsonb,
    updated_at      timestamptz not null default now()
);

-- ─── BACKUPS (kunlik natijalar arxivi) ──────────────────────────
create table if not exists backups (
    date_str        text primary key,
    data            jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);

-- ─── OTP (Web App login kodlari) ────────────────────────────────
create table if not exists otp_codes (
    code            text primary key,
    test_id         text not null,
    tg_id           bigint not null default 0,
    expires_at      timestamptz not null,
    created_at      timestamptz not null default now()
);
create index if not exists idx_otp_expires on otp_codes(expires_at);

-- ─── AUTO updated_at trigger ─────────────────────────────────────
create or replace function set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_tests_updated on tests;
create trigger trg_tests_updated before update on tests
    for each row execute function set_updated_at();

drop trigger if exists trg_users_updated on users;
create trigger trg_users_updated before update on users
    for each row execute function set_updated_at();

drop trigger if exists trg_user_stats_updated on user_stats;
create trigger trg_user_stats_updated before update on user_stats
    for each row execute function set_updated_at();

-- ─── Row Level Security — botdan service_role kalit bilan kirilgani
--     uchun RLS ni o'chirib qo'yamiz (faqat backend kirishi mumkin) ─
alter table tests         disable row level security;
alter table users         disable row level security;
alter table user_stats    disable row level security;
alter table app_settings  disable row level security;
alter table known_groups  disable row level security;
alter table leaderboard   disable row level security;
alter table backups       disable row level security;
alter table otp_codes     disable row level security;

-- ════════════════════════════════════════════════════════════════
-- TAYYOR. Endi Streamlit secrets.toml ga SUPABASE_URL va
-- SUPABASE_KEY (service_role) qo'shing va botni qayta ishga tushiring.
-- ════════════════════════════════════════════════════════════════
