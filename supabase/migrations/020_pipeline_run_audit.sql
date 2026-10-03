-- 020_pipeline_run_audit.sql
-- Auditoria operacional do pipeline de sinais reais.
-- Nao altera Events, ResearcherSignals ou conteudo editorial.

create table if not exists raw.pipeline_runs (
    id                      uuid primary key,
    initiated_by            text not null
        check (length(btrim(initiated_by)) between 1 and 120),
    mode                    text not null
        check (mode in ('dry_run', 'persist')),
    status                  text not null default 'running'
        check (status in ('running', 'succeeded', 'partial', 'failed')),
    started_at              timestamptz not null,
    completed_at            timestamptz,

    requested_sources       text[] not null default '{}',
    consulted_sources       text[] not null default '{}',
    successful_sources      text[] not null default '{}',
    failed_sources          text[] not null default '{}',

    requested_source_count  integer not null default 0,
    successful_source_count integer not null default 0,
    failed_source_count     integer not null default 0,
    records_received        integer not null default 0,
    candidates_generated    integer not null default 0,
    signals_generated       integer not null default 0,
    signals_eligible        integer not null default 0,
    signals_persisted       integer not null default 0,

    error_stage             text,
    error_type              text,
    error_message           text,

    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),

    constraint pipeline_runs_nonnegative_counts check (
        requested_source_count >= 0
        and successful_source_count >= 0
        and failed_source_count >= 0
        and records_received >= 0
        and candidates_generated >= 0
        and signals_generated >= 0
        and signals_eligible >= 0
        and signals_persisted >= 0
    ),
    constraint pipeline_runs_time_order check (
        completed_at is null or completed_at >= started_at
    ),
    constraint pipeline_runs_completion_state check (
        (status = 'running' and completed_at is null)
        or (status <> 'running' and completed_at is not null)
    ),
    constraint pipeline_runs_requested_count check (
        requested_source_count = cardinality(requested_sources)
    ),
    constraint pipeline_runs_success_count check (
        successful_source_count = cardinality(successful_sources)
    ),
    constraint pipeline_runs_failure_count check (
        failed_source_count = cardinality(failed_sources)
    ),
    constraint pipeline_runs_consulted_count check (
        successful_source_count + failed_source_count
            <= cardinality(consulted_sources)
    ),
    constraint pipeline_runs_persisted_count check (
        signals_persisted <= signals_eligible
    ),
    constraint pipeline_runs_error_lengths check (
        char_length(coalesce(error_stage, '')) <= 80
        and char_length(coalesce(error_type, '')) <= 120
        and char_length(coalesce(error_message, '')) <= 512
    )
);

create index if not exists idx_pipeline_runs_started
    on raw.pipeline_runs (started_at desc);

create index if not exists idx_pipeline_runs_status_started
    on raw.pipeline_runs (status, started_at desc);

create or replace trigger trg_pipeline_runs_updated
    before update on raw.pipeline_runs
    for each row execute function public.set_updated_at();

alter table raw.pipeline_runs enable row level security;

alter table raw.fetch_runs
    add column if not exists pipeline_run_id uuid
        references raw.pipeline_runs(id) on delete cascade,
    add column if not exists collector text,
    add column if not exists collector_role text,
    add column if not exists scientific_areas text[] not null default '{}',
    add column if not exists records_received integer not null default 0,
    add column if not exists candidates_generated integer not null default 0,
    add column if not exists signals_generated integer,
    add column if not exists error_type text,
    add column if not exists attempt integer not null default 1;

alter table raw.fetch_runs
    drop constraint if exists fetch_runs_collector_role_check,
    add constraint fetch_runs_collector_role_check check (
        collector_role is null
        or collector_role in ('requested', 'supporting')
    ),
    drop constraint if exists fetch_runs_audit_counts_check,
    add constraint fetch_runs_audit_counts_check check (
        records_received >= 0
        and candidates_generated >= 0
        and (signals_generated is null or signals_generated >= 0)
        and attempt >= 1
    ),
    drop constraint if exists fetch_runs_audit_time_order_check,
    add constraint fetch_runs_audit_time_order_check check (
        finished_at is null or finished_at >= started_at
    ),
    drop constraint if exists fetch_runs_audit_identity_check,
    add constraint fetch_runs_audit_identity_check check (
        pipeline_run_id is null
        or (
            collector is not null
            and length(btrim(collector)) between 1 and 120
            and collector_role is not null
        )
    ),
    drop constraint if exists fetch_runs_audit_error_lengths_check,
    add constraint fetch_runs_audit_error_lengths_check check (
        char_length(coalesce(error_type, '')) <= 120
        and char_length(coalesce(error, '')) <= 512
    );

