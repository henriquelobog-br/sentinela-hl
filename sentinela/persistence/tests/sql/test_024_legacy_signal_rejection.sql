-- 024 local PostgreSQL 17.6 executable validation. Session-scoped helpers;
-- each case uses BEGIN/ROLLBACK so fixtures never remain.

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
            'relevance_score', 0.4,
            'significance_score', 0.4,
            'priority_level', 'moderate',
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

create or replace function pg_temp.seed_run(
    p_run uuid,
    p_events uuid[]
) returns void
language plpgsql
as $$
declare
    v_event uuid;
    v_revision uuid;
    v_hash text := repeat('a', 64);
begin
    insert into raw.pipeline_runs (
        id, initiated_by, mode, status, started_at,
        requested_sources, requested_source_count
    ) values (
        p_run, 'test-024', 'persist', 'running', now(), '{}', 0
    );
    insert into provenance.run_manifests(run_id, stage)
    values (p_run, 'events_persisted');
    foreach v_event in array p_events
    loop
        insert into knowledge.events (id, title, epistemic_status, confidence_score)
        values (v_event, '024 event ' || v_event::text, 'confirmed_fact', 0.5);
        insert into provenance.event_revisions (
            canonical_event_id, content_hash, factual_snapshot
        ) values (v_event, v_hash, jsonb_build_object('id', v_event))
        returning id into v_revision;
        insert into provenance.event_run_occurrences (
            run_id, candidate_id, canonical_event_id, event_revision_id,
            disposition, content_hash, collector, collector_role
        ) values (
            p_run, v_event::text, v_event, v_revision,
            'inserted', v_hash, 'usgs', 'requested'
        );
    end loop;
end;
$$;

create or replace function pg_temp.seed_legacy(p_id text, p_event uuid, p_title text default 'legacy title')
returns jsonb
language plpgsql
as $$
declare
    v_row jsonb;
begin
    insert into public.researcher_signals (
        id, researcher_id, research_profile_version,
        event_id, representative_event_id, title,
        priority_score, priority_level, relevance_score,
        significance_score, significance_level, requires_human_review,
        taxonomy_version, algorithm_version, config_version
    ) values (
        p_id, 'researcher-024', '1',
        p_event::text, p_event::text, p_title,
        0.4, 'moderate', 0.4, 0.4, 'moderate', false,
        '1', '1', '1'
    );
    select to_jsonb(s) - array['created_at', 'updated_at']
    into v_row
    from public.researcher_signals s
    where id = p_id;
    return v_row;
end;
$$;

create or replace function pg_temp.assert_legacy_untouched(p_id text, p_before jsonb)
returns void
language plpgsql
as $$
begin
    if (
        select to_jsonb(s) - array['created_at', 'updated_at']
        from public.researcher_signals s
        where id = p_id
    ) is distinct from p_before then
        raise exception 'legacy row mutated: %', p_id;
    end if;
    if exists (
        select 1 from provenance.signal_run_occurrences where signal_id = p_id
    ) then
        raise exception 'legacy occurrence created: %', p_id;
    end if;
    if exists (
        select 1 from provenance.signal_event_members where signal_id = p_id
    ) then
        raise exception 'legacy membership created: %', p_id;
    end if;
end;
$$;

-- Case 1: legacy first + valid after
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000011';
    v_event uuid := '02400000-0000-4000-8000-000000000111';
    v_before jsonb;
    v_results jsonb;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_before := pg_temp.seed_legacy('024-legacy-first', v_event);
    select jsonb_agg(jsonb_build_object(
        'artifact_id', artifact_id,
        'disposition', disposition,
        'content_hash', content_hash
    ) order by ordinality)
    into v_results
    from public.persist_canonical_signal_batch(
        v_run,
        jsonb_build_array(
            pg_temp.signal_item('024-legacy-first', v_event),
            pg_temp.signal_item('024-new-first', v_event, 'valid')
        )
    ) with ordinality;
    if v_results <> jsonb_build_array(
        jsonb_build_object('artifact_id', '024-legacy-first', 'disposition', 'rejected', 'content_hash', null),
        jsonb_build_object(
            'artifact_id', '024-new-first',
            'disposition', 'inserted',
            'content_hash', (v_results -> 1 ->> 'content_hash')
        )
    ) then
        raise exception 'case 1 unexpected results: %', v_results;
    end if;
    if (v_results -> 1 ->> 'content_hash') is null
       or length(v_results -> 1 ->> 'content_hash') <> 64 then
        raise exception 'case 1 valid item missing hash';
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-first', v_before);
    if (select count(*) from provenance.signal_run_occurrences where run_id = v_run) <> 1 then
        raise exception 'case 1 occurrence count';
    end if;
    if (select count(*) from provenance.signal_event_members where run_id = v_run) <> 1 then
        raise exception 'case 1 membership count';
    end if;
    if (select persisted_signal_count from provenance.run_manifests where run_id = v_run) <> 1 then
        raise exception 'case 1 persisted_signal_count';
    end if;
