-- Pre-024 reproduction: legacy collision remains batch-fatal P0001.
-- Intended for local PostgreSQL 17.6 only. Rolls back all fixtures.

create or replace function pg_temp.signal_item(
    p_id text,
    p_event uuid,
    p_title text default 'title',
    p_contributors uuid[] default '{}',
    p_priority double precision default 0.4
) returns jsonb
language sql
as $$
    select jsonb_build_object(
        'signal', jsonb_build_object(
            'id', p_id,
            'researcher_id', 'researcher-024',
            'research_profile_version', '1',
            'event_id', p_event::text,
            'representative_event_id', p_event::text,
            'member_event_ids', '[]'::jsonb,
            'title', p_title,
            'summary', 'summary',
            'priority_score', p_priority,
            'priority_level', 'moderate',
            'relevance_score', 0.4,
            'significance_score', 0.4,
            'significance_level', 'moderate',
            'reasons', '[]'::jsonb,
            'requires_human_review', false,
            'taxonomy_version', '1',
            'algorithm_version', '1',
            'config_version', '1',
            'matched_concepts', '[]'::jsonb,
            'event_status', 'unknown',
            'supporting_sources', '[]'::jsonb,
            'evidence', '[]'::jsonb
        ),
        'representative_event_id', p_event::text,
        'contributor_event_ids', to_jsonb(p_contributors)
    );
$$;

begin;

do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000001';
    v_event uuid := '02400000-0000-4000-8000-000000000101';
    v_revision uuid;
    v_hash text := repeat('a', 64);
    v_sqlstate text;
    v_message text;
    v_legacy jsonb;
begin
    insert into raw.pipeline_runs (
        id, initiated_by, mode, status, started_at,
        requested_sources, requested_source_count
    ) values (
        v_run, 'test-024', 'persist', 'running', now(), '{}', 0
    );
    insert into provenance.run_manifests(run_id, stage)
    values (v_run, 'events_persisted');
    insert into knowledge.events (id, title, epistemic_status, confidence_score)
    values (v_event, '024 event', 'confirmed_fact', 0.5);
    insert into provenance.event_revisions (
        canonical_event_id, content_hash, factual_snapshot
    ) values (v_event, v_hash, jsonb_build_object('id', v_event))
    returning id into v_revision;
    insert into provenance.event_run_occurrences (
        run_id, candidate_id, canonical_event_id, event_revision_id,
        disposition, content_hash, collector, collector_role
    ) values (
        v_run, v_event::text, v_event, v_revision,
        'inserted', v_hash, 'usgs', 'requested'
    );

    insert into public.researcher_signals (
        id, researcher_id, research_profile_version,
        event_id, representative_event_id, title,
        priority_score, priority_level, relevance_score,
        significance_score, significance_level, requires_human_review,
        taxonomy_version, algorithm_version, config_version
    ) values (
        '024-legacy-a', 'researcher-024', '1',
        v_event::text, v_event::text, 'legacy title',
        0.4, 'moderate', 0.4, 0.4, 'moderate', false,
        '1', '1', '1'
    );
    select to_jsonb(s) - array['created_at', 'updated_at']
    into v_legacy
    from public.researcher_signals s
    where id = '024-legacy-a';

    begin
        perform artifact_id
        from public.persist_canonical_signal_batch(
            v_run,
            jsonb_build_array(
                pg_temp.signal_item('024-legacy-a', v_event),
                pg_temp.signal_item('024-new-a', v_event, 'valid')
            )
        );
        raise exception 'expected P0001 legacy collision';
    exception
        when raise_exception then
            get stacked diagnostics
                v_sqlstate = returned_sqlstate,
                v_message = message_text;
            if v_message = 'expected P0001 legacy collision' then
                raise;
            end if;
            if v_sqlstate <> 'P0001' then
                raise exception 'expected P0001, got % %', v_sqlstate, v_message;
            end if;
            if v_message <> 'legacy ResearcherSignal cannot be canonical-linked automatically' then
                raise exception 'unexpected message: %', v_message;
            end if;
    end;

    if exists (
        select 1 from public.researcher_signals where id = '024-new-a'
    ) then
        raise exception 'valid signal leaked after legacy P0001';
    end if;
    if exists (
        select 1 from provenance.signal_run_occurrences where run_id = v_run
    ) then
        raise exception 'signal occurrence leaked after legacy P0001';
    end if;
    if exists (
        select 1 from provenance.signal_event_members where run_id = v_run
    ) then
        raise exception 'membership leaked after legacy P0001';
    end if;
    if (
        select to_jsonb(s) - array['created_at', 'updated_at']
        from public.researcher_signals s
        where id = '024-legacy-a'
    ) is distinct from v_legacy then
        raise exception 'legacy row mutated after P0001';
    end if;
end;
$$;

rollback;