create index if not exists idx_fetch_runs_pipeline_run
    on raw.fetch_runs (pipeline_run_id);

create unique index if not exists uq_fetch_runs_pipeline_collector_attempt
    on raw.fetch_runs (pipeline_run_id, collector, attempt)
    where pipeline_run_id is not null and collector is not null;

-- raw permanece fora dos schemas expostos pela Data API. As funcoes abaixo
-- sao a unica ponte de escrita e aceitam apenas metadata operacional.

create or replace function public.create_pipeline_run_audit(p_run jsonb)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public, raw
as $$
declare
    v_id uuid;
    v_started_at timestamptz;
    v_requested_sources text[];
begin
    if p_run is null or jsonb_typeof(p_run) <> 'object' then
        raise exception 'invalid pipeline run audit payload';
    end if;

    v_id := (p_run ->> 'run_id')::uuid;
    v_started_at := (p_run ->> 'started_at')::timestamptz;
    select coalesce(array_agg(value order by ordinality), '{}')
      into v_requested_sources
      from jsonb_array_elements_text(coalesce(p_run -> 'requested_sources', '[]'))
           with ordinality as sources(value, ordinality);

    if p_run ->> 'status' <> 'running' then
        raise exception 'pipeline run must start with running status';
    end if;

    insert into raw.pipeline_runs (
        id, initiated_by, mode, status, started_at,
        requested_sources, requested_source_count
    ) values (
        v_id,
        p_run ->> 'initiated_by',
        p_run ->> 'mode',
        'running',
        v_started_at,
        v_requested_sources,
        cardinality(v_requested_sources)
    );
end;
$$;

create or replace function public.record_pipeline_collector_audit(p_collector jsonb)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public, raw
as $$
declare
    v_status public.fetch_status;
    v_areas text[];
begin
    if p_collector is null or jsonb_typeof(p_collector) <> 'object' then
        raise exception 'invalid collector audit payload';
    end if;

    v_status := case p_collector ->> 'status'
        when 'running' then 'running'::public.fetch_status
        when 'succeeded' then 'success'::public.fetch_status
        when 'partial' then 'partial'::public.fetch_status
        when 'failed' then 'error'::public.fetch_status
        else null
    end;
    if v_status is null then
        raise exception 'invalid collector audit status';
    end if;

    select coalesce(array_agg(value order by ordinality), '{}')
      into v_areas
      from jsonb_array_elements_text(coalesce(p_collector -> 'scientific_areas', '[]'))
           with ordinality as areas(value, ordinality);

    insert into raw.fetch_runs (
        pipeline_run_id, collector, collector_role, scientific_areas,
        status, started_at, finished_at, records_received,
        candidates_generated, signals_generated, error_type, error, attempt
    ) values (
        (p_collector ->> 'run_id')::uuid,
        p_collector ->> 'collector',
        p_collector ->> 'collector_role',
        v_areas,
        v_status,
        (p_collector ->> 'started_at')::timestamptz,
        nullif(p_collector ->> 'completed_at', '')::timestamptz,
        coalesce((p_collector ->> 'records_received')::integer, 0),
        coalesce((p_collector ->> 'candidates_generated')::integer, 0),
        nullif(p_collector ->> 'signals_generated', '')::integer,
        nullif(p_collector ->> 'error_type', ''),
        nullif(p_collector ->> 'error_message', ''),
        coalesce((p_collector ->> 'attempt')::integer, 1)
    )
    on conflict (pipeline_run_id, collector, attempt)
        where pipeline_run_id is not null and collector is not null
    do update set
        collector_role = excluded.collector_role,
        scientific_areas = excluded.scientific_areas,
        status = excluded.status,
        started_at = excluded.started_at,
        finished_at = excluded.finished_at,
        records_received = excluded.records_received,
        candidates_generated = excluded.candidates_generated,
        signals_generated = excluded.signals_generated,
        error_type = excluded.error_type,
        error = excluded.error;
