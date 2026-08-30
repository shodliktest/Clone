-- ════════════════════════════════════════════════════════════════
-- QuizMarkerBot (shodliktest) — TO'LIQ Supabase sxemasi
-- ════════════════════════════════════════════════════════════════
-- BITTA fayl — yangi (bo'sh) Supabase loyihasida ХАМ, mavjud
-- loyihada ХАМ bemalol ishga tushirish mumkin.
--
-- Supabase Dashboard → SQL Editor → shu faylni to'liq joylashtirib
-- "Run" bosing. Necha marta ishga tushirsangiz ham xavfsiz:
--
--   • "create table if not exists"   → jadval BOR bo'lsa, tegmaydi
--   • "add column if not exists"     → ustun BOR bo'lsa, tegmaydi
--                                       YO'Q bo'lsa — qo'shadi
--                                       (masalan eski jadvalda
--                                       "updated_at" yo'q bo'lib
--                                       qolgan holatni ham tuzatadi)
--   • "create index if not exists"   → indeks BOR bo'lsa, tegmaydi
--   • Mavjud QATORLAR (ma'lumotlar) HECH QACHON o'chirilmaydi
--     yoki ustidan yozilmaydi — faqat STRUKTURA tekshiriladi.
--
-- Tarkib: 9 ta jadval, avtomatik updated_at triggerlari, RLS
-- sozlamalari, rasm saqlash uchun Storage bucket, va admin panel
-- uchun baza-hajmi RPC funksiyasi.
-- ════════════════════════════════════════════════════════════════


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 1) TESTS — har bir test bitta qator, savollar JSONB ichida    │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists tests (
    test_id         text primary key
);
alter table tests add column if not exists title           text not null default '';
alter table tests add column if not exists questions       jsonb not null default '[]'::jsonb;
alter table tests add column if not exists meta            jsonb not null default '{}'::jsonb;
alter table tests add column if not exists question_count  integer not null default 0;
alter table tests add column if not exists is_active       boolean not null default true;
alter table tests add column if not exists is_paused       boolean not null default false;
alter table tests add column if not exists solve_count     integer not null default 0;
alter table tests add column if not exists avg_score       numeric not null default 0;
alter table tests add column if not exists created_at      timestamptz not null default now();
alter table tests add column if not exists updated_at      timestamptz not null default now();

create index if not exists idx_tests_active  on tests(is_active);
create index if not exists idx_tests_created on tests(created_at desc);


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 2) USERS                                                      │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists users (
    tg_id           bigint primary key
);
alter table users add column if not exists data       jsonb not null default '{}'::jsonb;
alter table users add column if not exists is_blocked boolean not null default false;
alter table users add column if not exists created_at timestamptz not null default now();
alter table users add column if not exists updated_at timestamptz not null default now();

create index if not exists idx_users_blocked on users(is_blocked);


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 3) USER_STATS — kim, qaysi testni, qachon yechgan             │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists user_stats (
    tg_id           bigint primary key references users(tg_id) on delete cascade
);
alter table user_stats add column if not exists data       jsonb not null default '{}'::jsonb;
alter table user_stats add column if not exists updated_at timestamptz not null default now();


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 4) APP_SETTINGS — bot uchun yagona (bitta qatorli) sozlama    │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists app_settings (
    id              integer primary key default 1,
    constraint single_row check (id = 1)
);
alter table app_settings add column if not exists data       jsonb not null default '{}'::jsonb;
alter table app_settings add column if not exists updated_at timestamptz not null default now();

insert into app_settings (id, data) values (1, '{}'::jsonb)
    on conflict (id) do nothing;


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 5) KNOWN_GROUPS — bot admin bo'lgan guruhlar                  │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists known_groups (
    chat_id         bigint primary key
);
alter table known_groups add column if not exists data       jsonb not null default '{}'::jsonb;
alter table known_groups add column if not exists updated_at timestamptz not null default now();


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 6) LEADERBOARD — umumiy va guruh reytingi                     │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists leaderboard (
    scope           text primary key    -- 'global' yoki 'group_{chat_id}'
);
alter table leaderboard add column if not exists data       jsonb not null default '{}'::jsonb;
alter table leaderboard add column if not exists updated_at timestamptz not null default now();


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 7) BACKUPS — kunlik natijalar arxivi                          │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists backups (
    date_str        text primary key
);
alter table backups add column if not exists data       jsonb not null default '{}'::jsonb;
alter table backups add column if not exists created_at timestamptz not null default now();


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 8) FILE_FINGERPRINTS — qayta yuklangan faylni tanish           │
-- │    (bir xil fayl qayta yuklansa AI/parse qayta ishlamaydi)     │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists file_fingerprints (
    file_hash       text primary key
);
-- test_id — FK, default qiymati bo'lishi mumkin emas, shuning uchun
-- faqat jadval ENDI yaratilayotganda (yuqoridagi create table orqali)
-- to'g'ri kelib tushadi. Eski jadval bu ustunsiz bo'lib qolgan bo'lsa
-- (juda ehtimoldan yiroq holat), buni qo'lda ko'rib chiqish kerak.
alter table file_fingerprints add column if not exists test_id       text references tests(test_id) on delete cascade;
alter table file_fingerprints add column if not exists original_name text;
alter table file_fingerprints add column if not exists uploaded_by   bigint;
alter table file_fingerprints add column if not exists file_size     integer;
alter table file_fingerprints add column if not exists upload_count  integer not null default 1;
alter table file_fingerprints add column if not exists created_at    timestamptz not null default now();
alter table file_fingerprints add column if not exists last_seen_at  timestamptz not null default now();

