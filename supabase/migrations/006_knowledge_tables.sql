-- 006_knowledge_tables.sql — Sentinela HL — BANCO DE CONHECIMENTO
-- Apenas tabelas (sem indices/triggers).

create table if not exists knowledge.claims (
  id                    uuid primary key default gen_random_uuid(),
  raw_item_id           uuid not null references raw.items(id) on delete restrict,
  statement             text not null,
  epistemic_status      public.epistemic_status,
  confidence_score      numeric(4,3) check (confidence_score between 0 and 1),
  source_reliability    public.reliability_tier not null default 'unknown',
  category              text,
  country               text,
  scientific_area       text,
  entities              jsonb not null default '[]'::jsonb,
  keywords              text[] not null default '{}',
  pipeline_status       public.pipeline_status not null default 'in_filter',
  requires_human_review boolean not null default false,
  review_reason         text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create table if not exists knowledge.classifications (
  id         uuid primary key default gen_random_uuid(),
  claim_id   uuid not null references knowledge.claims(id) on delete cascade,
  filter     public.filter_key not null,
  result     public.filter_result not null,
  rationale  text,
  detail     jsonb not null default '{}'::jsonb,
  automated  boolean not null default true,
  model      text,
  created_at timestamptz not null default now()
);

create table if not exists knowledge.events (
  id                    uuid primary key default gen_random_uuid(),
  primary_claim_id      uuid references knowledge.claims(id) on delete set null,
  title                 text not null,
  summary               text,
  epistemic_status      public.epistemic_status not null,
  confidence_score      numeric(4,3) check (confidence_score between 0 and 1),
  category              text,
  country               text,
  scientific_area       text,
  entities              jsonb not null default '[]'::jsonb,
  keywords              text[] not null default '{}',
  evidence              jsonb not null default '[]'::jsonb,
  occurred_at           timestamptz,
  pipeline_status       public.pipeline_status not null default 'validated',
  requires_human_review boolean not null default false,
  review_decision       public.review_decision not null default 'pending',
  validated_by          text,
  validated_at          timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create table if not exists knowledge.contradictions (
  id                   uuid primary key default gen_random_uuid(),
  claim_id             uuid not null references knowledge.claims(id) on delete cascade,
  conflicting_event_id uuid not null references knowledge.events(id) on delete cascade,
  kind                 text not null default 'direct',
  similarity           numeric(5,4),
  detail               text,
  resolved             boolean not null default false,
  resolution           text,
  created_at           timestamptz not null default now()
);

create table if not exists knowledge.bulletins (
  id            uuid primary key default gen_random_uuid(),
  bulletin_date date not null unique,
  status        public.bulletin_status not null default 'draft',
  title         text,
  body          text,
  channel       text not null default 'whatsapp',
  approved_by   text,
  sent_at       timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists knowledge.bulletin_events (
  bulletin_id uuid not null references knowledge.bulletins(id) on delete cascade,
  event_id    uuid not null references knowledge.events(id) on delete restrict,
  position    integer not null default 0,
  primary key (bulletin_id, event_id)
);
