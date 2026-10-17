-- 038_usgs_seismic_source_identity_dedup.sql
-- Reconcile historical USGS seismic revisions by source_event_id and preserve
-- the keeper UUID as the canonical identity for future persistence.

begin;

lock table knowledge.events in share row exclusive mode;
lock table provenance.event_revisions in share row exclusive mode;
lock table provenance.event_run_occurrences in share row exclusive mode;
lock table provenance.signal_event_members in share row exclusive mode;
lock table editorial.seismic_contents in share row exclusive mode;
lock table editorial.volcanic_contents in share row exclusive mode;
lock table knowledge.bulletin_events in share row exclusive mode;
lock table knowledge.contradictions in share row exclusive mode;
lock table public.researcher_signals in share row exclusive mode;

create temporary table usgs_seismic_event_dedup_map (
    source_event_id text not null,
    old_id uuid primary key,
    keep_id uuid not null,
    check (old_id <> keep_id)
) on commit drop;

insert into usgs_seismic_event_dedup_map(source_event_id, old_id, keep_id)
with ranked as (
    select
        events.id,
        nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '') as source_event_id,
        first_value(events.id) over (
            partition by nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '')
            order by
                nullif(events.evidence -> 0 ->> 'updated_at', '')::timestamptz desc nulls last,
                events.created_at desc,
                events.id desc
        ) as keep_id,
        row_number() over (
            partition by nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '')
            order by
                nullif(events.evidence -> 0 ->> 'updated_at', '')::timestamptz desc nulls last,
                events.created_at desc,
                events.id desc
        ) as rn
    from knowledge.events as events
    where events.source = 'USGS'
      and events.scientific_area = 'seismology'
      and events.category = 'earthquake_detected'
      and nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '') is not null
)
select source_event_id, id, keep_id
from ranked
where rn > 1;

create temporary table usgs_seismic_revision_moves on commit drop as
select revisions.id as revision_id, mapping.old_id, mapping.keep_id
from provenance.event_revisions as revisions
join usgs_seismic_event_dedup_map as mapping
  on mapping.old_id = revisions.canonical_event_id;

create temporary table usgs_seismic_occurrence_moves on commit drop as
select occurrences.run_id, occurrences.candidate_id,
       occurrences.event_revision_id, mapping.old_id, mapping.keep_id
from provenance.event_run_occurrences as occurrences
join usgs_seismic_event_dedup_map as mapping
  on mapping.old_id = occurrences.canonical_event_id;

create temporary table usgs_seismic_editorial_deletes on commit drop as
select contents.id as editorial_id, contents.event_id,
       contents.editorial_version, contents.locale, mapping.keep_id
from editorial.seismic_contents as contents
join usgs_seismic_event_dedup_map as mapping
  on mapping.old_id = contents.event_id;

do $assert_legacy$
declare
    v_mapping_count integer;
    v_initial_count integer;
    v_distinct_count integer;
    v_revision_moves integer;
    v_occurrence_moves integer;
    v_editorial_deletes integer;
    v_published_total integer;
    v_published_removed integer;
