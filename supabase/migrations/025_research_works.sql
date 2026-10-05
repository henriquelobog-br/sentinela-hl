-- 025_research_works.sql
-- ResearchWork V1 persistence contract: raw observations, canonical works,
-- source snapshots, empty curated topic map, citation SOT, curator publication
-- state, and service_role-only machine RPC. No public view. No topic seeds.

create table if not exists knowledge.research_topic_mapping_versions (
    mapping_version text primary key
        check (length(btrim(mapping_version)) > 0),
    created_at      timestamptz not null default now()
);

create table if not exists knowledge.research_topic_map (
    mapping_version     text not null
        references knowledge.research_topic_mapping_versions(mapping_version)
        on delete restrict,
    external_topic_id   text not null
        check (external_topic_id ~ '^T[0-9]+$'),
    external_topic_name text not null
        check (length(btrim(external_topic_name)) > 0),
    scientific_area     text not null
        check (length(btrim(scientific_area)) > 0),
    enabled             boolean not null,
    created_at          timestamptz not null default now(),
    primary key (mapping_version, external_topic_id)
);

create table if not exists knowledge.research_works (
    id                           uuid primary key default gen_random_uuid(),
    source                       text not null
        check (source = 'openalex'),
    source_work_id               text not null
        check (source_work_id ~ '^W[0-9]+$'),
    doi                          text
        check (doi is null or doi ~ '^10\.[0-9]{4,9}/\S+$'),
    title                        text not null
        check (length(btrim(title)) > 0),
    work_type                    text not null
        check (work_type in ('article', 'preprint')),
    publication_date             date,
    publication_year             integer
        check (publication_year is null or publication_year between 1000 and 9999),
    language                     text,
    primary_source_id            text,
    primary_source_name          text,
    is_open_access               boolean,
    oa_status                    text,
    source_created_date          date,
    source_updated_date          timestamptz,
    bibliographic_metadata_hash  text not null
        check (bibliographic_metadata_hash ~ '^[0-9a-f]{64}$'),
    first_observed_at            timestamptz not null,
    last_observed_at             timestamptz not null,
    citation_last_checked_at     timestamptz,
    created_at                   timestamptz not null default now(),
    updated_at                   timestamptz not null default now(),
    unique (source, source_work_id),
    check (first_observed_at <= last_observed_at)
);

create table if not exists knowledge.research_work_authors (
    research_work_id     uuid not null
        references knowledge.research_works(id) on delete cascade,
    position             integer not null
        check (position >= 1),
    display_name         text not null
        check (length(btrim(display_name)) > 0),
    openalex_author_id   text
        check (openalex_author_id is null or openalex_author_id ~ '^A[0-9]+$'),
    orcid                text,
    primary key (research_work_id, position)
);

create table if not exists knowledge.research_work_topics (
    research_work_id     uuid not null
        references knowledge.research_works(id) on delete cascade,
    external_topic_id    text not null
        check (external_topic_id ~ '^T[0-9]+$'),
    external_topic_name  text not null
        check (length(btrim(external_topic_name)) > 0),
    topic_rank           integer not null
        check (topic_rank between 1 and 3),
    topic_score          numeric
        check (topic_score is null or (topic_score >= 0 and topic_score <= 1)),
    is_primary           boolean not null,
    primary key (research_work_id, external_topic_id)
);

create unique index if not exists research_work_topics_one_primary_idx
    on knowledge.research_work_topics (research_work_id)
    where is_primary;

create unique index if not exists research_work_topics_rank_idx
    on knowledge.research_work_topics (research_work_id, topic_rank);

create table if not exists knowledge.research_citation_observations (
    id               uuid primary key default gen_random_uuid(),
    research_work_id uuid not null
        references knowledge.research_works(id) on delete cascade,
    source           text not null
        check (source = 'openalex'),
    citation_count   integer not null
        check (citation_count >= 0),
    observed_at      timestamptz not null,
    created_at       timestamptz not null default now()
);

create table if not exists knowledge.research_work_publication_state (
    research_work_id     uuid primary key
        references knowledge.research_works(id) on delete restrict,
    publication_approved boolean not null default false,
    approved_at          timestamptz,
    updated_at           timestamptz not null default now(),
    check (
        (publication_approved and approved_at is not null)
        or
        (not publication_approved and approved_at is null)
    )
);

