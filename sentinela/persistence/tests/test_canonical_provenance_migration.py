import hashlib
import re
from pathlib import Path


def migration_text() -> str:
    return Path(
        "supabase/migrations/021_canonical_event_provenance_v1.sql"
    ).read_text(encoding="utf-8").lower()


def migration_022_text() -> str:
    return Path(
        "supabase/migrations/022_fix_canonical_event_revision_conflict.sql"
    ).read_text(encoding="utf-8").lower()


def migration_023_text() -> str:
    return Path(
        "supabase/migrations/023_fix_canonical_signal_disposition_ambiguity.sql"
    ).read_text(encoding="utf-8").lower()


def migration_024_text() -> str:
    return Path(
        "supabase/migrations/024_allow_item_level_legacy_signal_rejection.sql"
    ).read_text(encoding="utf-8").lower()


def migration_038_text() -> str:
    return Path(
        "supabase/migrations/038_usgs_seismic_source_identity_dedup.sql"
    ).read_text(encoding="utf-8").lower()


def _signal_function(sql: str) -> str:
    start = sql.index(
        "create or replace function public.persist_canonical_signal_batch("
    )
    return sql[start : sql.index("\n$$;", start) + 4]


def test_migration_creates_private_lineage_and_no_legacy_signal_backfill():
    sql = migration_text()
    for table in (
        "provenance.run_manifests",
        "provenance.event_revisions",
        "provenance.event_run_occurrences",
        "provenance.signal_run_occurrences",
        "provenance.signal_event_members",
    ):
        assert f"create table if not exists {table}" in sql
    assert "where created_at" not in sql
    assert "legacy researchersignal cannot be canonical-linked automatically" in sql


def test_migration_enforces_private_security_and_fixed_search_path():
    sql = migration_text()
    assert "revoke all on schema provenance from public, anon, authenticated, service_role" in sql
    assert sql.count("enable row level security") >= 5
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert sql.count("security definer") >= 4
    assert sql.count("set search_path = pg_catalog") >= 6
    assert "create policy" not in sql


def test_migration_protects_curator_fields_and_classifies_dispositions():
    sql = migration_text()
    assert "'inserted', 'updated', 'observed_existing', 'rejected'" in sql
    event_update = sql.split("update knowledge.events set", 1)[1].split(
        "where id = v_event.id", 1
    )[0]
    for field in (
        "primary_claim_id",
        "epistemic_status",
        "confidence_score",
        "pipeline_status",
        "requires_human_review",
        "review_decision",
        "validated_by",
        "validated_at",
        "publication_approved",
    ):
        assert f"{field} =" not in event_update


def test_publication_gate_preserves_existing_seismic_contract():
    sql = migration_text()
    assert "add column if not exists publication_approved" in sql
    assert "migration_021_existing_public_contract" in sql
    assert "where not publication_approved" in sql
    view = sql.split("create or replace view public.v_seismic_events", 1)[1]
    assert "and publication_approved" in view
    assert "approve_canonical_event_publication" in sql
    assert "grant select (publication_approved) on knowledge.events to service_role" in sql


def test_editorial_views_require_publication_without_generating_editorial():
    sql = migration_text()
    seismic = sql.split(
        "create or replace view public.v_seismic_editorial_contents", 1
    )[1].split("alter view public.v_seismic_editorial_contents", 1)[0]
    volcanic = sql.split(
        "create or replace view public.v_volcanic_editorial_contents", 1
    )[1].split("alter view public.v_volcanic_editorial_contents", 1)[0]
    assert "events.publication_approved" in seismic
    assert "events.publication_approved" in volcanic
    assert "insert into editorial." not in sql


def test_canonical_rpc_requires_events_before_signals_and_real_members():
    sql = migration_text()
    assert "canonical events must be persisted before signals" in sql
    assert "canonical run manifest must be started first" in sql
    assert "begin_canonical_run_manifest" in sql
    assert "representative canonical event not persisted in this run" in sql
    assert "contributor canonical event not persisted in this run" in sql
    assert "canonical_event_id uuid not null" in sql


def test_migration_does_not_generate_editorial_or_expose_provenance_view():
    sql = migration_text()
    assert "insert into editorial." not in sql
    assert "create view public.v_provenance" not in sql
    assert "create view public.v_lineage" not in sql


