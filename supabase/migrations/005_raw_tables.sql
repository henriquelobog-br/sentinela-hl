-- 005_raw_tables.sql — Sentinela HL — BANCO BRUTO
-- Apenas tabelas (sem indices/triggers — esses vem em 007/008).

create table if not exists raw.sources (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  kind        public.source_kind not null,
  url         text,
  reliability public.reliability_tier not null default 'unknown',
  config      jsonb not null default '{}'::jsonb,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
comment on column raw.sources.config is 'Parametros do feed/API. NUNCA armazenar segredos aqui.';

create table if not exists raw.fetch_runs (
  id              uuid primary key default gen_random_uuid(),
  source_id       uuid references raw.sources(id) on delete cascade,
  status          public.fetch_status not null default 'running',
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  items_found     integer not null default 0,
  items_new       integer not null default 0,
  items_duplicate integer not null default 0,
  error           text,
  log             jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

create table if not exists raw.items (
  id                 uuid primary key default gen_random_uuid(),
  source_id          uuid not null references raw.sources(id) on delete cascade,
  fetch_run_id       uuid references raw.fetch_runs(id) on delete set null,
  external_id        text,
  url                text,
  title              text,
  raw_payload        jsonb,
  normalized_content text,
  content_hash       text,
  published_at       timestamptz,
  collected_at       timestamptz not null default now(),
  pipeline_status    public.pipeline_status not null default 'collected',
  duplicate_of       uuid references raw.items(id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