create table if not exists raw.research_records (
    id                          uuid primary key default gen_random_uuid(),
    fetch_run_id                uuid not null
        references raw.fetch_runs(id) on delete restrict,
    source                      text not null
        check (length(btrim(source)) > 0),
    source_work_id              text not null
        check (length(btrim(source_work_id)) > 0),
    retrieved_at                timestamptz not null,
    mapping_version_requested   text,
    mapping_version_applied     text
        references knowledge.research_topic_mapping_versions(mapping_version)
        on delete restrict,
    relevance_status            text not null
        check (relevance_status in ('relevant', 'unmapped', 'not_evaluated')),
    mapped_topic_ids            text[],
    payload                     jsonb not null,
    payload_hash                text not null
        check (payload_hash ~ '^[0-9a-f]{64}$'),
    created_at                  timestamptz not null default now(),
    unique (fetch_run_id, source, source_work_id, payload_hash),
    check (
        (relevance_status = 'not_evaluated'
            and mapping_version_applied is null
            and mapped_topic_ids is null)
        or
        (relevance_status = 'unmapped'
            and mapping_version_applied is not null
            and mapped_topic_ids is not null
            and cardinality(mapped_topic_ids) = 0)
        or
        (relevance_status = 'relevant'
            and mapping_version_applied is not null
            and mapped_topic_ids is not null
            and cardinality(mapped_topic_ids) >= 1)
    )
);

create index if not exists research_works_doi_idx
    on knowledge.research_works (doi)
    where doi is not null;

create index if not exists research_works_publication_date_idx
    on knowledge.research_works (publication_date);

create index if not exists research_work_topics_external_topic_id_idx
    on knowledge.research_work_topics (external_topic_id);

create index if not exists research_citation_observations_work_observed_idx
    on knowledge.research_citation_observations (research_work_id, observed_at desc);

create or replace trigger trg_research_works_updated
    before update on knowledge.research_works
    for each row execute function public.set_updated_at();

create or replace trigger trg_research_work_publication_state_updated
    before update on knowledge.research_work_publication_state
    for each row execute function public.set_updated_at();

alter table knowledge.research_topic_mapping_versions enable row level security;
alter table knowledge.research_topic_map enable row level security;
alter table knowledge.research_works enable row level security;
alter table knowledge.research_work_authors enable row level security;
alter table knowledge.research_work_topics enable row level security;
alter table knowledge.research_citation_observations enable row level security;
alter table knowledge.research_work_publication_state enable row level security;
alter table raw.research_records enable row level security;

revoke all on table knowledge.research_topic_mapping_versions
    from public, anon, authenticated, service_role;
revoke all on table knowledge.research_topic_map
    from public, anon, authenticated, service_role;
revoke all on table knowledge.research_works
    from public, anon, authenticated, service_role;
revoke all on table knowledge.research_work_authors
    from public, anon, authenticated, service_role;
revoke all on table knowledge.research_work_topics
    from public, anon, authenticated, service_role;
revoke all on table knowledge.research_citation_observations
    from public, anon, authenticated, service_role;
revoke all on table knowledge.research_work_publication_state
    from public, anon, authenticated, service_role;
revoke all on table raw.research_records
    from public, anon, authenticated, service_role;

comment on table raw.research_records is
    'Append-only OpenAlex source observations. No canonical FK.';
comment on table knowledge.research_works is
    'Canonical ResearchWork identity UNIQUE(source, source_work_id). DOI is secondary and non-unique.';
comment on table knowledge.research_work_publication_state is
    'Curator-owned publication gate. Missing row means unpublished. Machine RPC must not write this table.';
comment on table knowledge.research_topic_mapping_versions is
    'Append-only curated mapping version identities. Empty until TM1.';
comment on table knowledge.research_citation_observations is
    'Authoritative citation time series. No latest-count cache on research_works.';

