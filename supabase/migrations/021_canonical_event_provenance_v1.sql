-- 021_canonical_event_provenance_v1.sql
-- Canonical Event provenance, revision history, linked signals and publication gate.
-- Additive: no ResearcherSignal backfill and no fabricated legacy Events.

create schema if not exists provenance;
revoke all on schema provenance from public, anon, authenticated, service_role;

alter table knowledge.events
    add column if not exists publication_approved boolean not null default false,
    add column if not exists publication_approved_by text,
    add column if not exists publication_approved_at timestamptz;

alter table knowledge.events
    drop constraint if exists events_publication_approval_check,
    add constraint events_publication_approval_check check (
        (publication_approved and publication_approved_at is not null
            and publication_approved_by is not null)
        or
        (not publication_approved and publication_approved_at is null
            and publication_approved_by is null)
    );

-- Preserve all preexisting Event consumer behavior (including the seven rows in
-- v_seismic_events and bulletin reads). Future Events remain unpublished until
-- explicitly approved. This is publication-state initialization, not lineage
-- backfill and does not fabricate any Event or Signal membership.
update knowledge.events
set publication_approved = true,
    publication_approved_by = 'migration_021_existing_public_contract',
    publication_approved_at = coalesce(updated_at, created_at, now())
where not publication_approved;