end;
$$;
rollback;

-- Case 2: valid first + legacy last
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000012';
    v_event uuid := '02400000-0000-4000-8000-000000000112';
    v_before jsonb;
    v_results jsonb;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_before := pg_temp.seed_legacy('024-legacy-last', v_event);
    select jsonb_agg(jsonb_build_object(
        'artifact_id', artifact_id, 'disposition', disposition
    ) order by ordinality)
    into v_results
    from public.persist_canonical_signal_batch(
        v_run,
        jsonb_build_array(
            pg_temp.signal_item('024-new-last', v_event, 'valid'),
            pg_temp.signal_item('024-legacy-last', v_event)
        )
    ) with ordinality;
    if v_results <> jsonb_build_array(
        jsonb_build_object('artifact_id', '024-new-last', 'disposition', 'inserted'),
        jsonb_build_object('artifact_id', '024-legacy-last', 'disposition', 'rejected')
    ) then
        raise exception 'case 2 unexpected results: %', v_results;
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-last', v_before);
    if not exists (select 1 from public.researcher_signals where id = '024-new-last') then
        raise exception 'case 2 valid signal missing';
    end if;
end;
$$;
rollback;

-- Case 3: valid / legacy / valid
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000013';
    v_event uuid := '02400000-0000-4000-8000-000000000113';
    v_before jsonb;
    v_results jsonb;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_before := pg_temp.seed_legacy('024-legacy-mid', v_event);
    select jsonb_agg(disposition order by ordinality)
    into v_results
    from public.persist_canonical_signal_batch(
        v_run,
        jsonb_build_array(
            pg_temp.signal_item('024-new-mid-a', v_event, 'a'),
            pg_temp.signal_item('024-legacy-mid', v_event),
            pg_temp.signal_item('024-new-mid-b', v_event, 'b')
        )
    ) with ordinality;
    if v_results <> '["inserted", "rejected", "inserted"]'::jsonb then
        raise exception 'case 3 unexpected results: %', v_results;
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-mid', v_before);
    if (select count(*) from provenance.signal_run_occurrences where run_id = v_run) <> 2 then
        raise exception 'case 3 occurrence count';
    end if;
    if (select count(*) from provenance.signal_event_members where run_id = v_run and role = 'representative') <> 2 then
        raise exception 'case 3 representative memberships';
    end if;
    if (select persisted_signal_count from provenance.run_manifests where run_id = v_run) <> 2 then
        raise exception 'case 3 persisted_signal_count';
    end if;
end;
$$;
rollback;

-- Case 4: multiple legacy + valid
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000014';
    v_event uuid := '02400000-0000-4000-8000-000000000114';
    v_a jsonb;
    v_b jsonb;
    v_results jsonb;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_a := pg_temp.seed_legacy('024-legacy-multi-a', v_event);
    v_b := pg_temp.seed_legacy('024-legacy-multi-b', v_event);
    select jsonb_agg(disposition order by ordinality)
    into v_results
    from public.persist_canonical_signal_batch(
        v_run,
        jsonb_build_array(
            pg_temp.signal_item('024-legacy-multi-a', v_event),
            pg_temp.signal_item('024-new-multi', v_event, 'valid'),
            pg_temp.signal_item('024-legacy-multi-b', v_event)
        )
    ) with ordinality;
    if v_results <> '["rejected", "inserted", "rejected"]'::jsonb then
        raise exception 'case 4 unexpected results: %', v_results;
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-multi-a', v_a);
    perform pg_temp.assert_legacy_untouched('024-legacy-multi-b', v_b);
    if (select persisted_signal_count from provenance.run_manifests where run_id = v_run) <> 1 then
        raise exception 'case 4 persisted_signal_count';
    end if;
end;
$$;
rollback;