create or replace function public.persist_research_work_batch(
    p_run_id uuid,
    p_items jsonb
)
returns table (
    item_index integer,
    source text,
    source_work_id text,
    raw_disposition text,
    canonical_disposition text,
    temporal_disposition text,
    citation_disposition text,
    relevance_status text,
    identity_conflict boolean,
    research_work_id uuid,
    raw_record_id uuid,
    error_code text
)
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $$
declare
    v_item jsonb;
    v_index integer := 0;
    v_raw jsonb;
    v_norm jsonb;
    v_rel jsonb;
    v_fetch_id uuid;
    v_fetch_run raw.fetch_runs%rowtype;
    v_retrieved_at timestamptz;
    v_payload jsonb;
    v_payload_hash text;
    v_map_req text;
    v_map_applied text;
    v_rel_status text;
    v_mapped_ids text[];
    v_raw_id uuid;
    v_raw_inserted boolean;
    v_work knowledge.research_works%rowtype;
    v_created boolean;
    v_hash text;
    v_title text;
    v_work_type text;
    v_doi text;
    v_authors jsonb;
    v_topics jsonb;
    v_author jsonb;
    v_topic jsonb;
    v_positions integer[];
    v_author_names text[];
    v_author_aids text[];
    v_author_orcids text[];
    v_topic_ids text[];
    v_ranks integer[];
    v_topic_names text[];
    v_topic_scores numeric[];
    v_topic_primary boolean[];
    v_primary_count integer;
    v_position integer;
    v_rank integer;
    v_score numeric;
    v_pub_date date;
    v_pub_year integer;
    v_src_created date;
    v_src_updated timestamptz;
    v_oa boolean;
    v_i integer;
    v_temporal_ok boolean;
    v_citation_present boolean;
    v_citation_count integer;
    v_latest_count integer;
    v_latest_at timestamptz;
    v_conflict boolean;
    v_child_ok boolean;