create table if not exists provenance.run_manifests (
    run_id                 uuid primary key
        references raw.pipeline_runs(id) on delete restrict,
    manifest_version       text not null default 'canonical-provenance-v1'
        check (manifest_version = 'canonical-provenance-v1'),
    stage                  text not null default 'started'
        check (stage in (
            'started', 'events_persisted', 'signals_persisted',
            'finalized', 'failed'
        )),
    accepted_event_count   integer not null default 0 check (accepted_event_count >= 0),
    rejected_event_count   integer not null default 0 check (rejected_event_count >= 0),
    persisted_signal_count integer not null default 0 check (persisted_signal_count >= 0),
    versions               jsonb not null default '{}'::jsonb
        check (jsonb_typeof(versions) = 'object'),
    commit_state           text not null default 'known'
        check (commit_state in ('known', 'ambiguous')),
    manifest_hash          text check (
        manifest_hash is null or manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    error_type             text check (char_length(coalesce(error_type, '')) <= 120),
    error_message          text check (char_length(coalesce(error_message, '')) <= 512),
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now(),
    finalized_at           timestamptz,
    check (
        (stage in ('finalized', 'failed') and finalized_at is not null)
        or (stage not in ('finalized', 'failed') and finalized_at is null)
    )
);

create table if not exists provenance.event_revisions (
    id                 uuid primary key default gen_random_uuid(),
    canonical_event_id uuid not null
        references knowledge.events(id) on delete restrict,
    content_hash       text not null check (content_hash ~ '^[0-9a-f]{64}$'),
    factual_snapshot   jsonb not null check (jsonb_typeof(factual_snapshot) = 'object'),
    first_observed_at  timestamptz not null default now(),
    created_at         timestamptz not null default now(),
    unique (canonical_event_id, content_hash)
);

create table if not exists provenance.event_run_occurrences (
    run_id                 uuid not null
        references provenance.run_manifests(run_id) on delete restrict,
    candidate_id           text not null,
    canonical_event_id     uuid
        references knowledge.events(id) on delete restrict,
    event_revision_id      uuid
        references provenance.event_revisions(id) on delete restrict,
    disposition            text not null check (
        disposition in ('inserted', 'updated', 'observed_existing', 'rejected')
    ),
    content_hash           text check (
        content_hash is null or content_hash ~ '^[0-9a-f]{64}$'
    ),
    collector              text not null check (length(btrim(collector)) between 1 and 120),
    collector_role         text not null check (collector_role in ('requested', 'supporting')),
    reason_codes           text[] not null default '{}',
    observed_at            timestamptz not null default now(),
    created_at             timestamptz not null default now(),
    primary key (run_id, candidate_id),
    check (
        (disposition = 'rejected'
            and canonical_event_id is null
            and event_revision_id is null
            and content_hash is null
            and cardinality(reason_codes) > 0)
        or
        (disposition <> 'rejected'
            and canonical_event_id is not null
            and event_revision_id is not null
            and content_hash is not null
            and cardinality(reason_codes) = 0)
    )
);

create table if not exists provenance.signal_run_occurrences (
    run_id         uuid not null
        references provenance.run_manifests(run_id) on delete restrict,
    signal_id      text not null
        references public.researcher_signals(id) on delete restrict,
    disposition    text not null check (
        disposition in ('inserted', 'updated', 'observed_existing')
    ),
    content_hash   text not null check (content_hash ~ '^[0-9a-f]{64}$'),
    observed_at    timestamptz not null default now(),
    created_at     timestamptz not null default now(),
    primary key (run_id, signal_id)
);

create table if not exists provenance.signal_event_members (
    run_id             uuid not null,
    signal_id          text not null
        references public.researcher_signals(id) on delete restrict,
    canonical_event_id uuid not null
        references knowledge.events(id) on delete restrict,
    role               text not null check (role in ('representative', 'contributor')),
    position           integer not null check (position >= 0),
    created_at         timestamptz not null default now(),
    primary key (run_id, signal_id, canonical_event_id),
    unique (run_id, signal_id, position),
    foreign key (run_id, signal_id)
        references provenance.signal_run_occurrences(run_id, signal_id)
        on delete restrict
);

create unique index if not exists signal_event_members_one_representative_idx
    on provenance.signal_event_members(run_id, signal_id)
    where role = 'representative';

create index if not exists event_revisions_event_created_idx
    on provenance.event_revisions(canonical_event_id, created_at desc);

create index if not exists event_run_occurrences_event_idx
    on provenance.event_run_occurrences(canonical_event_id, run_id)
    where canonical_event_id is not null;

create index if not exists event_run_occurrences_disposition_idx
    on provenance.event_run_occurrences(disposition, observed_at desc);

create index if not exists signal_run_occurrences_signal_idx
    on provenance.signal_run_occurrences(signal_id, run_id);

create index if not exists signal_event_members_event_idx
    on provenance.signal_event_members(canonical_event_id);

create or replace trigger trg_run_manifests_updated
    before update on provenance.run_manifests
    for each row execute function public.set_updated_at();

alter table provenance.run_manifests enable row level security;
alter table provenance.event_revisions enable row level security;
alter table provenance.event_run_occurrences enable row level security;
alter table provenance.signal_run_occurrences enable row level security;
alter table provenance.signal_event_members enable row level security;

revoke all on all tables in schema provenance
from public, anon, authenticated, service_role;

create or replace function provenance.content_hash(p_payload jsonb)
returns text
language sql
immutable
strict
set search_path = pg_catalog
as $$
    select encode(
        extensions.digest(convert_to(p_payload::text, 'UTF8'), 'sha256'),
        'hex'
    );
$$;

create or replace function provenance.event_machine_payload(
    p_event knowledge.events
)
returns jsonb
language sql
immutable
strict
set search_path = pg_catalog
as $$
    select to_jsonb(p_event) - array[
        'primary_claim_id', 'epistemic_status', 'confidence_score',
        'pipeline_status', 'requires_human_review',
        'review_decision', 'validated_by', 'validated_at',
        'publication_approved', 'publication_approved_by',
        'publication_approved_at', 'created_at', 'updated_at'
    ];
$$;

revoke all on function provenance.content_hash(jsonb) from public, anon, authenticated, service_role;
revoke all on function provenance.event_machine_payload(knowledge.events) from public, anon, authenticated, service_role;

create or replace function public.begin_canonical_run_manifest(p_run_id uuid)
returns void
language plpgsql
security definer
set search_path = pg_catalog
as $$
begin
    if not exists (
        select 1 from raw.pipeline_runs
        where id = p_run_id and mode = 'persist'
    ) then
        raise exception 'canonical persistence requires a persist pipeline run';
    end if;
    insert into provenance.run_manifests(run_id)
    values (p_run_id)
    on conflict (run_id) do nothing;
    if exists (
        select 1 from provenance.run_manifests
        where run_id = p_run_id and stage in ('finalized', 'failed')
    ) then
        raise exception 'canonical run manifest is terminal';
    end if;
end;
$$;

create or replace function public.persist_canonical_event_batch(
    p_run_id uuid,
    p_accepted jsonb,
    p_rejected jsonb default '[]'::jsonb
)
returns table (
    artifact_id text,
    disposition text,
    content_hash text,
    revision_id uuid
)
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
    v_item jsonb;
    v_event knowledge.events%rowtype;
    v_existing knowledge.events%rowtype;
    v_effective knowledge.events%rowtype;
    v_snapshot jsonb;
    v_incoming_hash text;
    v_existing_hash text;
    v_revision_id uuid;
    v_disposition text;
    v_candidate_id text;
    v_occurrence provenance.event_run_occurrences%rowtype;
begin
    if jsonb_typeof(p_accepted) <> 'array' or jsonb_typeof(p_rejected) <> 'array' then
        raise exception 'canonical event payloads must be arrays';
    end if;
    if not exists (
        select 1 from raw.pipeline_runs
        where id = p_run_id and mode = 'persist'
    ) then
        raise exception 'canonical persistence requires a persist pipeline run';
    end if;

    if not exists (
        select 1 from provenance.run_manifests
        where run_id = p_run_id and stage = 'started'
    ) then
        raise exception 'canonical run manifest must be started first';
    end if;

    for v_item in select value from jsonb_array_elements(p_accepted)
    loop
        if jsonb_typeof(v_item -> 'event') <> 'object' then
            raise exception 'accepted canonical Event must be an object';
        end if;
        v_event := jsonb_populate_record(null::knowledge.events, v_item -> 'event');
        if v_event.id is null then
            raise exception 'canonical Event id is required';
        end if;
        v_candidate_id := v_event.id::text;
        v_incoming_hash := provenance.content_hash(
            provenance.event_machine_payload(v_event)
        );

        select * into v_existing
        from knowledge.events
        where id = v_event.id
        for update;

        if not found then
            insert into knowledge.events (
                id, title, summary, epistemic_status, confidence_score,
                category, country, scientific_area, entities, keywords,
                evidence, occurred_at, event_status, source, supporting_sources,
                pipeline_status, requires_human_review, review_decision,
                primary_claim_id, validated_by, validated_at
            ) values (
                v_event.id, v_event.title, v_event.summary,
                v_event.epistemic_status, v_event.confidence_score,
                v_event.category, v_event.country, v_event.scientific_area,
                coalesce(v_event.entities, '[]'::jsonb),
                coalesce(v_event.keywords, '{}'),
                coalesce(v_event.evidence, '[]'::jsonb),
                v_event.occurred_at, coalesce(v_event.event_status, 'unknown'),
                v_event.source, coalesce(v_event.supporting_sources, '{}'),
                'normalized', false, 'pending', null, null, null
            )
            returning * into v_effective;
            v_disposition := 'inserted';
        else
            v_existing_hash := provenance.content_hash(
                provenance.event_machine_payload(v_existing)
            );
            if v_existing_hash = v_incoming_hash then
                v_effective := v_existing;
                v_disposition := 'observed_existing';
            else
                update knowledge.events set
                    title = v_event.title,
                    summary = v_event.summary,
                    category = v_event.category,
                    country = v_event.country,
                    scientific_area = v_event.scientific_area,
                    entities = coalesce(v_event.entities, '[]'::jsonb),
                    keywords = coalesce(v_event.keywords, '{}'),
                    evidence = coalesce(v_event.evidence, '[]'::jsonb),
                    occurred_at = v_event.occurred_at,
                    event_status = coalesce(v_event.event_status, 'unknown'),
                    source = v_event.source,
                    supporting_sources = coalesce(v_event.supporting_sources, '{}')
                where id = v_event.id
                returning * into v_effective;
                v_disposition := 'updated';
            end if;
        end if;

        v_snapshot := provenance.event_machine_payload(v_effective);
        v_incoming_hash := provenance.content_hash(v_snapshot);
        insert into provenance.event_revisions(
            canonical_event_id, content_hash, factual_snapshot
        ) values (
            v_effective.id, v_incoming_hash, v_snapshot
        )
        on conflict (canonical_event_id, content_hash) do update
            set canonical_event_id = excluded.canonical_event_id
        returning id into v_revision_id;

        insert into provenance.event_run_occurrences(
            run_id, candidate_id, canonical_event_id, event_revision_id,
            disposition, content_hash, collector, collector_role
        ) values (
            p_run_id, v_candidate_id, v_effective.id, v_revision_id,
            v_disposition, v_incoming_hash,
            v_item ->> 'collector', v_item ->> 'collector_role'
        )
        on conflict (run_id, candidate_id) do nothing;

        select * into v_occurrence
        from provenance.event_run_occurrences
        where run_id = p_run_id and candidate_id = v_candidate_id;
        if v_occurrence.content_hash is distinct from v_incoming_hash
           or v_occurrence.canonical_event_id is distinct from v_effective.id then
            raise exception 'conflicting canonical Event retry';
        end if;

        artifact_id := v_candidate_id;
        disposition := v_occurrence.disposition;
        content_hash := v_incoming_hash;
        revision_id := v_revision_id;
        return next;
    end loop;

    for v_item in select value from jsonb_array_elements(p_rejected)
    loop
        v_candidate_id := v_item ->> 'candidate_id';
        if v_candidate_id is null or btrim(v_candidate_id) = '' then
            raise exception 'rejected candidate id is required';
        end if;
        insert into provenance.event_run_occurrences(
            run_id, candidate_id, disposition, collector, collector_role,
            reason_codes
        ) values (
            p_run_id, v_candidate_id, 'rejected',
            v_item ->> 'collector', v_item ->> 'collector_role',
            array(select jsonb_array_elements_text(v_item -> 'reasons'))
        )
        on conflict (run_id, candidate_id) do nothing;

        artifact_id := v_candidate_id;
        disposition := 'rejected';
        content_hash := null;
        revision_id := null;
        return next;
    end loop;

    update provenance.run_manifests set
        stage = 'events_persisted',
        accepted_event_count = (
            select count(*) from provenance.event_run_occurrences as occurrences
            where occurrences.run_id = p_run_id
              and occurrences.disposition <> 'rejected'
        ),
        rejected_event_count = (
            select count(*) from provenance.event_run_occurrences as occurrences
            where occurrences.run_id = p_run_id
              and occurrences.disposition = 'rejected'
        )
    where run_id = p_run_id;
end;
$$;

create or replace function public.persist_canonical_signal_batch(
    p_run_id uuid,
    p_signals jsonb
)
returns table (
    artifact_id text,
    disposition text,
    content_hash text
)
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
    v_item jsonb;
    v_signal public.researcher_signals%rowtype;
    v_existing public.researcher_signals%rowtype;
    v_effective public.researcher_signals%rowtype;
    v_hash text;
    v_existing_hash text;
    v_disposition text;
    v_representative uuid;
    v_contributor_text text;
    v_contributor uuid;
    v_position integer;
    v_occurrence provenance.signal_run_occurrences%rowtype;
    v_signal_exists boolean;
begin
    if jsonb_typeof(p_signals) <> 'array' then
        raise exception 'canonical signal payload must be an array';
    end if;
    if not exists (
        select 1 from provenance.run_manifests
        where run_id = p_run_id and stage in ('events_persisted', 'signals_persisted')
    ) then
        raise exception 'canonical Events must be persisted before signals';
    end if;

    for v_item in select value from jsonb_array_elements(p_signals)
    loop
        v_signal := jsonb_populate_record(null::public.researcher_signals, v_item -> 'signal');
        v_representative := (v_item ->> 'representative_event_id')::uuid;
        if v_signal.id is null or v_signal.representative_event_id <> v_representative::text then
            raise exception 'signal representative canonical Event mismatch';
        end if;
        if not exists (
            select 1 from provenance.event_run_occurrences
            where run_id = p_run_id
              and canonical_event_id = v_representative
              and disposition <> 'rejected'
        ) then
            raise exception 'representative canonical Event not persisted in this run';
        end if;
        for v_contributor_text in
            select jsonb_array_elements_text(
                coalesce(v_item -> 'contributor_event_ids', '[]'::jsonb)
            )
        loop
            v_contributor := v_contributor_text::uuid;
            if not exists (
                select 1 from provenance.event_run_occurrences
                where run_id = p_run_id
                  and canonical_event_id = v_contributor
                  and disposition <> 'rejected'
            ) then
                raise exception 'contributor canonical Event not persisted in this run';
            end if;
        end loop;

        v_hash := provenance.content_hash(
            to_jsonb(v_signal) - array['created_at', 'updated_at']
        );
        select * into v_existing
        from public.researcher_signals
        where id = v_signal.id
        for update;
        v_signal_exists := found;

        if v_signal_exists and not exists (
            select 1 from provenance.signal_event_members
            where signal_id = v_signal.id
        ) then
            raise exception 'legacy ResearcherSignal cannot be canonical-linked automatically';
        end if;

        if not v_signal_exists then
            insert into public.researcher_signals (
                id, researcher_id, research_profile_version,
                event_id, representative_event_id, member_event_ids,
                title, summary, occurred_at, validated_at,
                priority_score, priority_level, relevance_score,
                significance_score, significance_level, reasons,
                requires_human_review, taxonomy_version, algorithm_version,
                config_version, matched_concepts, event_status, category,
                source, supporting_sources, evidence
            ) values (
                v_signal.id, v_signal.researcher_id,
                v_signal.research_profile_version, v_signal.event_id,
                v_signal.representative_event_id, v_signal.member_event_ids,
                v_signal.title, v_signal.summary, v_signal.occurred_at,
                v_signal.validated_at, v_signal.priority_score,
                v_signal.priority_level, v_signal.relevance_score,
                v_signal.significance_score, v_signal.significance_level,
                v_signal.reasons, v_signal.requires_human_review,
                v_signal.taxonomy_version, v_signal.algorithm_version,
                v_signal.config_version, v_signal.matched_concepts,
                v_signal.event_status, v_signal.category, v_signal.source,
                v_signal.supporting_sources, v_signal.evidence
            ) returning * into v_effective;
            v_disposition := 'inserted';
        else
            v_existing_hash := provenance.content_hash(
                to_jsonb(v_existing) - array['created_at', 'updated_at']
            );
            if v_existing_hash = v_hash then
                v_effective := v_existing;
                v_disposition := 'observed_existing';
            else
                update public.researcher_signals set
                    researcher_id = v_signal.researcher_id,
                    research_profile_version = v_signal.research_profile_version,
                    event_id = v_signal.event_id,
                    representative_event_id = v_signal.representative_event_id,
                    member_event_ids = v_signal.member_event_ids,
                    title = v_signal.title,
                    summary = v_signal.summary,
                    occurred_at = v_signal.occurred_at,
                    validated_at = v_signal.validated_at,
                    priority_score = v_signal.priority_score,
                    priority_level = v_signal.priority_level,
                    relevance_score = v_signal.relevance_score,
                    significance_score = v_signal.significance_score,
                    significance_level = v_signal.significance_level,
                    reasons = v_signal.reasons,
                    requires_human_review = v_signal.requires_human_review,
                    taxonomy_version = v_signal.taxonomy_version,
                    algorithm_version = v_signal.algorithm_version,
                    config_version = v_signal.config_version,
                    matched_concepts = v_signal.matched_concepts,
                    event_status = v_signal.event_status,
                    category = v_signal.category,
                    source = v_signal.source,
                    supporting_sources = v_signal.supporting_sources,
                    evidence = v_signal.evidence,
                    updated_at = now()
                where id = v_signal.id
                returning * into v_effective;
                v_disposition := 'updated';
            end if;
        end if;

        insert into provenance.signal_run_occurrences(
            run_id, signal_id, disposition, content_hash
        ) values (
            p_run_id, v_signal.id, v_disposition, v_hash
        )
        on conflict (run_id, signal_id) do nothing;

        select * into v_occurrence
        from provenance.signal_run_occurrences
        where run_id = p_run_id and signal_id = v_signal.id;
        if v_occurrence.content_hash <> v_hash then
            raise exception 'conflicting canonical Signal retry';
        end if;

        insert into provenance.signal_event_members(
            run_id, signal_id, canonical_event_id, role, position
        ) values (
            p_run_id, v_signal.id, v_representative, 'representative', 0
        )
        on conflict (run_id, signal_id, canonical_event_id) do nothing;
        if not exists (
            select 1 from provenance.signal_event_members
            where run_id = p_run_id and signal_id = v_signal.id
              and canonical_event_id = v_representative
              and role = 'representative' and position = 0
        ) then
            raise exception 'conflicting representative membership retry';
        end if;

        v_position := 1;
        for v_contributor_text in
            select jsonb_array_elements_text(
                coalesce(v_item -> 'contributor_event_ids', '[]'::jsonb)
            )
        loop
            v_contributor := v_contributor_text::uuid;
            if v_contributor <> v_representative then
                insert into provenance.signal_event_members(
                    run_id, signal_id, canonical_event_id, role, position
                ) values (
                    p_run_id, v_signal.id, v_contributor, 'contributor', v_position
                )
                on conflict (run_id, signal_id, canonical_event_id) do nothing;
                if not exists (
                    select 1 from provenance.signal_event_members
                    where run_id = p_run_id and signal_id = v_signal.id
                      and canonical_event_id = v_contributor
                      and role = 'contributor' and position = v_position
                ) then
                    raise exception 'conflicting contributor membership retry';
                end if;
                v_position := v_position + 1;
            end if;
        end loop;

        artifact_id := v_signal.id;
        disposition := v_occurrence.disposition;
        content_hash := v_hash;
        return next;
    end loop;

    update provenance.run_manifests set
        stage = 'signals_persisted',
        persisted_signal_count = (
            select count(*) from provenance.signal_run_occurrences
            where run_id = p_run_id
        )
    where run_id = p_run_id;
end;
$$;

create or replace function public.finalize_canonical_run_manifest(
    p_run_id uuid,
    p_stage text,
    p_accepted_events integer default 0,
    p_rejected_events integer default 0,
    p_persisted_signals integer default 0,
    p_versions jsonb default '{}'::jsonb,
    p_commit_state text default 'known',
    p_error_type text default null,
    p_error_message text default null
)
returns void
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
    v_hash text;
    v_current provenance.run_manifests%rowtype;
begin
    if p_stage not in ('events_persisted', 'signals_persisted', 'finalized', 'failed') then
        raise exception 'invalid canonical manifest stage';
    end if;
    if p_commit_state not in ('known', 'ambiguous') then
        raise exception 'invalid canonical manifest commit state';
    end if;
    if p_accepted_events < 0 or p_rejected_events < 0 or p_persisted_signals < 0 then
        raise exception 'manifest counts must be nonnegative';
    end if;
    v_hash := provenance.content_hash(jsonb_build_object(
        'run_id', p_run_id,
        'stage', p_stage,
        'accepted_events', p_accepted_events,
        'rejected_events', p_rejected_events,
        'persisted_signals', p_persisted_signals,
        'versions', coalesce(p_versions, '{}'::jsonb),
        'commit_state', p_commit_state,
        'error_type', p_error_type,
        'error_message', p_error_message
    ));

    select * into v_current from provenance.run_manifests
    where run_id = p_run_id for update;
    if not found then
        raise exception 'canonical run manifest not found';
    end if;
    if v_current.stage in ('finalized', 'failed') then
        if v_current.manifest_hash = v_hash then
            return;
        end if;
        raise exception 'canonical run manifest already finalized differently';
    end if;

    update provenance.run_manifests set
        stage = p_stage,
        accepted_event_count = p_accepted_events,
        rejected_event_count = p_rejected_events,
        persisted_signal_count = p_persisted_signals,
        versions = coalesce(p_versions, '{}'::jsonb),
        commit_state = p_commit_state,
        error_type = p_error_type,
        error_message = p_error_message,
        manifest_hash = v_hash,
        finalized_at = case when p_stage in ('finalized', 'failed') then now() else null end
    where run_id = p_run_id;
end;
$$;

create or replace function public.approve_canonical_event_publication(
    p_event_id uuid,
    p_approved_by text
)
returns void
language plpgsql
security definer
set search_path = pg_catalog
as $$
begin
    if p_approved_by is null or btrim(p_approved_by) = '' then
        raise exception 'publication approver is required';
    end if;
    update knowledge.events set
        publication_approved = true,
        publication_approved_by = p_approved_by,
        publication_approved_at = now()
    where id = p_event_id;
    if not found then
        raise exception 'canonical Event not found';
    end if;
end;
$$;

create or replace view public.v_seismic_events
with (security_invoker = true)
as
select
    id,
    title,
    summary,
    category,
    source,
    event_status,
    country,
    scientific_area,
    evidence,
    occurred_at,
    validated_at
from knowledge.events
where scientific_area = 'seismology'
  and category = 'earthquake_detected'
  and publication_approved;

alter view public.v_seismic_events owner to postgres;
revoke all on public.v_seismic_events from public, anon, authenticated, service_role;
grant select on public.v_seismic_events to service_role;
grant select (publication_approved) on knowledge.events to service_role;

create or replace view public.v_seismic_editorial_contents
with (security_invoker = true)
as
select
    contents.event_id,
    contents.editorial_version,
    contents.locale,
    contents.editorial_title,
    contents.editorial_subtitle,
    contents.editorial_summary,
    contents.seo_title,
    contents.seo_description,
    contents.seo_keywords,
    contents.generated_at,
    events.source,
    events.event_status,
    events.country,
    events.occurred_at,
    events.category
from editorial.seismic_contents as contents
join knowledge.events as events on events.id = contents.event_id
where contents.editorial_version = 'seismic-v1'
  and contents.locale = 'pt-BR'
  and events.scientific_area = 'seismology'
  and events.category = 'earthquake_detected'
  and events.publication_approved;

alter view public.v_seismic_editorial_contents owner to postgres;
revoke all on public.v_seismic_editorial_contents
from public, anon, authenticated, service_role;
grant select on public.v_seismic_editorial_contents to service_role;

create or replace view public.v_volcanic_editorial_contents
with (security_invoker = true)
as
select
    contents.editorial_group_id,
    contents.representative_event_id,
    contents.member_event_ids,
    contents.volcano_name,
    contents.volcano_number,
    contents.editorial_version,
    contents.locale,
    contents.editorial_title,
    contents.editorial_subtitle,
    contents.editorial_summary,
    contents.seo_title,
    contents.seo_description,
    contents.seo_keywords,
    contents.generated_at,
    events.source,
    events.event_status,
    events.occurred_at,
    events.category
from editorial.volcanic_contents as contents
join knowledge.events as events on events.id = contents.representative_event_id
where contents.editorial_version = 'volcanic-v1'
  and contents.locale = 'pt-BR'
  and events.scientific_area = 'volcanology'
  and events.publication_approved;

alter view public.v_volcanic_editorial_contents owner to postgres;
revoke all on public.v_volcanic_editorial_contents
from public, anon, authenticated, service_role;
grant select on public.v_volcanic_editorial_contents to service_role;

revoke all on function public.persist_canonical_event_batch(uuid, jsonb, jsonb)
from public, anon, authenticated;
revoke all on function public.begin_canonical_run_manifest(uuid)
from public, anon, authenticated;
revoke all on function public.persist_canonical_signal_batch(uuid, jsonb)
from public, anon, authenticated;
revoke all on function public.finalize_canonical_run_manifest(
    uuid, text, integer, integer, integer, jsonb, text, text, text
) from public, anon, authenticated;
revoke all on function public.approve_canonical_event_publication(uuid, text)
from public, anon, authenticated;

grant execute on function public.persist_canonical_event_batch(uuid, jsonb, jsonb)
to service_role;
grant execute on function public.begin_canonical_run_manifest(uuid)
to service_role;
grant execute on function public.persist_canonical_signal_batch(uuid, jsonb)
to service_role;
grant execute on function public.finalize_canonical_run_manifest(
    uuid, text, integer, integer, integer, jsonb, text, text, text
) to service_role;
grant execute on function public.approve_canonical_event_publication(uuid, text)
to service_role;

comment on schema provenance is
    'Private append-only lineage for canonical Events and ResearcherSignals.';
comment on table provenance.signal_event_members is
    'Canonical Event membership only; source-observation IDs are forbidden by UUID FK.';
comment on column knowledge.events.publication_approved is
    'Explicit publication gate. Canonical persistence never sets this true.';