-- Case 5: all legacy
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000015';
    v_event uuid := '02400000-0000-4000-8000-000000000115';
    v_a jsonb;
    v_b jsonb;
    v_results jsonb;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_a := pg_temp.seed_legacy('024-legacy-all-a', v_event);
    v_b := pg_temp.seed_legacy('024-legacy-all-b', v_event);
    select jsonb_agg(jsonb_build_object(
        'disposition', disposition, 'content_hash', content_hash
    ) order by ordinality)
    into v_results
    from public.persist_canonical_signal_batch(
        v_run,
        jsonb_build_array(
            pg_temp.signal_item('024-legacy-all-a', v_event),
            pg_temp.signal_item('024-legacy-all-b', v_event)
        )
    ) with ordinality;
    if v_results <> jsonb_build_array(
        jsonb_build_object('disposition', 'rejected', 'content_hash', null),
        jsonb_build_object('disposition', 'rejected', 'content_hash', null)
    ) then
        raise exception 'case 5 unexpected results: %', v_results;
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-all-a', v_a);
    perform pg_temp.assert_legacy_untouched('024-legacy-all-b', v_b);
    if exists (select 1 from provenance.signal_run_occurrences where run_id = v_run) then
        raise exception 'case 5 occurrence present';
    end if;
    if exists (select 1 from provenance.signal_event_members where run_id = v_run) then
        raise exception 'case 5 membership present';
    end if;
    if (select persisted_signal_count from provenance.run_manifests where run_id = v_run) <> 0 then
        raise exception 'case 5 persisted_signal_count';
    end if;
end;
$$;
rollback;

-- Case 6: zero collision inserted / observed_existing / updated
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000016';
    v_replay uuid := '02400000-0000-4000-8000-000000000017';
    v_update uuid := '02400000-0000-4000-8000-000000000018';
    v_event uuid := '02400000-0000-4000-8000-000000000116';
    v_disp text;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    select disposition into v_disp
    from public.persist_canonical_signal_batch(
        v_run,
        jsonb_build_array(pg_temp.signal_item('024-lifecycle', v_event, 'original'))
    );
    if v_disp <> 'inserted' then
        raise exception 'lifecycle inserted got %', v_disp;
    end if;

    insert into raw.pipeline_runs (
        id, initiated_by, mode, status, started_at,
        requested_sources, requested_source_count
    ) values (
        v_replay, 'test-024', 'persist', 'running', now(), '{}', 0
    );
    insert into provenance.run_manifests(run_id, stage)
    values (v_replay, 'events_persisted');
    insert into provenance.event_run_occurrences (
        run_id, candidate_id, canonical_event_id, event_revision_id,
        disposition, content_hash, collector, collector_role
    )
    select v_replay, candidate_id, canonical_event_id, event_revision_id,
           'observed_existing', content_hash, collector, collector_role
    from provenance.event_run_occurrences
    where run_id = v_run;

    select disposition into v_disp
    from public.persist_canonical_signal_batch(
        v_replay,
        jsonb_build_array(pg_temp.signal_item('024-lifecycle', v_event, 'original'))
    );
    if v_disp <> 'observed_existing' then
        raise exception 'lifecycle observed_existing got %', v_disp;
    end if;

    insert into raw.pipeline_runs (
        id, initiated_by, mode, status, started_at,
        requested_sources, requested_source_count
    ) values (
        v_update, 'test-024', 'persist', 'running', now(), '{}', 0
    );
    insert into provenance.run_manifests(run_id, stage)
    values (v_update, 'events_persisted');
    insert into provenance.event_run_occurrences (
        run_id, candidate_id, canonical_event_id, event_revision_id,
        disposition, content_hash, collector, collector_role
    )
    select v_update, candidate_id, canonical_event_id, event_revision_id,
           'observed_existing', content_hash, collector, collector_role
    from provenance.event_run_occurrences
    where run_id = v_run;

    select disposition into v_disp
    from public.persist_canonical_signal_batch(
        v_update,
        jsonb_build_array(pg_temp.signal_item('024-lifecycle', v_event, 'changed'))
    );
    if v_disp <> 'updated' then
        raise exception 'lifecycle updated got %', v_disp;
    end if;
end;
$$;
rollback;

