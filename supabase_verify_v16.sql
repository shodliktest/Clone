-- ═══════════════════════════════════════════════════════════════════════════
-- supabase_verify_v16.sql — FAQAT O'QIYDI (hech narsani o'zgartirmaydi).
-- supabase_patch_v16.sql dan keyin ishga tushiring: yetishmayotgan jadval/ustunlar eng tepada "❌ YO'Q" bo'lib chiqadi.
-- Hammasi joyida bo'lsa — birinchi qatorlar ham "✅".
-- ═══════════════════════════════════════════════════════════════════════════

-- A) Jadval va ustunlar (kod ishlatadigan barchasi)
with expected(tbl, col) as (values
  ('tests','test_id'),('tests','title'),('tests','questions'),('tests','meta'),('tests','question_count'),
  ('tests','is_active'),('tests','is_paused'),('tests','solve_count'),('tests','avg_score'),('tests','updated_at'),
  ('results','result_id'),('results','user_id'),('results','user_name'),('results','user_username'),('results','test_id'),
  ('results','test_title'),('results','percentage'),('results','completed_at'),('results','detailed_results'),
  ('live_sessions','session_id'),('live_sessions','user_id'),('live_sessions','test_id'),('live_sessions','user_name'),
  ('live_sessions','user_username'),('live_sessions','idx'),('live_sessions','total_q'),('live_sessions','started_at'),('live_sessions','last_seen'),
  ('user_stats','tg_id'),('user_stats','data'),
  ('users','tg_id'),('users','data'),
  ('app_settings','id'),('app_settings','data'),
  ('force_join_config','id'),('force_join_config','enabled'),('force_join_config','channels'),
  ('user_wrong_answers','user_id'),('user_wrong_answers','test_id'),('user_wrong_answers','title'),('user_wrong_answers','message_id'),
  ('user_wrong_answers','file_id'),('user_wrong_answers','wrong_count'),('user_wrong_answers','total'),('user_wrong_answers','updated_at'),
  ('user_analysis','user_id'),('user_analysis','test_id'),('user_analysis','result_id'),('user_analysis','title'),('user_analysis','message_id'),
  ('user_analysis','file_id'),('user_analysis','correct'),('user_analysis','total'),('user_analysis','percentage'),('user_analysis','updated_at'),
  ('test_solvers_index','test_id'),('test_solvers_index','message_id'),('test_solvers_index','file_id'),('test_solvers_index','solver_count'),
  ('test_solvers_index','attempts_total'),('test_solvers_index','avg_score'),('test_solvers_index','last_solved_at'),('test_solvers_index','updated_at'),
  ('test_archive_index','test_id'),('test_archive_index','message_id'),('test_archive_index','file_id'),('test_archive_index','question_count'),
  ('test_archive_index','size_bytes'),('test_archive_index','saved_at'),('test_archive_index','last_access_at'),
  ('test_archive_index','archived'),('test_archive_index','archived_at')
)
select e.tbl as jadval, e.col as ustun,
       case when c.column_name is null then '❌ YO''Q' else '✅' end as holat
  from expected e
  left join information_schema.columns c
    on c.table_schema = 'public' and c.table_name = e.tbl and c.column_name = e.col
 order by (c.column_name is not null), e.tbl, e.col;

-- B) user_wrong_answers kaliti faqat user_id bo'lishi kerak (1 ta ustun)
select 'user_wrong_answers kaliti' as tekshiruv,
       count(*) as kalit_ustunlar_soni,
       case when count(*) = 1 then '✅' else '❌ eski shakl — supabase_patch_v16.sql ni qayta ishga tushiring' end as holat
  from information_schema.table_constraints c
  join information_schema.key_column_usage k
    on k.constraint_name = c.constraint_name and k.table_schema = c.table_schema
 where c.table_schema = 'public' and c.table_name = 'user_wrong_answers' and c.constraint_type = 'PRIMARY KEY';

-- C) force_join_config da id=1 qatori bor bo'lishi kerak
select 'force_join_config qatori' as tekshiruv, count(*) as qatorlar,
       case when count(*) = 1 then '✅' else '❌ insert into force_join_config (id) values (1);' end as holat
  from force_join_config where id = 1;

-- D) Hozirgi holat (ma'lumot hajmi): har jadvalda nechta qator va umumiy hajm
select relname as jadval, n_live_tup as qatorlar,
       pg_size_pretty(pg_total_relation_size(relid)) as hajm
  from pg_stat_user_tables
 order by pg_total_relation_size(relid) desc;
