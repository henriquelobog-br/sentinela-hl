"""Testes do PostgresWriter (112.5).

Integração: rodam contra um Postgres com o schema (raw + knowledge). Se não
houver banco (SENTINELA_TEST_DSN ausente/indisponível), são pulados.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

from sentinela.builder.evidence_builder import EvidenceBuilder
from sentinela.clients.fake import FakeLLMClient
from sentinela.core.models import RawItem, Source, SourceKind
from sentinela.engines.agent import evaluate
from sentinela.writer.postgres import PostgresWriter, persist_pipeline_result

DSN = os.environ.get("SENTINELA_TEST_DSN")


def _verdict(prov="pass", label="pass", calib="pass"):
    return FakeLLMClient(json.dumps({
        "provenance": {"result": prov, "rationale": "r"},
        "epistemic_label": {"result": label, "rationale": "r"},
        "calibration": {"result": calib, "rationale": "r"},
    }))


def _raw(ext="e1", title="estudo sobre clima", url="https://www.nature.com/x"):
    return RawItem(source_id=uuid4(), external_id=ext, title=title, url=url,
                   normalized_content="resumo do achado climático.",
                   content_hash=f"h-{ext}", published_at=datetime.now(timezone.utc))


def _src(name=None):
    return Source(name=name or f"feed-{uuid4().hex[:8]}", kind=SourceKind.RSS,
                  url="https://example.org/feed")


@pytest.fixture()
def conn():
    if not DSN:
        pytest.skip("SENTINELA_TEST_DSN não definido")
    with psycopg.connect(DSN) as c:
        yield c


def _run(conn, raw, source, llm):
    inp = EvidenceBuilder().build(raw)
    out = evaluate(inp, llm)
    return persist_pipeline_result(conn, raw, inp, out, source)


# ---------------- pass / escalate / reject ----------------
def test_pass_cria_evento(conn):
    res = _run(conn, _raw("p1"), _src(), _verdict())
    assert res["decision"] == "pass" and res["pipeline_status"] == "validated"
    assert res["event_id"] is not None
    with conn.cursor() as cur:
        cur.execute("select requires_human_review, review_decision from knowledge.events where id=%s",
                    (res["event_id"],))
        review, decision = cur.fetchone()
    assert review is False and decision == "pending"


def test_escalate_cria_evento_com_revisao(conn):
    res = _run(conn, _raw("e1"), _src(), _verdict(label="flag"))
    assert res["decision"] == "escalate" and res["pipeline_status"] == "escalated"
    assert res["event_id"] is not None
    with conn.cursor() as cur:
        cur.execute("select requires_human_review from knowledge.events where id=%s", (res["event_id"],))
        assert cur.fetchone()[0] is True


def test_reject_nao_cria_evento_mas_preserva_auditoria(conn):
    res = _run(conn, _raw("r1"), _src(), _verdict(prov="fail"))
    assert res["decision"] == "reject" and res["pipeline_status"] == "rejected"
    assert res["event_id"] is None
    with conn.cursor() as cur:
        cur.execute("select count(*) from knowledge.classifications where claim_id=%s", (res["claim_id"],))
        assert cur.fetchone()[0] == 3          # trilha de auditoria preservada


# ---------------- dedup ----------------
def test_dedup_external_id(conn):
    src = _src()
    r1 = _run(conn, _raw("dup1"), src, _verdict())
    r2 = _run(conn, _raw("dup1"), src, _verdict())    # mesmo external_id
    assert r1["raw_item_id"] == r2["raw_item_id"]
    assert r1["is_new"] is True and r2["is_new"] is False


def test_dedup_content_hash(conn):
    src = _src()
    a = _raw("x"); a.external_id = None
    b = _raw("y"); b.external_id = None; b.content_hash = a.content_hash
    r1 = _run(conn, a, src, _verdict())
    r2 = _run(conn, b, src, _verdict())
    assert r1["raw_item_id"] == r2["raw_item_id"]     # dedup pelo hash


# ---------------- classifications: prompt_version + run_id ----------------
def test_classifications_guardam_prompt_version_e_run_id(conn):
    res = _run(conn, _raw("c1"), _src(), _verdict())
    with conn.cursor() as cur:
        cur.execute("""select prompt_version, detail->>'run_id'
                         from knowledge.classifications where claim_id=%s limit 1""",
                    (res["claim_id"],))
        pv, run_id = cur.fetchone()
    assert pv == "filter_v1"
    assert run_id


# ---------------- rollback ----------------
def test_rollback_em_falha(conn):
    """Se algo estourar no meio, nada é gravado (transação por item)."""
    src = _src()
    with conn.cursor() as cur:
        cur.execute("select count(*) from knowledge.claims")
        before = cur.fetchone()[0]

    raw = _raw("rb1")
    inp = EvidenceBuilder().build(raw)
    out = evaluate(inp, _verdict())
    # sabota: statement None viola not-null de knowledge.claims
    inp.claim.statement = None
    with pytest.raises(Exception):
        persist_pipeline_result(conn, raw, inp, out, src)
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute("select count(*) from knowledge.claims")
        after = cur.fetchone()[0]
        cur.execute("select count(*) from raw.items where external_id=%s", ("rb1",))
        item_count = cur.fetchone()[0]
    assert after == before          # nenhuma claim gravada
    assert item_count == 0          # nem o item bruto — rollback pegou tudo


# ---------------- fetch_run ----------------
def test_fetch_run_lifecycle(conn):
    w = PostgresWriter(conn)
    sid = w.ensure_source(_src())
    fid = w.start_fetch_run(sid)
    w.finish_fetch_run(fid, status="success", items_found=3, items_new=2, items_duplicate=1)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select status, items_found, items_new, finished_at from raw.fetch_runs where id=%s", (fid,))
        status, found, new, finished = cur.fetchone()
    assert status == "success" and found == 3 and new == 2 and finished is not None


def test_ensure_source_idempotente(conn):
    w = PostgresWriter(conn)
    s = _src("fonte-fixa")
    a = w.ensure_source(s); conn.commit()
    b = w.ensure_source(s); conn.commit()
    assert a == b
