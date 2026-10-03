-- 024_allow_item_level_legacy_signal_rejection.sql
-- Convert legacy ResearcherSignal identity collision from batch-fatal
-- P0001 into item-level rejected, without scientific writes.

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
            select 1 from provenance.event_run_occurrences as ero
            where ero.run_id = p_run_id
              and ero.canonical_event_id = v_representative
              and ero.disposition <> 'rejected'
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
                select 1 from provenance.event_run_occurrences as ero
                where ero.run_id = p_run_id
                  and ero.canonical_event_id = v_contributor
                  and ero.disposition <> 'rejected'
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
            artifact_id := v_signal.id;
            disposition := 'rejected';
            content_hash := null;
            return next;
            continue;
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

revoke all on function public.persist_canonical_signal_batch(uuid, jsonb)
from public, anon, authenticated;

grant execute on function public.persist_canonical_signal_batch(uuid, jsonb)
to service_role;