begin
    select count(*) into v_mapping_count
    from usgs_seismic_event_dedup_map;

    if v_mapping_count = 0 then
        return;
    end if;

    select count(*), count(distinct nullif(btrim(
        events.evidence -> 0 ->> 'source_event_id'
    ), ''))
    into v_initial_count, v_distinct_count
    from knowledge.events as events
    where events.source = 'USGS'
      and events.scientific_area = 'seismology'
      and events.category = 'earthquake_detected'
      and nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '') is not null;

    if v_initial_count <> 254 or v_distinct_count <> 202
       or v_mapping_count <> 52 then
        raise exception
            'unexpected legacy USGS seismic cardinality: events %, identities %, redundant %',
            v_initial_count, v_distinct_count, v_mapping_count;
    end if;

    if exists (
        select 1
        from usgs_seismic_event_dedup_map as mapping
        join knowledge.events as old_event on old_event.id = mapping.old_id
        join knowledge.events as keeper on keeper.id = mapping.keep_id
        where nullif(btrim(old_event.evidence -> 0 ->> 'source_event_id'), '')
              is distinct from mapping.source_event_id
           or nullif(btrim(keeper.evidence -> 0 ->> 'source_event_id'), '')
              is distinct from mapping.source_event_id
    ) then
        raise exception 'invalid USGS seismic keeper mapping';
    end if;

    select count(*) into v_revision_moves from usgs_seismic_revision_moves;
    select count(*) into v_occurrence_moves from usgs_seismic_occurrence_moves;
    select count(*) into v_editorial_deletes from usgs_seismic_editorial_deletes;

    if v_revision_moves <> 111 then
        raise exception 'expected 111 revision moves, found %', v_revision_moves;
    end if;
    if v_occurrence_moves <> 111 then
        raise exception 'expected 111 occurrence moves, found %', v_occurrence_moves;
    end if;
    if v_editorial_deletes <> 51 then
        raise exception 'expected 51 duplicate editorials, found %', v_editorial_deletes;
    end if;

    if exists (
        with collapsed_revisions as (
            select moves.keep_id, revisions.content_hash
            from usgs_seismic_revision_moves as moves
            join provenance.event_revisions as revisions
              on revisions.id = moves.revision_id
            union all
            select keepers.keep_id, revisions.content_hash
            from (
                select distinct mapping.keep_id
                from usgs_seismic_event_dedup_map as mapping
            ) as keepers
            join provenance.event_revisions as revisions
              on revisions.canonical_event_id = keepers.keep_id
        )
        select 1
        from collapsed_revisions
        group by keep_id, content_hash
        having count(*) > 1
    ) then
        raise exception 'USGS revision hash collision after keeper collapse';
    end if;

    if exists (
        select 1
        from usgs_seismic_editorial_deletes as old_editorial
        where not exists (
            select 1
            from editorial.seismic_contents as keeper_editorial
            where keeper_editorial.event_id = old_editorial.keep_id
              and keeper_editorial.editorial_version = old_editorial.editorial_version
              and keeper_editorial.locale = old_editorial.locale
        )
    ) then
        raise exception 'duplicate seismic editorial lacks keeper counterpart';
    end if;

    select count(*) into v_published_total
    from knowledge.events as events
    where events.source = 'USGS'
      and events.scientific_area = 'seismology'
      and events.category = 'earthquake_detected'
      and events.publication_approved;

    select count(*) into v_published_removed
    from knowledge.events as events
    join usgs_seismic_event_dedup_map as mapping on mapping.old_id = events.id
    where events.publication_approved;

    if v_published_total <> 7 or v_published_removed <> 0 then
        raise exception
            'unexpected publication state: total %, removed %',
            v_published_total, v_published_removed;
    end if;

    if exists (
        select 1 from provenance.signal_event_members as members
        join usgs_seismic_event_dedup_map as mapping
          on mapping.old_id = members.canonical_event_id
    ) then raise exception 'removed Event referenced by signal_event_members'; end if;

    if exists (
        select 1 from knowledge.bulletin_events as bulletin_events
        join usgs_seismic_event_dedup_map as mapping
          on mapping.old_id = bulletin_events.event_id
    ) then raise exception 'removed Event referenced by bulletin_events'; end if;

    if exists (
        select 1 from knowledge.contradictions as contradictions
        join usgs_seismic_event_dedup_map as mapping
          on mapping.old_id = contradictions.conflicting_event_id
    ) then raise exception 'removed Event referenced by contradictions'; end if;

    if exists (
        select 1 from public.researcher_signals as signals
        join usgs_seismic_event_dedup_map as mapping
          on signals.event_id = mapping.old_id::text
          or signals.representative_event_id = mapping.old_id::text
          or signals.member_event_ids @> jsonb_build_array(mapping.old_id::text)
    ) then raise exception 'removed Event referenced by researcher_signals'; end if;

    if exists (
        select 1 from editorial.volcanic_contents as contents
        join usgs_seismic_event_dedup_map as mapping
          on contents.representative_event_id = mapping.old_id
          or mapping.old_id = any(contents.member_event_ids)
    ) then raise exception 'removed Event referenced by volcanic editorial'; end if;
end;
$assert_legacy$;

do $apply_cleanup$
declare
    v_expected integer;
    v_actual_revision_moves integer;
    v_actual_occurrence_moves integer;
    v_actual_editorial_deletes integer;
    v_actual_event_deletes integer;
begin
    select count(*) into v_expected from usgs_seismic_event_dedup_map;
    if v_expected = 0 then
        return;
    end if;

    update provenance.event_revisions as revisions
    set canonical_event_id = moves.keep_id
    from usgs_seismic_revision_moves as moves
    where revisions.id = moves.revision_id;
    get diagnostics v_actual_revision_moves = row_count;

    update provenance.event_run_occurrences as occurrences
    set canonical_event_id = moves.keep_id
    from usgs_seismic_occurrence_moves as moves
    where occurrences.run_id = moves.run_id
      and occurrences.candidate_id = moves.candidate_id
      and occurrences.event_revision_id = moves.event_revision_id;
    get diagnostics v_actual_occurrence_moves = row_count;

    delete from editorial.seismic_contents as contents
    using usgs_seismic_editorial_deletes as deletes
    where contents.id = deletes.editorial_id;
    get diagnostics v_actual_editorial_deletes = row_count;

    delete from knowledge.events as events
    using usgs_seismic_event_dedup_map as mapping
    where events.id = mapping.old_id;
    get diagnostics v_actual_event_deletes = row_count;

    if v_actual_revision_moves <> 111 then
        raise exception 'actual revision moves %, expected 111', v_actual_revision_moves;
    end if;
    if v_actual_occurrence_moves <> 111 then
        raise exception 'actual occurrence moves %, expected 111', v_actual_occurrence_moves;
    end if;
    if v_actual_editorial_deletes <> 51 then
        raise exception 'actual editorial deletes %, expected 51', v_actual_editorial_deletes;
    end if;
    if v_actual_event_deletes <> 52 then
        raise exception 'actual Event deletes %, expected 52', v_actual_event_deletes;
    end if;