begin
    if p_run_id is null then
        raise exception 'research persistence requires p_run_id';
    end if;
    if p_items is null or jsonb_typeof(p_items) <> 'array' then
        raise exception 'research work payload must be an array';
    end if;
    if jsonb_array_length(p_items) > 500 then
        raise exception 'research work batch exceeds 500 items';
    end if;

    for v_item in select value from jsonb_array_elements(p_items)
    loop
        v_index := v_index + 1;
        item_index := v_index;
        source := null;
        source_work_id := null;
        raw_disposition := 'rejected';
        canonical_disposition := 'not_applicable';
        temporal_disposition := 'not_applicable';
        citation_disposition := 'not_applicable';
        relevance_status := 'not_evaluated';
        identity_conflict := false;
        research_work_id := null;
        raw_record_id := null;
        error_code := null;

        begin
            if jsonb_typeof(v_item) <> 'object' then
                error_code := 'malformed_envelope';
                return next;
                continue;
            end if;

            v_raw := v_item -> 'raw';
            v_norm := v_item -> 'normalized';
            v_rel := v_item -> 'relevance';
            if jsonb_typeof(v_raw) <> 'object' then
                error_code := 'malformed_envelope';
                return next;
                continue;
            end if;

            source := nullif(btrim(v_raw ->> 'source'), '');
            source_work_id := nullif(btrim(v_raw ->> 'source_work_id'), '');
            if source is null or source_work_id is null then
                error_code := 'malformed_envelope';
                return next;
                continue;
            end if;

            begin
                v_fetch_id := (v_raw ->> 'fetch_run_id')::uuid;
            exception
                when invalid_text_representation then
                    error_code := 'malformed_envelope';
                    return next;
                    continue;
            end;
            if v_fetch_id is null then
                error_code := 'malformed_envelope';
                return next;
                continue;
            end if;
            if jsonb_typeof(v_raw -> 'retrieved_at') is distinct from 'string' then
                error_code := 'invalid_retrieved_at';
                return next;
                continue;
            end if;
            begin
                v_retrieved_at := (v_raw ->> 'retrieved_at')::timestamptz;
            exception
                when invalid_text_representation
                    or invalid_datetime_format
                    or datetime_field_overflow
                    or invalid_time_zone_displacement_value then
                    error_code := 'invalid_retrieved_at';
                    return next;
                    continue;
            end;
            if v_retrieved_at is null then
                error_code := 'invalid_retrieved_at';
                return next;
                continue;
            end if;

            v_payload := v_raw -> 'payload';
            v_payload_hash := v_raw ->> 'payload_hash';
            if jsonb_typeof(v_payload) <> 'object'
                or v_payload_hash is null
                or v_payload_hash !~ '^[0-9a-f]{64}$'
            then
                error_code := 'malformed_envelope';
                return next;
                continue;
            end if;

            select * into v_fetch_run
            from raw.fetch_runs
            where id = v_fetch_id;
            if not found or v_fetch_run.pipeline_run_id is distinct from p_run_id then
                error_code := 'fetch_run_mismatch';
                return next;
                continue;
            end if;

            if jsonb_typeof(v_rel) = 'object' then
                v_map_req := nullif(btrim(v_rel ->> 'mapping_version_requested'), '');
                v_map_applied := nullif(btrim(v_rel ->> 'mapping_version_applied'), '');
                v_rel_status := coalesce(nullif(btrim(v_rel ->> 'relevance_status'), ''), 'not_evaluated');
                if v_rel ? 'mapped_topic_ids' and jsonb_typeof(v_rel -> 'mapped_topic_ids') = 'array' then
                    select coalesce(array_agg(value order by value), '{}')
                      into v_mapped_ids
                      from jsonb_array_elements_text(v_rel -> 'mapped_topic_ids') as t(value);
                else
                    v_mapped_ids := null;
                end if;
            else
                v_map_req := null;
                v_map_applied := null;
                v_rel_status := 'not_evaluated';
                v_mapped_ids := null;
            end if;

            if v_rel_status not in ('relevant', 'unmapped', 'not_evaluated') then
                error_code := 'invalid_relevance';
                return next;
                continue;
            end if;

            if v_map_applied is not null and not exists (
                select 1
                from knowledge.research_topic_mapping_versions
                where mapping_version = v_map_applied
            ) then
                error_code := 'unknown_mapping_version_applied';
                return next;
                continue;
            end if;

            if v_rel_status = 'not_evaluated' then
                v_map_applied := null;
                v_mapped_ids := null;
            elsif v_rel_status = 'unmapped' then
                if v_map_applied is null then
                    v_rel_status := 'not_evaluated';
                    v_mapped_ids := null;
                else
                    v_mapped_ids := coalesce(v_mapped_ids, '{}');
                    if cardinality(v_mapped_ids) <> 0 then
                        error_code := 'invalid_relevance';
                        return next;
                        continue;
                    end if;
                end if;
            else
                if v_map_applied is null or v_mapped_ids is null or cardinality(v_mapped_ids) < 1 then
                    error_code := 'invalid_relevance';
                    return next;
                    continue;
                end if;
            end if;

            relevance_status := v_rel_status;

            insert into raw.research_records (
                fetch_run_id, source, source_work_id, retrieved_at,
                mapping_version_requested, mapping_version_applied,
                relevance_status, mapped_topic_ids, payload, payload_hash
            ) values (
                v_fetch_id, source, source_work_id, v_retrieved_at,
                v_map_req, v_map_applied, v_rel_status, v_mapped_ids,
                v_payload, v_payload_hash
            )
            ON CONFLICT ON CONSTRAINT research_records_fetch_run_id_source_source_work_id_payload_key DO NOTHING
            returning id into v_raw_id;

            v_raw_inserted := v_raw_id is not null;
            if not v_raw_inserted then
                select id into v_raw_id
                from raw.research_records
                where fetch_run_id = v_fetch_id
                  and raw.research_records.source = persist_research_work_batch.source
                  and raw.research_records.source_work_id = persist_research_work_batch.source_work_id
                  and payload_hash = v_payload_hash;
            end if;

            raw_record_id := v_raw_id;
            raw_disposition := case when v_raw_inserted then 'inserted' else 'existing' end;

            if jsonb_typeof(v_norm) is distinct from 'object' then
                canonical_disposition := 'rejected';
                error_code := 'canonical_ineligible';
                return next;
                continue;
            end if;

            if coalesce(v_norm ->> 'source', source) is distinct from 'openalex'
                or coalesce(v_norm ->> 'source_work_id', source_work_id) is distinct from source_work_id
                or source_work_id !~ '^W[0-9]+$'
            then
                canonical_disposition := 'rejected';
                error_code := 'invalid_identity';
                return next;
                continue;
            end if;

            v_title := nullif(btrim(v_norm ->> 'title'), '');
            v_work_type := nullif(btrim(v_norm ->> 'work_type'), '');
            v_hash := v_norm ->> 'bibliographic_metadata_hash';
            v_doi := nullif(btrim(v_norm ->> 'doi'), '');
            if v_title is null then
                canonical_disposition := 'rejected';
                error_code := 'missing_title';
                return next;
                continue;
            end if;
            if v_work_type is null or v_work_type not in ('article', 'preprint') then
                canonical_disposition := 'rejected';
                error_code := 'unsupported_type';
                return next;
                continue;
            end if;
            if v_hash is null or v_hash !~ '^[0-9a-f]{64}$' then
                canonical_disposition := 'rejected';
                error_code := 'invalid_hash';
                return next;
                continue;
            end if;
            if v_doi is not null and v_doi !~ '^10\.[0-9]{4,9}/\S+$' then
                canonical_disposition := 'rejected';
                error_code := 'invalid_doi';
                return next;
                continue;
            end if;

            v_authors := coalesce(v_norm -> 'authors', '[]'::jsonb);
            v_topics := coalesce(v_norm -> 'topics', '[]'::jsonb);
            if jsonb_typeof(v_authors) <> 'array' or jsonb_typeof(v_topics) <> 'array' then
                canonical_disposition := 'rejected';
                error_code := 'invalid_children';
                return next;
                continue;
            end if;

            v_positions := '{}';
            v_author_names := '{}';
            v_author_aids := '{}';
            v_author_orcids := '{}';
            v_child_ok := true;
            for v_author in select value from jsonb_array_elements(v_authors)
            loop
                if jsonb_typeof(v_author) <> 'object'
                    or jsonb_typeof(v_author -> 'position') is distinct from 'number'
                    or nullif(btrim(v_author ->> 'display_name'), '') is null
                    or (
                        v_author ->> 'openalex_author_id' is not null
                        and btrim(v_author ->> 'openalex_author_id') <> ''
                        and btrim(v_author ->> 'openalex_author_id') !~ '^A[0-9]+$'
                    )
                then
                    v_child_ok := false;
                    exit;
                end if;
                begin
                    v_position := (v_author ->> 'position')::integer;
                exception
                    when invalid_text_representation or numeric_value_out_of_range then
                        v_child_ok := false;
                end;
                if not v_child_ok
                    or v_position is null
                    or v_position < 1
                    or v_position = any (v_positions)
                then
                    v_child_ok := false;
                    exit;
                end if;
                v_positions := array_append(v_positions, v_position);
                v_author_names := array_append(v_author_names, btrim(v_author ->> 'display_name'));
                v_author_aids := array_append(
                    v_author_aids, nullif(btrim(v_author ->> 'openalex_author_id'), '')
                );
                v_author_orcids := array_append(
                    v_author_orcids, nullif(btrim(v_author ->> 'orcid'), '')
                );
            end loop;

            v_topic_ids := '{}';
            v_ranks := '{}';
            v_topic_names := '{}';
            v_topic_scores := '{}';
            v_topic_primary := '{}';
            v_primary_count := 0;
            for v_topic in select value from jsonb_array_elements(v_topics)
            loop
                if jsonb_typeof(v_topic) <> 'object'
                    or coalesce(v_topic ->> 'external_topic_id', '') !~ '^T[0-9]+$'
                    or nullif(btrim(v_topic ->> 'external_topic_name'), '') is null
                    or jsonb_typeof(v_topic -> 'topic_rank') is distinct from 'number'
                    or jsonb_typeof(v_topic -> 'is_primary') is distinct from 'boolean'
                    or (v_topic ->> 'external_topic_id') = any (v_topic_ids)
                then
                    v_child_ok := false;
                    exit;
                end if;
                begin
                    v_rank := (v_topic ->> 'topic_rank')::integer;
                exception
                    when invalid_text_representation or numeric_value_out_of_range then
                        v_child_ok := false;
                end;
                if not v_child_ok
                    or v_rank is null
                    or v_rank not between 1 and 3
                    or v_rank = any (v_ranks)
                then
                    v_child_ok := false;
                    exit;
                end if;
                v_score := null;
                if v_topic ? 'topic_score'
                    and jsonb_typeof(v_topic -> 'topic_score') is distinct from 'null'
                then
                    if jsonb_typeof(v_topic -> 'topic_score') is distinct from 'number' then
                        v_child_ok := false;
                        exit;
                    end if;
                    begin
                        v_score := (v_topic ->> 'topic_score')::numeric;
                    exception
                        when invalid_text_representation or numeric_value_out_of_range then
                            v_child_ok := false;
                    end;
                    if not v_child_ok
                        or v_score is null
                        or v_score < 0
                        or v_score > 1
                    then
                        v_child_ok := false;
                        exit;
                    end if;
                end if;
                if (v_topic -> 'is_primary') = 'true'::jsonb then
                    v_primary_count := v_primary_count + 1;
                end if;
                v_topic_ids := array_append(v_topic_ids, v_topic ->> 'external_topic_id');
                v_ranks := array_append(v_ranks, v_rank);
                v_topic_names := array_append(v_topic_names, btrim(v_topic ->> 'external_topic_name'));
                v_topic_scores := array_append(v_topic_scores, v_score);
                v_topic_primary := array_append(
                    v_topic_primary, (v_topic -> 'is_primary') = 'true'::jsonb
                );
            end loop;
            if not v_child_ok or v_primary_count > 1 then
                canonical_disposition := 'rejected';
                error_code := 'invalid_children';
                return next;
                continue;
            end if;

            v_citation_present := v_norm ? 'cited_by_count'
                and jsonb_typeof(v_norm -> 'cited_by_count') is distinct from 'null';
            if not v_citation_present then
                citation_disposition := 'missing';
                v_citation_count := null;
            elsif jsonb_typeof(v_norm -> 'cited_by_count') is distinct from 'number' then
                citation_disposition := 'invalid';
                v_citation_count := null;
            else
                begin
                    v_citation_count := (v_norm ->> 'cited_by_count')::integer;
                exception
                    when invalid_text_representation or numeric_value_out_of_range then
                        citation_disposition := 'invalid';
                        v_citation_count := null;
                end;
                if citation_disposition is distinct from 'invalid'
                    and (v_citation_count is null or v_citation_count < 0)
                then
                    citation_disposition := 'invalid';
                    v_citation_count := null;
                end if;
            end if;

            v_pub_date := null;
            v_pub_year := null;
            v_src_created := null;
            v_src_updated := null;
            v_oa := null;
            v_temporal_ok := true;
            if v_norm ? 'publication_date'
                and jsonb_typeof(v_norm -> 'publication_date') is distinct from 'null'
            then
                if jsonb_typeof(v_norm -> 'publication_date') is distinct from 'string' then
                    v_temporal_ok := false;
                else
                    begin
                        v_pub_date := (v_norm ->> 'publication_date')::date;
                    exception
                        when invalid_text_representation
                            or invalid_datetime_format
                            or datetime_field_overflow
                            or invalid_time_zone_displacement_value then
                            v_temporal_ok := false;
                    end;
                end if;
            end if;
            if v_temporal_ok
                and v_norm ? 'publication_year'
                and jsonb_typeof(v_norm -> 'publication_year') is distinct from 'null'
            then
                if jsonb_typeof(v_norm -> 'publication_year') is distinct from 'number' then
                    v_temporal_ok := false;
                else
                    begin
                        v_pub_year := (v_norm ->> 'publication_year')::integer;
                    exception
                        when invalid_text_representation or numeric_value_out_of_range then
                            v_temporal_ok := false;
                    end;
                    if v_temporal_ok
                        and (v_pub_year is null or v_pub_year < 1000 or v_pub_year > 9999)
                    then
                        v_temporal_ok := false;
                    end if;
                end if;
            end if;
            if v_temporal_ok
                and v_norm ? 'source_created_date'
                and jsonb_typeof(v_norm -> 'source_created_date') is distinct from 'null'
            then
                if jsonb_typeof(v_norm -> 'source_created_date') is distinct from 'string' then
                    v_temporal_ok := false;
                else
                    begin
                        v_src_created := (v_norm ->> 'source_created_date')::date;
                    exception
                        when invalid_text_representation
                            or invalid_datetime_format
                            or datetime_field_overflow
                            or invalid_time_zone_displacement_value then
                            v_temporal_ok := false;
                    end;
                end if;
            end if;
            if v_temporal_ok
                and v_norm ? 'source_updated_date'
                and jsonb_typeof(v_norm -> 'source_updated_date') is distinct from 'null'
            then
                if jsonb_typeof(v_norm -> 'source_updated_date') is distinct from 'string' then
                    v_temporal_ok := false;
                else
                    begin
                        v_src_updated := (v_norm ->> 'source_updated_date')::timestamptz;
                    exception
                        when invalid_text_representation
                            or invalid_datetime_format
                            or datetime_field_overflow
                            or invalid_time_zone_displacement_value then
                            v_temporal_ok := false;
                    end;
                end if;
            end if;
            if not v_temporal_ok then
                canonical_disposition := 'rejected';
                error_code := 'invalid_temporal';
                return next;
                continue;
            end if;
            if jsonb_typeof(v_norm -> 'is_open_access') = 'boolean' then
                v_oa := (v_norm -> 'is_open_access') = 'true'::jsonb;
            end if;

            insert into knowledge.research_works (
                source, source_work_id, doi, title, work_type,
                publication_date, publication_year, language,
                primary_source_id, primary_source_name,
                is_open_access, oa_status,
                source_created_date, source_updated_date,
                bibliographic_metadata_hash,
                first_observed_at, last_observed_at
            ) values (
                'openalex', source_work_id, v_doi, v_title, v_work_type,
                v_pub_date,
                v_pub_year,
                nullif(v_norm ->> 'language', ''),
                nullif(v_norm ->> 'primary_source_id', ''),
                nullif(v_norm ->> 'primary_source_name', ''),
                v_oa,
                nullif(v_norm ->> 'oa_status', ''),
                v_src_created,
                v_src_updated,
                v_hash, v_retrieved_at, v_retrieved_at
            )
            ON CONFLICT ON CONSTRAINT research_works_source_source_work_id_key DO NOTHING
            returning * into v_work;
            v_created := found;

            if not v_created then
                select * into v_work
                from knowledge.research_works
                where knowledge.research_works.source = 'openalex'
                  and knowledge.research_works.source_work_id = persist_research_work_batch.source_work_id
                for update;
            end if;

            research_work_id := v_work.id;

            if v_created then
                temporal_disposition := 'fresh';
                canonical_disposition := 'inserted';
                for v_i in 1 .. coalesce(cardinality(v_positions), 0)
                loop
                    insert into knowledge.research_work_authors (
                        research_work_id, position, display_name, openalex_author_id, orcid
                    ) values (
                        v_work.id,
                        v_positions[v_i],
                        v_author_names[v_i],
                        v_author_aids[v_i],
                        v_author_orcids[v_i]
                    );
                end loop;

                for v_i in 1 .. coalesce(cardinality(v_topic_ids), 0)
                loop
                    insert into knowledge.research_work_topics (
                        research_work_id, external_topic_id, external_topic_name,
                        topic_rank, topic_score, is_primary
                    ) values (
                        v_work.id,
                        v_topic_ids[v_i],
                        v_topic_names[v_i],
                        v_ranks[v_i],
                        v_topic_scores[v_i],
                        v_topic_primary[v_i]
                    );
                end loop;
            elsif v_retrieved_at < v_work.last_observed_at then
                temporal_disposition := 'stale';
                canonical_disposition := 'unchanged';
            elsif v_retrieved_at = v_work.last_observed_at
                and v_hash <> v_work.bibliographic_metadata_hash then
                temporal_disposition := 'conflict';
                canonical_disposition := 'unchanged';
            elsif v_retrieved_at = v_work.last_observed_at then
                temporal_disposition := 'same_time';
                canonical_disposition := 'observed_existing';
            else
                temporal_disposition := 'fresh';
                if v_hash is distinct from v_work.bibliographic_metadata_hash then
                    update knowledge.research_works set
                        doi = v_doi,
                        title = v_title,
                        work_type = v_work_type,
                        publication_date = v_pub_date,
                        publication_year = v_pub_year,
                        language = nullif(v_norm ->> 'language', ''),
                        primary_source_id = nullif(v_norm ->> 'primary_source_id', ''),
                        primary_source_name = nullif(v_norm ->> 'primary_source_name', ''),
                        is_open_access = v_oa,
                        oa_status = nullif(v_norm ->> 'oa_status', ''),
                        source_created_date = v_src_created,
                        source_updated_date = v_src_updated,
                        bibliographic_metadata_hash = v_hash,
                        last_observed_at = v_retrieved_at
                    where id = v_work.id;

                    delete from knowledge.research_work_authors
                    where knowledge.research_work_authors.research_work_id = v_work.id;
                    for v_i in 1 .. coalesce(cardinality(v_positions), 0)
                    loop
                        insert into knowledge.research_work_authors (
                            research_work_id, position, display_name, openalex_author_id, orcid
                        ) values (
                            v_work.id,
                            v_positions[v_i],
                            v_author_names[v_i],
                            v_author_aids[v_i],
                            v_author_orcids[v_i]
                        );
                    end loop;

                    delete from knowledge.research_work_topics
                    where knowledge.research_work_topics.research_work_id = v_work.id;
                    for v_i in 1 .. coalesce(cardinality(v_topic_ids), 0)
                    loop
                        insert into knowledge.research_work_topics (
                            research_work_id, external_topic_id, external_topic_name,
                            topic_rank, topic_score, is_primary
                        ) values (
                            v_work.id,
                            v_topic_ids[v_i],
                            v_topic_names[v_i],
                            v_ranks[v_i],
                            v_topic_scores[v_i],
                            v_topic_primary[v_i]
                        );
                    end loop;

                    canonical_disposition := 'updated';
                else
                    update knowledge.research_works
                    set last_observed_at = v_retrieved_at
                    where id = v_work.id;
                    canonical_disposition := 'observed_existing';
                end if;
            end if;

            if v_doi is not null then
                select exists (
                    select 1
                    from knowledge.research_works other
                    where other.doi = v_doi
                      and other.id <> v_work.id
                ) into v_conflict;
                identity_conflict := coalesce(v_conflict, false);
            end if;

            if citation_disposition = 'missing' then
                null;
            elsif citation_disposition = 'invalid' then
                null;
            else
                select citation_count, observed_at
                  into v_latest_count, v_latest_at
                  from knowledge.research_citation_observations
                 where knowledge.research_citation_observations.research_work_id = v_work.id
                 order by observed_at desc, created_at desc, id desc
                 limit 1;

                if v_work.citation_last_checked_at is not null
                    and v_retrieved_at < v_work.citation_last_checked_at then
                    citation_disposition := 'stale';
                elsif v_work.citation_last_checked_at is not null
                    and v_retrieved_at = v_work.citation_last_checked_at then
                    if v_latest_count is not distinct from v_citation_count then
                        citation_disposition := 'unchanged';
                    else
                        citation_disposition := 'conflict';
                    end if;
                elsif v_latest_count is null then
                    insert into knowledge.research_citation_observations (
                        research_work_id, source, citation_count, observed_at
                    ) values (
                        v_work.id, 'openalex', v_citation_count, v_retrieved_at
                    );
                    update knowledge.research_works
                    set citation_last_checked_at = v_retrieved_at
                    where id = v_work.id;
                    citation_disposition := 'first_observation';
                elsif v_latest_count = v_citation_count then
                    update knowledge.research_works
                    set citation_last_checked_at = v_retrieved_at
                    where id = v_work.id;
                    citation_disposition := 'unchanged';
                else
                    insert into knowledge.research_citation_observations (
                        research_work_id, source, citation_count, observed_at
                    ) values (
                        v_work.id, 'openalex', v_citation_count, v_retrieved_at
                    );
                    update knowledge.research_works
                    set citation_last_checked_at = v_retrieved_at
                    where id = v_work.id;
                    citation_disposition := 'changed';
                end if;
            end if;

            return next;
        exception
            when others then
                raw_disposition := 'failed';
                canonical_disposition := 'failed';
                temporal_disposition := 'not_applicable';
                citation_disposition := 'not_applicable';
                identity_conflict := false;
                research_work_id := null;
                raw_record_id := null;
                error_code := 'unexpected_sql';
                return next;
        end;
    end loop;
end;
$$;

revoke all on function public.persist_research_work_batch(uuid, jsonb)
    from public, anon, authenticated;
grant execute on function public.persist_research_work_batch(uuid, jsonb)
    to service_role;

comment on function public.persist_research_work_batch(uuid, jsonb) is
    'Machine-only ResearchWork persistence. Does not write publication state. Does not parse OpenAlex JSON.';