-- Fatal missing representative after valid + legacy
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000021';
    v_event uuid := '02400000-0000-4000-8000-000000000121';
    v_missing uuid := '02400000-0000-4000-8000-000000000199';
    v_before jsonb;
    v_message text;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_before := pg_temp.seed_legacy('024-legacy-rep', v_event);
    begin
        perform artifact_id
        from public.persist_canonical_signal_batch(
            v_run,
            jsonb_build_array(
                pg_temp.signal_item('024-new-rep', v_event, 'valid'),
                pg_temp.signal_item('024-legacy-rep', v_event),
                pg_temp.signal_item('024-missing-rep', v_missing, 'missing')
            )
        );
        raise exception 'expected missing representative';
    exception
        when raise_exception then
            get stacked diagnostics v_message = message_text;
            if v_message = 'expected missing representative' then
                raise;
            end if;
            if v_message <> 'representative canonical Event not persisted in this run' then
                raise exception 'unexpected representative fatal: %', v_message;
            end if;
    end;
    if exists (select 1 from public.researcher_signals where id = '024-new-rep') then
        raise exception 'valid write survived representative fatal';
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-rep', v_before);
end;
$$;
rollback;

-- Fatal missing contributor after valid + legacy
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000022';
    v_event uuid := '02400000-0000-4000-8000-000000000122';
    v_missing uuid := '02400000-0000-4000-8000-000000000198';
    v_before jsonb;
    v_message text;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_before := pg_temp.seed_legacy('024-legacy-contrib', v_event);
    begin
        perform artifact_id
        from public.persist_canonical_signal_batch(
            v_run,
            jsonb_build_array(
                pg_temp.signal_item('024-new-contrib', v_event, 'valid'),
                pg_temp.signal_item('024-legacy-contrib', v_event),
                pg_temp.signal_item('024-missing-contrib', v_event, 'bad', array[v_missing])
            )
        );
        raise exception 'expected missing contributor';
    exception
        when raise_exception then
            get stacked diagnostics v_message = message_text;
            if v_message = 'expected missing contributor' then
                raise;
            end if;
            if v_message <> 'contributor canonical Event not persisted in this run' then
                raise exception 'unexpected contributor fatal: %', v_message;
            end if;
    end;
    if exists (select 1 from public.researcher_signals where id = '024-new-contrib') then
        raise exception 'valid write survived contributor fatal';
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-contrib', v_before);
end;
$$;
rollback;

-- Rejected Event occurrence remains batch-fatal
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000023';
    v_event uuid := '02400000-0000-4000-8000-000000000123';
    v_message text;
begin
    insert into raw.pipeline_runs (
        id, initiated_by, mode, status, started_at,
        requested_sources, requested_source_count
    ) values (
        v_run, 'test-024', 'persist', 'running', now(), '{}', 0
    );
    insert into provenance.run_manifests(run_id, stage)
    values (v_run, 'events_persisted');
    insert into provenance.event_run_occurrences (
        run_id, candidate_id, disposition, collector, collector_role, reason_codes
    ) values (
        v_run, v_event::text, 'rejected', 'usgs', 'requested', array['missing_title']
    );
    begin
        perform artifact_id
        from public.persist_canonical_signal_batch(
            v_run,
            jsonb_build_array(pg_temp.signal_item('024-rejected-event', v_event))
        );
        raise exception 'expected rejected event occurrence fatal';
    exception
        when raise_exception then
            get stacked diagnostics v_message = message_text;
            if v_message = 'expected rejected event occurrence fatal' then
                raise;
            end if;
            if v_message <> 'representative canonical Event not persisted in this run' then
                raise exception 'unexpected rejected-event fatal: %', v_message;
            end if;
    end;
end;
$$;
rollback;

-- Constraint error after valid + legacy rolls back
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000024';
    v_event uuid := '02400000-0000-4000-8000-000000000124';
    v_before jsonb;
    v_sqlstate text;
    v_message text;
begin
    perform pg_temp.seed_run(v_run, array[v_event]);
    v_before := pg_temp.seed_legacy('024-legacy-check', v_event);
    begin
        perform artifact_id
        from public.persist_canonical_signal_batch(
            v_run,
            jsonb_build_array(
                pg_temp.signal_item('024-new-check', v_event, 'valid'),
                pg_temp.signal_item('024-legacy-check', v_event),
                pg_temp.signal_item('024-bad-check', v_event, 'bad', '{}'::uuid[], 1.5)
            )
        );
        raise exception 'expected constraint failure';
    exception
        when check_violation then
            get stacked diagnostics v_sqlstate = returned_sqlstate;
            if v_sqlstate is null then
                raise exception 'missing sqlstate';
            end if;
        when raise_exception then
            get stacked diagnostics v_message = message_text;
            if v_message = 'expected constraint failure' then
                raise;
            end if;
            raise;
    end;
    if exists (select 1 from public.researcher_signals where id = '024-new-check') then
        raise exception 'valid write survived constraint fatal';
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-check', v_before);
end;
$$;
rollback;

