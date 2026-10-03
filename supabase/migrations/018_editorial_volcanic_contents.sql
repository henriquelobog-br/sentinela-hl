-- 018_editorial_volcanic_contents.sql
-- Persistencia versionada da projecao Editorial Vulcanologia.
-- Estritamente aditiva: nao altera Events, Sismologia ou ResearcherSignals.

create schema if not exists editorial;

revoke all on schema editorial from public, anon, authenticated;

create table if not exists editorial.volcanic_contents (
    id                      uuid primary key default gen_random_uuid(),
    editorial_group_id      text not null
        check (length(btrim(editorial_group_id)) > 0),
    representative_event_id uuid not null
        references knowledge.events(id) on delete restrict,
    member_event_ids        uuid[] not null
        check (cardinality(member_event_ids) > 0)
        check (array_position(member_event_ids, null) is null)
        check (representative_event_id = any(member_event_ids)),
    volcano_name            text not null
        check (length(btrim(volcano_name)) > 0),
    volcano_number          text null
        check (volcano_number is null or length(btrim(volcano_number)) > 0),
    editorial_version       text not null
        check (length(btrim(editorial_version)) > 0),
    locale                  text not null
        check (length(btrim(locale)) > 0),

    editorial_title         text not null
        check (char_length(editorial_title) <= 120),
    editorial_subtitle      text not null
        check (char_length(editorial_subtitle) <= 180),
    editorial_summary       text not null
        check (char_length(editorial_summary) <= 800),
    seo_title               text not null
        check (char_length(seo_title) <= 70),
    seo_description         text not null
        check (char_length(seo_description) <= 180),
    seo_keywords            text[] not null default '{}'
        check (cardinality(seo_keywords) <= 8),

    input_facts_signature   text not null
        check (input_facts_signature ~ '^[0-9a-f]{64}$'),
    generated_at            timestamptz not null,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),

    unique (editorial_group_id, editorial_version, locale)
);

create index if not exists volcanic_contents_representative_event_id_idx
    on editorial.volcanic_contents (representative_event_id);

create index if not exists volcanic_contents_member_event_ids_idx
    on editorial.volcanic_contents using gin (member_event_ids);

create or replace trigger trg_volcanic_contents_updated
    before update on editorial.volcanic_contents
    for each row execute function public.set_updated_at();

alter table editorial.volcanic_contents enable row level security;

revoke all on editorial.volcanic_contents from public, anon, authenticated;
grant usage on schema editorial to service_role;
grant select, insert, update on editorial.volcanic_contents to service_role;

comment on table editorial.volcanic_contents is
    'Versioned Volcanic Editorial content derived from canonical Event groups.';

comment on column editorial.volcanic_contents.member_event_ids is
    'Canonical Event membership. PostgreSQL cannot enforce element FKs on UUID arrays; membership integrity is validated by the application contract.';