end;
$apply_cleanup$;

create unique index if not exists events_usgs_seismic_source_event_id_uidx
on knowledge.events ((nullif(btrim(evidence -> 0 ->> 'source_event_id'), '')))
where source = 'USGS'
  and scientific_area = 'seismology'
  and category = 'earthquake_detected'
  and nullif(btrim(evidence -> 0 ->> 'source_event_id'), '') is not null;

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

do $assert_final$
declare
    v_legacy boolean;
    v_events integer;
    v_distinct integer;
    v_duplicates integer;
    v_editorials integer;
    v_without_editorial integer;
    v_published integer;
begin
    select exists(select 1 from usgs_seismic_event_dedup_map) into v_legacy;

    select count(*),
           count(distinct nullif(btrim(
               events.evidence -> 0 ->> 'source_event_id'
           ), ''))
    into v_events, v_distinct
    from knowledge.events as events
    where events.source = 'USGS'
      and events.scientific_area = 'seismology'
      and events.category = 'earthquake_detected'
      and nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '') is not null;

    select count(*) into v_duplicates
    from (
        select nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '')
        from knowledge.events as events
        where events.source = 'USGS'
          and events.scientific_area = 'seismology'
          and events.category = 'earthquake_detected'
          and nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '') is not null
        group by nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '')
        having count(*) > 1
    ) as duplicate_identities;

    if v_duplicates <> 0 then
        raise exception 'duplicate USGS seismic source identities remain: %', v_duplicates;
    end if;

    if v_legacy then
        if v_events <> 202 or v_distinct <> 202 then
            raise exception 'unexpected final USGS seismic counts: %, %', v_events, v_distinct;
        end if;

        select count(*) into v_editorials
        from editorial.seismic_contents;
        if v_editorials <> 202 then
            raise exception 'expected 202 seismic editorials, found %', v_editorials;
        end if;

        select count(*) into v_without_editorial
        from knowledge.events as events
        where events.source = 'USGS'
          and events.scientific_area = 'seismology'
          and events.category = 'earthquake_detected'
          and nullif(btrim(events.evidence -> 0 ->> 'source_event_id'), '') is not null
          and not exists (
              select 1 from editorial.seismic_contents as contents
              where contents.event_id = events.id
          );
        if v_without_editorial <> 0 then
            raise exception 'USGS seismic keepers without editorial: %', v_without_editorial;
        end if;

        select count(*) into v_published
        from knowledge.events as events
        where events.source = 'USGS'
          and events.scientific_area = 'seismology'
          and events.category = 'earthquake_detected'
          and events.publication_approved;
        if v_published <> 7 then
            raise exception 'expected 7 published USGS seismic keepers, found %', v_published;
        end if;
    end if;

    if exists (
        select 1 from provenance.event_revisions as revisions
        left join knowledge.events as events on events.id = revisions.canonical_event_id
        where events.id is null
    ) then raise exception 'orphan event revisions remain'; end if;

    if exists (
        select 1 from provenance.event_run_occurrences as occurrences
        left join knowledge.events as events on events.id = occurrences.canonical_event_id
        where occurrences.disposition <> 'rejected' and events.id is null
    ) then raise exception 'orphan event run occurrences remain'; end if;

    if exists (
        select 1 from editorial.seismic_contents as contents
        left join knowledge.events as events on events.id = contents.event_id
        where events.id is null
    ) then raise exception 'orphan seismic contents remain'; end if;

    if exists (
        select 1 from usgs_seismic_event_dedup_map as mapping
        where exists (select 1 from knowledge.events where id = mapping.old_id)
           or exists (select 1 from provenance.event_revisions where canonical_event_id = mapping.old_id)
           or exists (select 1 from provenance.event_run_occurrences where canonical_event_id = mapping.old_id)
           or exists (select 1 from editorial.seismic_contents where event_id = mapping.old_id)
    ) then raise exception 'references to removed Event IDs remain'; end if;

    if not exists (
        select 1
        from pg_index as indexes
        join pg_class as relations on relations.oid = indexes.indexrelid
        where relations.relname = 'events_usgs_seismic_source_event_id_uidx'
          and indexes.indisunique
          and indexes.indisvalid
    ) then raise exception 'USGS source identity unique guard is not valid'; end if;
end;
$assert_final$;

commit;