def test_event_revisions_and_occurrences_are_idempotently_constrained():
    sql = migration_text()
    assert "unique (canonical_event_id, content_hash)" in sql
    assert "primary key (run_id, candidate_id)" in sql
    assert "conflicting canonical event retry" in sql
    assert "on conflict (canonical_event_id, content_hash)" in sql


def test_signal_occurrence_and_membership_are_idempotently_constrained():
    sql = migration_text()
    assert "primary key (run_id, signal_id)" in sql
    assert "primary key (run_id, signal_id, canonical_event_id)" in sql
    assert "references provenance.signal_run_occurrences(run_id, signal_id)" in sql
    assert "signal_event_members_one_representative_idx" in sql
    assert "where role = 'representative'" in sql
    assert "conflicting canonical signal retry" in sql
    assert "delete from provenance.signal_event_members" not in sql


def test_manifest_records_recovery_stage_counts_versions_and_hash():
    sql = migration_text()
    for field in (
        "manifest_version",
        "stage",
        "accepted_event_count",
        "rejected_event_count",
        "persisted_signal_count",
        "versions",
        "commit_state",
        "manifest_hash",
        "finalized_at",
    ):
        assert field in sql
    assert "canonical run manifest already finalized differently" in sql
    assert "if v_current.manifest_hash = v_hash" in sql
    assert "commit_state in ('known', 'ambiguous')" in sql


def test_canonical_persistence_defaults_to_unpublished_and_noncurated():
    sql = migration_text()
    assert "publication_approved boolean not null default false" in sql
    assert "'normalized', false, 'pending', null, null, null" in sql
    assert "canonical persistence never sets this true" in sql


def test_no_direct_provenance_table_grants_are_given_to_browser_roles():
    sql = migration_text()
    assert "revoke all on all tables in schema provenance" in sql
    assert "grant select on provenance." not in sql
    assert "grant insert on provenance." not in sql


def test_022_reproduces_and_fixes_event_revision_conflict_ambiguity():
    old = migration_text()
    fixed = migration_022_text()
    assert "returns table (" in old
    assert "content_hash text" in old
    assert "on conflict (canonical_event_id, content_hash) do update" in old
    assert (
        "on conflict on constraint "
        "event_revisions_canonical_event_id_content_hash_key"
    ) in fixed
    assert "on conflict (canonical_event_id, content_hash)" not in fixed


def test_022_only_replaces_event_rpc_and_preserves_security_contract():
    sql = migration_022_text()
    assert sql.count("create or replace function") == 1
    assert "public.persist_canonical_event_batch(" in sql
    assert "returns table (" in sql
    assert "artifact_id text" in sql
    assert "disposition text" in sql
    assert "content_hash text" in sql
    assert "revision_id uuid" in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "update knowledge.events set" in sql
    assert "publication_approved =" not in sql
    assert "update public.researcher_signals" not in sql
    assert "insert into editorial." not in sql
    assert "create or replace view" not in sql


def test_other_canonical_conflict_targets_do_not_collide_with_out_variables():
    sql = migration_text()
    assert "on conflict (run_id, candidate_id) do nothing" in sql
    assert "on conflict (run_id, signal_id) do nothing" in sql
    assert "on conflict (run_id, signal_id, canonical_event_id) do nothing" in sql
    assert "run_id text" not in sql
    assert "signal_id text" not in sql.split(
        "returns table (", 2
    )[2].split(")", 1)[0]


def test_023_follows_022_and_preserves_frozen_migration_hashes():
    migrations = sorted(Path("supabase/migrations").glob("*.sql"))
    names = [path.name for path in migrations]
    assert names.index("023_fix_canonical_signal_disposition_ambiguity.sql") == (
        names.index("022_fix_canonical_event_revision_conflict.sql") + 1
    )
    expected = {
        "021_canonical_event_provenance_v1.sql": (
            "fff557ecf8d253f506a2537f6bd335563bde97d62165a02a55b6896ae222d9e7"
        ),
        "022_fix_canonical_event_revision_conflict.sql": (
            "93bb9a695dc1bfa66ce0a6d715a6d546dc70312bf93b7db35909f8118d3a8f4b"
        ),
    }
    for name, digest in expected.items():
        actual = hashlib.sha256(
            (Path("supabase/migrations") / name).read_bytes()
        ).hexdigest()
        assert actual == digest


