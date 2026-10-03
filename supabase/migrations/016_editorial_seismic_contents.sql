-- 016_editorial_seismic_contents.sql
-- Persistencia versionada da projecao Editorial Sismologia.
-- Estritamente aditiva: nao altera Events nem ResearcherSignals existentes.

create schema if not exists editorial;

revoke all on schema editorial from public, anon, authenticated;

create table if not exists editorial.seismic_contents (
    id                    uuid primary key default gen_random_uuid(),
    event_id              uuid not null
        references knowledge.events(id) on delete restrict,
    editorial_version     text not null
        check (length(btrim(editorial_version)) > 0),
    locale                text not null
        check (length(btrim(locale)) > 0),

    editorial_title       text not null
        check (char_length(editorial_title) <= 120),
    editorial_subtitle    text not null
        check (char_length(editorial_subtitle) <= 180),
    editorial_summary     text not null
        check (char_length(editorial_summary) <= 800),
    seo_title             text not null
        check (char_length(seo_title) <= 70),
    seo_description       text not null
        check (char_length(seo_description) <= 180),
    seo_keywords          text[] not null default '{}'
        check (cardinality(seo_keywords) <= 8),

    input_facts_signature text not null
        check (input_facts_signature ~ '^[0-9a-f]{64}$'),
    generated_at          timestamptz not null,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),

    unique (event_id, editorial_version, locale)
);

create index if not exists seismic_contents_event_id_idx
    on editorial.seismic_contents (event_id);

create or replace trigger trg_seismic_contents_updated
    before update on editorial.seismic_contents
    for each row execute function public.set_updated_at();

alter table editorial.seismic_contents enable row level security;

revoke all on editorial.seismic_contents from public, anon, authenticated;
grant usage on schema editorial to service_role;
grant select, insert, update on editorial.seismic_contents to service_role;

comment on table editorial.seismic_contents is
    'Versioned Seismic Editorial content derived from canonical Events.';