create index if not exists idx_fingerprints_test on file_fingerprints(test_id);


-- ┌──────────────────────────────────────────────────────────────┐
-- │ 9) OTP_CODES — Web App (web_test.html/proxy.js) login kodlari │
-- └──────────────────────────────────────────────────────────────┘
create table if not exists otp_codes (
    code            text primary key
);
alter table otp_codes add column if not exists test_id    text;
alter table otp_codes add column if not exists tg_id      bigint not null default 0;
alter table otp_codes add column if not exists expires_at timestamptz not null default (now() + interval '10 minutes');
alter table otp_codes add column if not exists created_at timestamptz not null default now();

create index if not exists idx_otp_expires on otp_codes(expires_at);


-- ┌──────────────────────────────────────────────────────────────┐
-- │ AVTOMATIK "updated_at" TRIGGERLARI                             │
-- └──────────────────────────────────────────────────────────────┘
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

drop trigger if exists trg_app_settings_updated on app_settings;
create trigger trg_app_settings_updated before update on app_settings
    for each row execute function set_updated_at();

drop trigger if exists trg_known_groups_updated on known_groups;
create trigger trg_known_groups_updated before update on known_groups
    for each row execute function set_updated_at();

drop trigger if exists trg_leaderboard_updated on leaderboard;
create trigger trg_leaderboard_updated before update on leaderboard
    for each row execute function set_updated_at();


-- ┌──────────────────────────────────────────────────────────────┐
-- │ ROW LEVEL SECURITY — bot faqat service_role kalit bilan       │
-- │ kiradi (RLS'ni chetlab o'tadi), shuning uchun RLS o'chiriladi │
-- └──────────────────────────────────────────────────────────────┘
alter table tests             disable row level security;
alter table users             disable row level security;
alter table user_stats        disable row level security;
alter table app_settings      disable row level security;
alter table known_groups      disable row level security;
alter table leaderboard       disable row level security;
alter table backups           disable row level security;
alter table otp_codes         disable row level security;
alter table file_fingerprints disable row level security;


-- ┌──────────────────────────────────────────────────────────────┐
-- │ STORAGE BUCKET — savol rasmlari uchun ("quiz-images")         │
-- │ (handlers/create_test.py: client.storage.from_("quiz-images"))│
-- │ public=true → get_public_url() orqali olingan havola hech     │
-- │ qanday qo'shimcha policy'siz to'g'ridan-to'g'ri ochiladi      │
-- │ (Telegram/brauzer rasmni to'g'ridan-to'g'ri ko'rsata oladi).  │
-- │ Fayl hajmi/format cheklovi QO'YILMAGAN — hozirgi kod bunday   │
-- │ cheklovni kutmaydi, cheklov qo'yish yuklashni kutilmaganda    │
-- │ butlab qo'yishi mumkin.                                       │
-- └──────────────────────────────────────────────────────────────┘
insert into storage.buckets (id, name, public)
values ('quiz-images', 'quiz-images', true)
on conflict (id) do nothing;


-- ┌──────────────────────────────────────────────────────────────┐
-- │ RPC: get_storage_stats() — admin panelda "Supabase holati"    │
-- │ (baza umumiy hajmi + har bir jadval hajmi, jumladan "tests")  │
-- └──────────────────────────────────────────────────────────────┘
create or replace function public.get_storage_stats()
returns json
language sql
security definer
set search_path = public
as $$
  select json_build_object(
    'total_bytes', pg_database_size(current_database()),
    'tables', (
      select coalesce(json_agg(t), '[]'::json)
      from (
        select
          c.relname                                              as table_name,
          pg_total_relation_size(c.oid)                          as total_bytes,
          pg_relation_size(c.oid)                                as table_bytes,
          pg_total_relation_size(c.oid) - pg_relation_size(c.oid) as index_bytes,
          coalesce(s.n_live_tup, 0)                              as row_estimate
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        left join pg_stat_user_tables s on s.relid = c.oid
        where n.nspname = 'public' and c.relkind = 'r'
        order by pg_total_relation_size(c.oid) desc
      ) t
    )
  );
$$;

grant execute on function public.get_storage_stats() to service_role;


-- ┌──────────────────────────────────────────────────────────────┐
-- │ POSTGREST SXEMA KESHINI YANGILASH                              │
-- │ (yangi jadval/funksiya "Could not find table/function" xatosi │
-- │ bermasligi uchun — PostgREST'ga "qayta o'qi" signali beradi)  │
-- └──────────────────────────────────────────────────────────────┘
notify pgrst, 'reload schema';


-- ════════════════════════════════════════════════════════════════
-- TAYYOR!
--
-- Keyingi qadam — Streamlit/bot muhitida (.env yoki secrets.toml):
--   SUPABASE_URL = https://xxxxx.supabase.co
--   SUPABASE_KEY = <service_role kaliti — anon EMAS>
--
-- Tekshirish uchun (ixtiyoriy, SQL Editor'da alohida ishga tushiring):
--   select get_storage_stats();
--   select * from storage.buckets where id = 'quiz-images';
--   select table_name from information_schema.tables
--     where table_schema = 'public' order by table_name;
-- ════════════════════════════════════════════════════════════════


-- GLOBAL PREMIUM IDS
create table if not exists premium_users (
 user_id bigint primary key,
 started_at timestamptz not null default now(),
 expires_at timestamptz not null,
 granted_by bigint,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create index if not exists idx_premium_expires on premium_users(expires_at);