def test_023_preserves_signal_rpc_signature_return_and_security():
    sql = migration_023_text()
    assert sql.count("create or replace function") == 1
    assert (
        "public.persist_canonical_signal_batch(\n"
        "    p_run_id uuid,\n"
        "    p_signals jsonb"
    ) in sql
    returns = sql.split("returns table (", 1)[1].split(")", 1)[0]
    assert returns.split() == [
        "artifact_id",
        "text,",
        "disposition",
        "text,",
        "content_hash",
        "text",
    ]
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_023_qualifies_both_event_occurrence_dispositions():
    function = _signal_function(migration_023_text())
    assert function.count("from provenance.event_run_occurrences as ero") == 2
    assert function.count("and ero.disposition <> 'rejected'") == 2
    assert re.search(r"(?m)^\s*and disposition\s*<>\s*'rejected'", function) is None
    representative = function.split(
        "representative canonical event not persisted in this run", 1
    )[0]
    contributor = function.split(
        "representative canonical event not persisted in this run", 1
    )[1].split("contributor canonical event not persisted in this run", 1)[0]
    assert "ero.canonical_event_id = v_representative" in representative
    assert "ero.canonical_event_id = v_contributor" in contributor


def test_023_function_diff_is_limited_to_two_event_occurrence_aliases():
    original = _signal_function(migration_text())
    fixed = _signal_function(migration_023_text())
    normalized = fixed.replace(
        "from provenance.event_run_occurrences as ero",
        "from provenance.event_run_occurrences",
    )
    normalized = normalized.replace("ero.run_id", "run_id")
    normalized = normalized.replace("ero.canonical_event_id", "canonical_event_id")
    normalized = normalized.replace("ero.disposition", "disposition")
    assert normalized == original
    assert fixed.count("content_hash") == original.count("content_hash")
    assert fixed.count("signal_id") == original.count("signal_id")


def test_023_has_no_top_level_data_or_publication_changes():
    sql = migration_023_text()
    top_level = re.sub(r"as \$\$.*?\$\$;", "", sql, flags=re.DOTALL)
    assert re.search(r"(?m)^\s*(insert|update|delete)\s", top_level) is None
    assert "persist_canonical_event_batch" not in sql
    assert "publication_approved" not in sql
    assert "create or replace view" not in sql
    assert "alter view" not in sql
    assert "insert into editorial." not in top_level


_FROZEN_MIGRATION_HASHES = {
    "021_canonical_event_provenance_v1.sql": (
        "fff557ecf8d253f506a2537f6bd335563bde97d62165a02a55b6896ae222d9e7"
    ),
    "022_fix_canonical_event_revision_conflict.sql": (
        "93bb9a695dc1bfa66ce0a6d715a6d546dc70312bf93b7db35909f8118d3a8f4b"
    ),
    "023_fix_canonical_signal_disposition_ambiguity.sql": (
        "f632b012b4bdc59c7677f0406aafb60588f9e0b9389e06d1fd6ae92c4a9cb4bf"
    ),
}


_023_LEGACY_BRANCH = """        if v_signal_exists and not exists (
            select 1 from provenance.signal_event_members
            where signal_id = v_signal.id
        ) then
            raise exception 'legacy researchersignal cannot be canonical-linked automatically';
        end if;"""

_024_LEGACY_BRANCH = """        if v_signal_exists and not exists (
            select 1 from provenance.signal_event_members
            where signal_id = v_signal.id
        ) then
            artifact_id := v_signal.id;
            disposition := 'rejected';
            content_hash := null;
            return next;
            continue;
        end if;"""


def test_024_follows_023_and_preserves_frozen_migration_hashes():
    migrations = sorted(Path("supabase/migrations").glob("*.sql"))
    names = [path.name for path in migrations]
    assert names.index("024_allow_item_level_legacy_signal_rejection.sql") == (
        names.index("023_fix_canonical_signal_disposition_ambiguity.sql") + 1
    )
    for name, digest in _FROZEN_MIGRATION_HASHES.items():
        actual = hashlib.sha256(
            (Path("supabase/migrations") / name).read_bytes()
        ).hexdigest()
        assert actual == digest


