-- 039_canonical_event_stored_updated_at.sql
-- Extend persist_canonical_event_batch to return the transactional
-- keeper evidence.updated_at used by the USGS stale-revision guard.
-- Preserves 038 persistence semantics; adds stored_updated_at only.

begin;

drop function public.persist_canonical_event_batch(uuid, jsonb, jsonb);

create function public.persist_canonical_event_batch(
    p_run_id uuid,
    p_accepted jsonb,
    p_rejected jsonb default '[]'::jsonb
)
returns table (
    artifact_id text,
    canonical_event_id uuid,
    disposition text,
    content_hash text,
    revision_id uuid,
    stored_updated_at timestamptz
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
    v_candidate_event_id uuid;
    v_candidate_id text;
    v_source_event_id text;
    v_existing_found boolean;
    v_inserted boolean;
    v_incoming_updated_at timestamptz;
    v_existing_updated_at timestamptz;
    v_occurrence provenance.event_run_occurrences%rowtype;
begin
    if jsonb_typeof(p_accepted) <> 'array' or jsonb_typeof(p_rejected) <> 'array' then
        raise exception 'canonical event payloads must be arrays';
    end if;
    if not exists (
        select 1 from raw.pipeline_runs as runs
        where runs.id = p_run_id and runs.mode = 'persist'
    ) then
        raise exception 'canonical persistence requires a persist pipeline run';
    end if;
    if not exists (
        select 1 from provenance.run_manifests as manifests
        where manifests.run_id = p_run_id and manifests.stage = 'started'
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
        v_candidate_event_id := v_event.id;
        v_candidate_id := v_candidate_event_id::text;
        v_source_event_id := null;
        v_incoming_updated_at := null;
        v_existing_updated_at := null;
        v_event.entities := coalesce(v_event.entities, '[]'::jsonb);
        v_event.keywords := coalesce(v_event.keywords, '{}');
        v_event.evidence := coalesce(v_event.evidence, '[]'::jsonb);
        v_event.event_status := coalesce(v_event.event_status, 'unknown');
        v_event.supporting_sources := coalesce(v_event.supporting_sources, '{}');

        if v_event.source = 'USGS'
           and v_event.scientific_area = 'seismology'
           and v_event.category = 'earthquake_detected' then
            v_source_event_id := nullif(
                btrim(v_event.evidence -> 0 ->> 'source_event_id'), ''
            );
            if v_source_event_id is null then
                raise exception 'USGS seismic Event source_event_id is required';
            end if;
            v_incoming_updated_at := nullif(
                btrim(v_event.evidence -> 0 ->> 'updated_at'), ''
            )::timestamptz;
            if v_incoming_updated_at is null then
                raise exception 'USGS seismic Event updated_at is required';
            end if;
            perform pg_advisory_xact_lock(
                hashtextextended(
                    'knowledge.events:USGS:earthquake_detected:' || v_source_event_id,
                    0
                )
            );
            select existing.* into v_existing
            from knowledge.events as existing
            where existing.source = 'USGS'
              and existing.scientific_area = 'seismology'
              and existing.category = 'earthquake_detected'
              and nullif(btrim(existing.evidence -> 0 ->> 'source_event_id'), '')
                  = v_source_event_id
            for update;
            v_existing_found := found;
        else
            select existing.* into v_existing
            from knowledge.events as existing
            where existing.id = v_candidate_event_id
            for update;
            v_existing_found := found;
        end if;

        if v_existing_found then
            v_event.id := v_existing.id;
        end if;
        v_snapshot := provenance.event_machine_payload(v_event);
        v_incoming_hash := provenance.content_hash(
            v_snapshot
        );

        if not v_existing_found then
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
                v_event.entities, v_event.keywords, v_event.evidence,
                v_event.occurred_at, v_event.event_status,
                v_event.source, v_event.supporting_sources,
                'normalized', false, 'pending', null, null, null
            )
            on conflict do nothing
            returning * into v_effective;
            v_inserted := found;

            if v_inserted then
                v_disposition := 'inserted';
            else
                if v_source_event_id is not null then
                    select existing.* into v_existing
                    from knowledge.events as existing
                    where existing.source = 'USGS'
                      and existing.scientific_area = 'seismology'
                      and existing.category = 'earthquake_detected'
                      and nullif(btrim(
                          existing.evidence -> 0 ->> 'source_event_id'
                      ), '') = v_source_event_id
                    for update;
                else
                    select existing.* into v_existing
                    from knowledge.events as existing
                    where existing.id = v_candidate_event_id
                    for update;
                end if;
                v_existing_found := found;
                if not v_existing_found then
                    raise exception
                        'canonical Event insert conflicted without a compatible winner';
                end if;
                v_event.id := v_existing.id;
                v_snapshot := provenance.event_machine_payload(v_event);
                v_incoming_hash := provenance.content_hash(v_snapshot);
            end if;
        end if;

        if v_existing_found then
            if v_existing.id <> v_candidate_event_id and exists (
                select 1 from knowledge.events as candidate_collision
                where candidate_collision.id = v_candidate_event_id
                  and candidate_collision.id <> v_existing.id
            ) then
                raise exception 'canonical Event UUID conflicts with USGS source identity';
            end if;
            v_existing_hash := provenance.content_hash(
                provenance.event_machine_payload(v_existing)
            );
            if v_source_event_id is not null then
                v_existing_updated_at := nullif(
                    btrim(v_existing.evidence -> 0 ->> 'updated_at'), ''
                )::timestamptz;
                if v_existing_updated_at is null then
                    raise exception 'canonical USGS seismic Event updated_at is required';
                end if;
            end if;

            if v_source_event_id is not null
               and v_incoming_updated_at < v_existing_updated_at then
                v_effective := v_existing;
                v_disposition := 'observed_existing';
            elsif v_existing_hash = v_incoming_hash then
                v_effective := v_existing;
                v_disposition := 'observed_existing';
            else
                update knowledge.events as events set
                    title = v_event.title,
                    summary = v_event.summary,
                    category = v_event.category,
                    country = v_event.country,
                    scientific_area = v_event.scientific_area,
                    entities = v_event.entities,
                    keywords = v_event.keywords,
                    evidence = v_event.evidence,
                    occurred_at = v_event.occurred_at,
                    event_status = v_event.event_status,
                    source = v_event.source,
                    supporting_sources = v_event.supporting_sources
                where events.id = v_existing.id
                returning * into v_effective;
                v_disposition := 'updated';
            end if;
        end if;

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

        select occurrences.* into v_occurrence
        from provenance.event_run_occurrences as occurrences
        where occurrences.run_id = p_run_id
          and occurrences.candidate_id = v_candidate_id;
        if v_occurrence.content_hash is distinct from v_incoming_hash
           or v_occurrence.canonical_event_id is distinct from v_effective.id
           or v_occurrence.event_revision_id is distinct from v_revision_id then
            raise exception 'conflicting canonical Event retry';
        end if;

        artifact_id := v_candidate_id;
        canonical_event_id := v_effective.id;
        disposition := v_occurrence.disposition;
        content_hash := v_occurrence.content_hash;
        revision_id := v_occurrence.event_revision_id;
        if v_source_event_id is not null then
            stored_updated_at := nullif(
                btrim(v_effective.evidence -> 0 ->> 'updated_at'), ''
            )::timestamptz;
        else
            stored_updated_at := null;
        end if;
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
        canonical_event_id := null;
        disposition := 'rejected';
        content_hash := null;
        revision_id := null;
        stored_updated_at := null;
        return next;
    end loop;

    update provenance.run_manifests as manifests set
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
    where manifests.run_id = p_run_id;
end;
$$;

revoke all on function public.persist_canonical_event_batch(uuid, jsonb, jsonb)
from public, anon, authenticated;

grant execute on function public.persist_canonical_event_batch(uuid, jsonb, jsonb)
to service_role;

notify pgrst, 'reload schema';

commit;

