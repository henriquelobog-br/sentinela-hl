-- 022_fix_canonical_event_revision_conflict.sql
-- Avoid PL/pgSQL ambiguity between the content_hash OUT variable and column.

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
        on conflict on constraint event_revisions_canonical_event_id_content_hash_key
        do update set canonical_event_id = excluded.canonical_event_id
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

revoke all on function public.persist_canonical_event_batch(uuid, jsonb, jsonb)
from public, anon, authenticated;

grant execute on function public.persist_canonical_event_batch(uuid, jsonb, jsonb)
to service_role;