def test_024_preserves_signal_rpc_signature_return_and_security():
    sql = migration_024_text()
    assert sql.count("create or replace function") == 1
    assert (
        "public.persist_canonical_signal_batch(\n"
        "    p_run_id uuid,\n"
        "    p_signals jsonb"
    ) in sql
    returns = sql.split("returns table (", 1)[1].split(")", 1)[0]
    assert returns.split() == [
        "artifact_id",
        "text,",
        "disposition",
        "text,",
        "content_hash",
        "text",
    ]
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_024_converts_legacy_collision_to_item_level_rejected():
    function = _signal_function(migration_024_text())
    assert _024_LEGACY_BRANCH in function
    assert "artifact_id := v_signal.id;" in function
    assert "disposition := 'rejected';" in function
    assert "content_hash := null;" in function
    assert "return next;" in function
    assert "continue;" in function
    assert (
        "raise exception 'legacy researchersignal cannot be canonical-linked automatically'"
        not in function
    )
    assert "representative canonical event not persisted in this run" in function
    assert "contributor canonical event not persisted in this run" in function
    assert "and ero.disposition <> 'rejected'" in function
    assert function.count("from provenance.event_run_occurrences as ero") == 2


def test_024_function_diff_is_limited_to_legacy_collision_branch():
    original = _signal_function(migration_023_text())
    fixed = _signal_function(migration_024_text())
    assert _023_LEGACY_BRANCH in original
    assert _024_LEGACY_BRANCH in fixed
    normalized = fixed.replace(_024_LEGACY_BRANCH, _023_LEGACY_BRANCH)
    assert normalized == original


def test_024_has_no_top_level_data_or_publication_changes():
    sql = migration_024_text()
    top_level = re.sub(r"as \$\$.*?\$\$;", "", sql, flags=re.DOTALL)
    assert re.search(r"(?m)^\s*(insert|update|delete)\s", top_level) is None
    assert "persist_canonical_event_batch" not in sql
    assert "publication_approved" not in sql
    assert "create or replace view" not in sql
    assert "alter view" not in sql
    assert "insert into editorial." not in top_level
    assert "create table" not in sql
    assert "alter table" not in sql
    assert "drop " not in sql
    assert "truncate" not in sql


def test_038_is_transactional_and_materializes_frozen_cleanup_sets():
    sql = migration_038_text()
    assert sql.startswith("-- 038_usgs_seismic_source_identity_dedup.sql")
    assert "begin;" in sql
    assert sql.rstrip().endswith("commit;")
    assert "create temporary table usgs_seismic_event_dedup_map" in sql
    assert "create temporary table usgs_seismic_revision_moves" in sql
    assert "create temporary table usgs_seismic_occurrence_moves" in sql
    assert "create temporary table usgs_seismic_editorial_deletes" in sql
    assert "nullif(events.evidence -> 0 ->> 'updated_at', '')::timestamptz desc nulls last" in sql
    assert "events.created_at desc" in sql
    assert "events.id desc" in sql


def test_038_freezes_legacy_counts_and_remaps_only_supported_dependencies():
    sql = migration_038_text()
    for expected in (
        "v_initial_count <> 254",
        "v_distinct_count <> 202",
        "v_mapping_count <> 52",
        "v_revision_moves <> 111",
        "v_occurrence_moves <> 111",
        "v_editorial_deletes <> 51",
        "v_published_keepers <> 7",
        "v_published_removed <> 0",
        "v_actual_revision_moves <> 111",
        "v_actual_occurrence_moves <> 111",
        "v_actual_editorial_deletes <> 51",
        "v_actual_event_deletes <> 52",
    ):
        assert expected in sql
    assert "set canonical_event_id = moves.keep_id" in sql
    assert "set canonical_event_id = moves.keep_id\n    from usgs_seismic_occurrence_moves" in sql
    assert "set event_revision_id" not in sql
    assert "delete from editorial.seismic_contents" in sql
    assert "delete from knowledge.events" in sql