-- Successful contributor membership + legacy replay stays rejected
begin;
do $$
declare
    v_run uuid := '02400000-0000-4000-8000-000000000025';
    v_rep uuid := '02400000-0000-4000-8000-000000000125';
    v_contrib uuid := '02400000-0000-4000-8000-000000000126';
    v_replay uuid := '02400000-0000-4000-8000-000000000026';
    v_before jsonb;
    v_disp text;
    v_roles text[];
begin
    perform pg_temp.seed_run(v_run, array[v_rep, v_contrib]);
    v_before := pg_temp.seed_legacy('024-legacy-replay', v_rep);
    select disposition into v_disp
    from public.persist_canonical_signal_batch(
        v_run,
        jsonb_build_array(
            pg_temp.signal_item('024-new-contrib-ok', v_rep, 'valid', array[v_contrib]),
            pg_temp.signal_item('024-legacy-replay', v_rep)
        )
    )
    where artifact_id = '024-new-contrib-ok';
    if v_disp <> 'inserted' then
        raise exception 'contributor insert got %', v_disp;
    end if;
    select array_agg(role order by position)
    into v_roles
    from provenance.signal_event_members
    where run_id = v_run and signal_id = '024-new-contrib-ok';
    if v_roles <> array['representative', 'contributor'] then
        raise exception 'unexpected roles: %', v_roles;
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-replay', v_before);

    insert into raw.pipeline_runs (
        id, initiated_by, mode, status, started_at,
        requested_sources, requested_source_count
    ) values (
        v_replay, 'test-024', 'persist', 'running', now(), '{}', 0
    );
    insert into provenance.run_manifests(run_id, stage)
    values (v_replay, 'events_persisted');
    insert into provenance.event_run_occurrences (
        run_id, candidate_id, canonical_event_id, event_revision_id,
        disposition, content_hash, collector, collector_role
    )
    select v_replay, candidate_id, canonical_event_id, event_revision_id,
           'observed_existing', content_hash, collector, collector_role
    from provenance.event_run_occurrences
    where run_id = v_run;

    select disposition into v_disp
    from public.persist_canonical_signal_batch(
        v_replay,
        jsonb_build_array(pg_temp.signal_item('024-legacy-replay', v_rep))
    );
    if v_disp <> 'rejected' then
        raise exception 'legacy replay got %', v_disp;
    end if;
    perform pg_temp.assert_legacy_untouched('024-legacy-replay', v_before);
end;
$$;
rollback;

-- Security / Event RPC / publication isolation
do $$
declare
    v_definer boolean;
    v_search text[];
    v_event_rpc text;
begin
    select p.prosecdef, p.proconfig
    into v_definer, v_search
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'persist_canonical_signal_batch';
    if v_definer is not true then
        raise exception 'SECURITY DEFINER missing';
    end if;
    if v_search is distinct from array['search_path=pg_catalog'] then
        raise exception 'search_path changed: %', v_search;
    end if;
    if has_function_privilege('anon', 'public.persist_canonical_signal_batch(uuid,jsonb)', 'EXECUTE') then
        raise exception 'anon execute granted';
    end if;
    if has_function_privilege('authenticated', 'public.persist_canonical_signal_batch(uuid,jsonb)', 'EXECUTE') then
        raise exception 'authenticated execute granted';
    end if;
    if not has_function_privilege('service_role', 'public.persist_canonical_signal_batch(uuid,jsonb)', 'EXECUTE') then
        raise exception 'service_role execute missing';
    end if;
    if position(
        'on conflict on constraint event_revisions_canonical_event_id_content_hash_key'
        in lower(pg_get_functiondef('public.persist_canonical_event_batch(uuid,jsonb,jsonb)'::regprocedure))
    ) = 0 then
        raise exception '022 Event RPC conflict target missing';
    end if;
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'knowledge'
          and table_name = 'events'
          and column_name in (
              'publication_approved',
              'publication_approved_by',
              'publication_approved_at'
          )
        having count(*) <> 3
    ) then
        raise exception 'publication columns missing';
    end if;
    if (
        select column_default
        from information_schema.columns
        where table_schema = 'knowledge'
          and table_name = 'events'
          and column_name = 'publication_approved'
    ) is distinct from 'false' then
        raise exception 'publication default changed';
    end if;
end;
$$;

select '024 local sql validation passed' as status;
