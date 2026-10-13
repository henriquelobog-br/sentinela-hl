from pathlib import Path


def test_seismic_editorial_operational_rpc_security_contract():
    sql = Path(
        "supabase/migrations/035_seismic_editorial_operational.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(sql.lower().split())

    assert "security definer" in normalized
    assert normalized.count("security definer") == 2
    assert normalized.count("set search_path = pg_catalog, pg_temp") == 2
    assert "persist_seismic_editorial_batch" in normalized
    assert "list_seismic_editorial_events" in normalized
    assert normalized.count("to service_role") == 2
    assert normalized.count("from public, anon, authenticated") == 2
    assert "grant execute" in normalized