def test_038_fails_closed_on_collisions_counterparts_publication_and_references():
    sql = migration_038_text()
    assert "usgs revision hash collision after keeper collapse" in sql
    assert "duplicate seismic editorial lacks keeper counterpart" in sql
    assert "removed event referenced by signal_event_members" in sql
    assert "removed event referenced by bulletin_events" in sql
    assert "removed event referenced by contradictions" in sql
    assert "removed event referenced by researcher_signals" in sql
    assert "removed event referenced by volcanic editorial" in sql
    assert "publication_approved" in sql
    assert "if v_mapping_count = 0 then\n        return;" in sql


def test_038_installs_partial_unique_usgs_source_identity_guard():
    sql = migration_038_text()
    index = sql.split(
        "create unique index if not exists events_usgs_seismic_source_event_id_uidx",
        1,
    )[1].split("drop function", 1)[0]
    assert "evidence -> 0 ->> 'source_event_id'" in index
    assert "source = 'usgs'" in index
    assert "scientific_area = 'seismology'" in index
    assert "category = 'earthquake_detected'" in index
    assert "source identity unique guard is not valid" in sql


def test_038_event_rpc_reconciles_keeper_and_returns_effective_id():
    sql = migration_038_text()
    returns = sql.split("returns table (", 1)[1].split(")", 1)[0]
    assert "artifact_id text" in returns
    assert "canonical_event_id uuid" in returns
    assert "disposition text" in returns
    assert "content_hash text" in returns
    assert "revision_id uuid" in returns
    assert "v_candidate_event_id := v_event.id" in sql
    assert "existing.evidence -> 0 ->> 'source_event_id'" in sql
    assert "v_event.id := v_existing.id" in sql
    assert "artifact_id := v_candidate_id" in sql
    assert "canonical_event_id := v_effective.id" in sql
    assert "canonical_event_id := null" in sql
    assert "p_run_id, v_candidate_id, v_effective.id, v_revision_id" in sql


def test_038_preserves_keeper_pk_curator_fields_and_rpc_security():
    sql = migration_038_text()
    event_update = sql.split("update knowledge.events as events set", 1)[1].split(
        "where events.id = v_existing.id", 1
    )[0]
    assert "id =" not in event_update
    for field in (
        "primary_claim_id",
        "epistemic_status",
        "confidence_score",
        "pipeline_status",
        "requires_human_review",
        "review_decision",
        "validated_by",
        "validated_at",
        "publication_approved",
    ):
        assert f"{field} =" not in event_update
    assert "drop function public.persist_canonical_event_batch(uuid, jsonb, jsonb)" in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_038_keeps_newer_usgs_snapshot_when_older_revision_arrives_late():
    sql = migration_038_text()
    assert "v_incoming_updated_at timestamptz" in sql
    assert "v_existing_updated_at timestamptz" in sql
    assert "usgs seismic event updated_at is required" in sql
    assert "canonical usgs seismic event updated_at is required" in sql
    assert "v_incoming_updated_at < v_existing_updated_at" in sql
    stale_branch = sql.split(
        "v_incoming_updated_at < v_existing_updated_at then", 1
    )[1].split("elsif", 1)[0]
    assert "v_effective := v_existing" in stale_branch
    assert "v_disposition := 'observed_existing'" in stale_branch
    assert "update knowledge.events" not in stale_branch
    assert "v_effective.id, v_incoming_hash, v_snapshot" in sql


def test_038_resolves_concurrent_first_insert_to_source_identity_winner():
    sql = migration_038_text()
    assert "on conflict do nothing" in sql
    race_branch = sql.split("if v_inserted then", 1)[1].split(
        "if v_existing_found then", 1
    )[0]
    assert "existing.evidence -> 0 ->> 'source_event_id'" in race_branch
    assert "for update" in race_branch
    assert "v_existing_found := found" in race_branch
    assert "insert conflicted without a compatible winner" in race_branch
    assert "v_event.id := v_existing.id" in race_branch
    assert "events_usgs_seismic_source_event_id_uidx" in sql


def test_038_preserves_keeper_editorial_without_claiming_sql_freshness():
    sql = migration_038_text()
    assert "duplicate seismic editorial lacks keeper counterpart" in sql
    assert "delete from editorial.seismic_contents" in sql
    assert "update editorial.seismic_contents" not in sql
    assert "insert into editorial.seismic_contents" not in sql
    assert "input_facts_signature =" not in sql
