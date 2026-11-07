-- ═══════════════════════════════════════════════════════════════════════════
-- supabase_patch_v16.sql — Supabase → SQL Editor'da ishga tushiring.
-- QAYTA ISHGA TUSHIRSANGIZ HAM XAVFSIZ: hech narsa o'chirilmaydi, mavjud ma'lumotga tegilmaydi.
-- Tekshirish uchun keyin supabase_verify_v16.sql ni ishga tushiring.
-- ═══════════════════════════════════════════════════════════════════════════

-- 1) Majburiy obuna sozlamasi (admin o'chirmaguncha saqlanadi)
create table if not exists force_join_config (
    id         int primary key,
    enabled    boolean     not null default false,
    channels   jsonb       not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);
insert into force_join_config (id) values (1) on conflict (id) do nothing;
alter table force_join_config disable row level security;

-- 2) Xato javoblar: har userga BITTA qator (oxirgi yechilgan test). JSON fayl Statistika kanalida.
--    Agar jadval ESKI shaklda (user_id + test_id kalit) yaratilgan bo'lsa — ma'lumot o'chirilmaydi:
--    eskisi user_wrong_answers_old nomiga o'tkaziladi va yangi jadval yaratiladi.
do $$
begin
    if exists (select 1 from information_schema.tables
                where table_schema = 'public' and table_name = 'user_wrong_answers')
       and (select count(*)
              from information_schema.table_constraints c
              join information_schema.key_column_usage k
                on k.constraint_name = c.constraint_name and k.table_schema = c.table_schema
             where c.table_schema = 'public' and c.table_name = 'user_wrong_answers'
               and c.constraint_type = 'PRIMARY KEY') > 1
    then
        alter table user_wrong_answers rename to user_wrong_answers_old;
        alter index if exists user_wrong_answers_pkey rename to user_wrong_answers_old_pkey;
    end if;
end $$;
create table if not exists user_wrong_answers (
    user_id     bigint primary key,
    test_id     text,
    title       text,
    message_id  bigint,          -- Statistika kanalidagi xabar (har safar shu xabar yangilanadi)
    file_id     text,
    wrong_count int         not null default 0,
    total       int         not null default 0,
    updated_at  timestamptz not null default now()
);
alter table user_wrong_answers disable row level security;

-- 3) Batafsil tahlil indeksi: har (user, test) uchun bitta qator. JSON Statistika kanalida.
create table if not exists user_analysis (
    user_id     bigint      not null,
    test_id     text        not null,
    result_id   text,
    title       text,
    message_id  bigint,
    file_id     text,
    correct     int         not null default 0,
    total       int         not null default 0,
    percentage  numeric     not null default 0,
    updated_at  timestamptz not null default now(),
    primary key (user_id, test_id)
);
create index if not exists idx_user_analysis_user_updated on user_analysis (user_id, updated_at desc);
alter table user_analysis disable row level security;

-- 4) "Kim yechgan": har test uchun BITTA qator — indeks (kanaldagi JSON xabari) + tezkor sanoqlar.
--    test_id = '__web_sync__' — webdagi natijalar qayerga qadar o'qilganini eslab qoluvchi xizmat qatori.
create table if not exists test_solvers_index (
    test_id         text primary key,
    message_id      bigint,
    file_id         text,
    solver_count    int         not null default 0,   -- nechta kishi yechgan/boshlagan
    attempts_total  int         not null default 0,   -- jami urinishlar
    avg_score       numeric     not null default 0,   -- o'rtacha foiz
    last_solved_at  text,
    updated_at      timestamptz not null default now()
);
alter table test_solvers_index disable row level security;

-- 5) Testlar arxivi: har test uchun BITTA qator — Telegram "Testlar" kanalidagi JSON ko'rsatkichi
--    va "oxirgi murojaat" vaqti. 14 kun ochilmagan testning savollari Supabase'dan olinadi
--    (tests qatori, meta, solve_count, avg_score SAQLANADI), indeks orqali kanaldan tiklanadi.
create table if not exists test_archive_index (
    test_id         text primary key,
    message_id      bigint,
    file_id         text,
    question_count  int,
    size_bytes      int,
    saved_at        timestamptz,                                   -- kanaldagi nusxa qachon yozilgan
    last_access_at  timestamptz not null default now(),            -- oxirgi marta ochilgan/yechilgan
    archived        boolean     not null default false,            -- true: savollar Supabase'dan olingan
    archived_at     timestamptz
);
create index if not exists idx_archive_state on test_archive_index (archived, last_access_at);
alter table test_archive_index disable row level security;

-- 6) Mavjud jadvallarga kerakli ustunlar (agar eski migratsiya ishlatilgan bo'lsa yetishmasligi mumkin)
alter table if exists live_sessions add column if not exists user_name     text;
alter table if exists live_sessions add column if not exists user_username text;
alter table if exists tests         add column if not exists updated_at    timestamptz not null default now();

-- 7) Tezlik uchun indekslar (natijalar ko'paygan sari "kim yechgan", tarix va webdagi natijalarni
--    o'qish sekinlashmasligi uchun). Mavjud ma'lumotga ta'sir qilmaydi.
create index if not exists idx_results_test_id      on results (test_id);
create index if not exists idx_results_user_done    on results (user_id, completed_at desc);
create index if not exists idx_results_completed_at on results (completed_at);
create index if not exists idx_live_sessions_test   on live_sessions (test_id);

-- 8) Eski joydan ko'chirish: app_settings.force_join bo'lsa — yangi jadvalga nusxalash
update force_join_config f
   set enabled  = coalesce((a.data->'force_join'->>'enabled')::boolean, f.enabled),
       channels = coalesce(a.data->'force_join'->'channels', f.channels)
  from app_settings a
 where f.id = 1 and a.id = 1 and (a.data->'force_join') is not null;

-- 9) API (PostgREST) yangi jadvallarni darhol ko'rishi uchun
notify pgrst, 'reload schema';