end;
$$;

create or replace function public.finalize_pipeline_run_audit(p_run jsonb)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public, raw
as $$
declare
    v_requested_sources text[];
    v_consulted_sources text[];
    v_successful_sources text[];
    v_failed_sources text[];
begin
    if p_run is null or jsonb_typeof(p_run) <> 'object' then
        raise exception 'invalid pipeline run final payload';
    end if;
    if p_run ->> 'status' not in ('succeeded', 'partial', 'failed') then
        raise exception 'invalid terminal pipeline run status';
    end if;

    select coalesce(array_agg(value order by ordinality), '{}') into v_requested_sources
      from jsonb_array_elements_text(coalesce(p_run -> 'requested_sources', '[]'))
           with ordinality as sources(value, ordinality);
    select coalesce(array_agg(value order by ordinality), '{}') into v_consulted_sources
      from jsonb_array_elements_text(coalesce(p_run -> 'consulted_sources', '[]'))
           with ordinality as sources(value, ordinality);
    select coalesce(array_agg(value order by ordinality), '{}') into v_successful_sources
      from jsonb_array_elements_text(coalesce(p_run -> 'successful_sources', '[]'))
           with ordinality as sources(value, ordinality);
    select coalesce(array_agg(value order by ordinality), '{}') into v_failed_sources
      from jsonb_array_elements_text(coalesce(p_run -> 'failed_sources', '[]'))
           with ordinality as sources(value, ordinality);

    update raw.pipeline_runs set
        status = p_run ->> 'status',
        completed_at = (p_run ->> 'completed_at')::timestamptz,
        requested_sources = v_requested_sources,
        consulted_sources = v_consulted_sources,
        successful_sources = v_successful_sources,
        failed_sources = v_failed_sources,
        requested_source_count = cardinality(v_requested_sources),
        successful_source_count = cardinality(v_successful_sources),
        failed_source_count = cardinality(v_failed_sources),
        records_received = coalesce((p_run ->> 'records_received')::integer, 0),
        candidates_generated = coalesce((p_run ->> 'candidates_generated')::integer, 0),
        signals_generated = coalesce((p_run ->> 'signals_generated')::integer, 0),
        signals_eligible = coalesce((p_run ->> 'signals_eligible')::integer, 0),
        signals_persisted = coalesce((p_run ->> 'signals_persisted')::integer, 0),
        error_stage = nullif(p_run ->> 'error_stage', ''),
        error_type = nullif(p_run ->> 'error_type', ''),
        error_message = nullif(p_run ->> 'error_message', '')
    where id = (p_run ->> 'run_id')::uuid;

    if not found then
        raise exception 'pipeline run audit not found';
    end if;
end;
$$;

revoke all on function public.create_pipeline_run_audit(jsonb)
    from public, anon, authenticated;
revoke all on function public.record_pipeline_collector_audit(jsonb)
    from public, anon, authenticated;
revoke all on function public.finalize_pipeline_run_audit(jsonb)
    from public, anon, authenticated;

grant execute on function public.create_pipeline_run_audit(jsonb) to service_role;
grant execute on function public.record_pipeline_collector_audit(jsonb) to service_role;
grant execute on function public.finalize_pipeline_run_audit(jsonb) to service_role;

comment on table raw.pipeline_runs is
    'Operational metadata for real-signal pipeline executions; never scientific event time.';
comment on column raw.pipeline_runs.started_at is
    'UTC wall-clock time when pipeline execution began; not Event.occurred_at.';
comment on column raw.pipeline_runs.completed_at is
    'UTC wall-clock time when pipeline execution ended; not persistence created_at.';
comment on column raw.fetch_runs.signals_generated is
    'Nullable because signal attribution to one collector is not always semantically safe.';
