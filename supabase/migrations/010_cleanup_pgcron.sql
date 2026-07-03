-- =====================================================================
-- Documento 103 — Higienização automática do banco bruto (pg_cron)
--
-- Objetivo duplo:
--   1) Segurar os 500 MB do plano Free do Supabase.
--   2) Cumprir o desenho do Sentinela: raw.* é buffer descartável de
--      curto prazo; knowledge.* é memória permanente.
--
-- REGRA DE OURO: esta limpeza NUNCA toca knowledge.*. Só apaga dado
-- bruto que já cumpriu sua função. A FK knowledge.claims.raw_item_id
-- (on delete restrict) é uma trava extra: itens referenciados por uma
-- claim validada são protegidos mesmo que a função tente apagá-los.
-- =====================================================================

-- No Supabase, pg_cron já está disponível — basta habilitar.
create extension if not exists pg_cron;

-- ---------------------------------------------------------------------
-- Log de auditoria das limpezas (fica no banco bruto, acesso só service_role)
-- ---------------------------------------------------------------------
create table if not exists raw.cleanup_log (
  id                        bigint generated always as identity primary key,
  ran_at                    timestamptz not null default now(),
  items_deleted             integer not null default 0,
  fetch_runs_deleted        integer not null default 0,
  estimated_bytes_freed     bigint  not null default 0,  -- peso lógico dos dados removidos (pg_column_size)
  items_retention_days      integer not null,
  fetch_runs_retention_days integer not null,
  note                      text
);
alter table raw.cleanup_log enable row level security;  -- sem policy = só service_role

-- ---------------------------------------------------------------------
-- Função de limpeza. Parametrizada — ajuste a retenção sem reescrever.
-- security definer: roda como owner, atravessa RLS para limpar o raw.
-- ---------------------------------------------------------------------
create or replace function raw.sentinela_cleanup(
  p_items_retention_days      integer default 7,
  p_fetch_runs_retention_days integer default 30
) returns raw.cleanup_log
language plpgsql
security definer
set search_path = raw, knowledge, public
as $$
declare
  v_items_deleted integer := 0;
  v_runs_deleted  integer := 0;
  v_items_bytes   bigint  := 0;
  v_runs_bytes    bigint  := 0;
  v_log           raw.cleanup_log;
begin
  -- 1) Itens brutos JÁ PROCESSADOS, antigos e NÃO referenciados por
  --    nenhuma claim. O "not exists" respeita a FK e garante que nada
  --    que o conhecimento ainda usa seja apagado.
  with del as (
    delete from raw.items i
    where i.collected_at < now() - make_interval(days => p_items_retention_days)
      and i.pipeline_status in ('discarded','duplicate','promoted')
      and not exists (
        select 1 from knowledge.claims c where c.raw_item_id = i.id
      )
    returning pg_column_size(i.*) as sz
  )
  select count(*), coalesce(sum(sz), 0) into v_items_deleted, v_items_bytes from del;

  -- 2) Logs de coleta antigos. (raw.items.fetch_run_id é on delete set
  --    null, então isso só desvincula; não derruba item nenhum.)
  with del as (
    delete from raw.fetch_runs f
    where f.started_at < now() - make_interval(days => p_fetch_runs_retention_days)
    returning pg_column_size(f.*) as sz
  )
  select count(*), coalesce(sum(sz), 0) into v_runs_deleted, v_runs_bytes from del;

  insert into raw.cleanup_log(
    items_deleted, fetch_runs_deleted, estimated_bytes_freed,
    items_retention_days, fetch_runs_retention_days, note
  )
  values (
    v_items_deleted, v_runs_deleted, (v_items_bytes + v_runs_bytes),
    p_items_retention_days, p_fetch_runs_retention_days,
    'higienização automática do banco bruto'
  )
  returning * into v_log;

  return v_log;
end;
$$;

comment on function raw.sentinela_cleanup is
  'Limpa apenas o banco bruto (raw.items processados + fetch_runs antigos). Nunca toca knowledge.*. Itens referenciados por claims são preservados.';

-- ---------------------------------------------------------------------
-- View de acompanhamento: consumo liberado por dia + acumulado.
-- Permite decidir mexer na retenção (ex.: 7→5 dias) com base em série
-- temporal própria, sem depender do painel do Supabase.
-- ---------------------------------------------------------------------
create or replace view raw.cleanup_trend as
select
  ran_at::date                                       as dia,
  sum(items_deleted)                                 as itens_apagados,
  sum(fetch_runs_deleted)                            as fetch_runs_apagados,
  sum(estimated_bytes_freed)                         as bytes_liberados,
  pg_size_pretty(sum(estimated_bytes_freed))         as liberado_legivel,
  pg_size_pretty(sum(sum(estimated_bytes_freed))
    over (order by ran_at::date))                    as acumulado_legivel
from raw.cleanup_log
group by ran_at::date
order by dia desc;

comment on view raw.cleanup_trend is
  'Tendência de consumo liberado pela higienização (diário + acumulado).';

-- ---------------------------------------------------------------------
-- Agendamento diário via pg_cron (04:00 UTC ≈ 01:00 BRT, fora do pico).
-- Idempotente: remove o job anterior (se existir) antes de reagendar.
-- ---------------------------------------------------------------------
do $$
begin
  perform cron.unschedule('sentinela-cleanup-raw');
exception when others then
  null;  -- job ainda não existe — ok
end $$;

select cron.schedule(
  'sentinela-cleanup-raw',
  '0 4 * * *',
  $cron$ select raw.sentinela_cleanup(7, 30); $cron$
);

-- ---------------------------------------------------------------------
-- Uso manual / inspeção:
--   select * from raw.sentinela_cleanup();           -- roda agora (7/30)
--   select * from raw.sentinela_cleanup(3, 14);      -- retenção custom
--   select * from raw.cleanup_log order by ran_at desc limit 10;
--   select * from cron.job;                           -- ver o agendamento
--   select * from cron.job_run_details order by start_time desc limit 5;
-- ---------------------------------------------------------------------
