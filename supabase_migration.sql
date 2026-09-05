-- ============================================================
-- TestPro Web — yangi Supabase jadvallari
-- ============================================================
-- Bu skriptni Supabase Dashboard → SQL Editor'da BIR MARTA
-- ishga tushiring (bot ishlatadigan xuddi shu loyihada).
--
-- `tests` va `users` jadvallari allaqachon bot tomonidan
-- yaratilgan bo'lishi kerak — bu yerda faqat YANGI, web uchun
-- kerak bo'lgan ikkita jadval qo'shiladi.

-- ── 1. results — foydalanuvchi test natijalari ────────────────
create table if not exists results (
  result_id         text primary key,
  user_id           text not null,
  user_name         text,
  user_username     text,
  test_id           text not null,
  test_title        text,
  subject           text,
  source            text default 'web',
  score             numeric default 0,
  correct           integer default 0,
  total             integer default 0,
  percentage        numeric default 0,
  passing_score     numeric default 60,
  passed            boolean default false,
  elapsed           integer default 0,
  detailed_results  jsonb default '[]'::jsonb,
  completed_at      timestamptz default now()
);

create index if not exists results_user_id_idx  on results (user_id);
create index if not exists results_test_id_idx  on results (test_id);
create index if not exists results_completed_idx on results (completed_at desc);

-- ── 2. live_sessions — Live Monitor (bot + web umumiy) ────────
create table if not exists live_sessions (
  session_id     text primary key,
  user_id        text not null,
  test_id        text not null,
  test_title     text,
  user_name      text,
  user_username  text,
  source         text default 'web',   -- 'web' | 'bot_inline' | 'bot_poll'
  idx            integer default 0,
  total_q        integer default 0,
  started_at     timestamptz default now(),
  last_seen      timestamptz default now()
);

-- Jadval ALLAQACHON mavjud bo'lsa (yuqoridagi CREATE TABLE ishlamaydi),
-- yangi ustunlarni shu bilan qo'shing — bir marta ishga tushiring:
alter table live_sessions add column if not exists user_name text;
alter table live_sessions add column if not exists user_username text;

create index if not exists live_sessions_last_seen_idx on live_sessions (last_seen);

-- Eslatma: bu jadval "davomiyli" jadval emas — sessiyalar test
-- tugagach o'chiriladi (DELETE), yoki 2 daqiqadan uzoq yangilanmasa
-- "eskirgan" hisoblanib admin ekranida ko'rsatilmaydi. Shu sabab RLS/
-- indekslash minimal — vaqti-vaqti bilan bo'sh qatorlar qolib ketsa,
-- quyidagi so'rov bilan tozalash mumkin:
--
--   delete from live_sessions where last_seen < now() - interval '10 minutes';
