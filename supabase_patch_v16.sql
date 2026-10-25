-- ═══════════════════════════════════════════════════════════════
-- supabase_patch_v16.sql — Supabase SQL Editor'da BIR MARTA ishga tushiring
-- (qayta ishga tushirsangiz ham xavfsiz: hammasi IF NOT EXISTS)
-- ═══════════════════════════════════════════════════════════════

-- 1) Majburiy obuna sozlamasi (admin o'chirmaguncha saqlanadi)
create table if not exists force_join_config (
    id         int primary key,
    enabled    boolean     not null default false,
    channels   jsonb       not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);
insert into force_join_config (id) values (1) on conflict (id) do nothing;
alter table force_join_config disable row level security;

-- 2) Web sahifa uchun: foydalanuvchi obunasi holati (bot yozadi, web o'qiydi)
create table if not exists force_join_status (
    user_id    bigint primary key,
    ok         boolean     not null default false,
    checked_at timestamptz not null default now()
);
alter table force_join_status disable row level security;

-- 3) Xato javoblar indeksi (keyingi bosqich uchun tayyor; hozir ishlatilmaydi)
create table if not exists user_wrong_answers (
    user_id     bigint      not null,
    test_id     text        not null,
    title       text,
    message_id  bigint,
    file_id     text,
    wrong_count int         not null default 0,
    total       int         not null default 0,
    updated_at  timestamptz not null default now(),
    primary key (user_id, test_id)
);
create index if not exists idx_uwa_user_updated on user_wrong_answers (user_id, updated_at desc);
alter table user_wrong_answers disable row level security;

-- 4) Eski joydan ko'chirish: app_settings.force_join bo'lsa — yangi jadvalga nusxalash
update force_join_config f
   set enabled  = coalesce((a.data->'force_join'->>'enabled')::boolean, f.enabled),
       channels = coalesce(a.data->'force_join'->'channels', f.channels)
  from app_settings a
 where f.id = 1 and a.id = 1 and a.data ? 'force_join';
