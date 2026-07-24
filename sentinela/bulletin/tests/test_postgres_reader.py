"""Integração do PostgresEventReader (112.6A). Pulado sem SENTINELA_TEST_DSN."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

from sentinela.builder.evidence_builder import EvidenceBuilder
from sentinela.bulletin.engine import BulletinEngine
from sentinela.bulletin.postgres_reader import PostgresEventReader
from sentinela.clients.fake import FakeLLMClient
from sentinela.core.models import Event, RawItem, Source, SourceKind
from sentinela.engines.agent import evaluate
from sentinela.writer.postgres import persist_pipeline_result

DSN = os.environ.get("SENTINELA_TEST_DSN")


@pytest.fixture()
def conn():
    if not DSN:
        pytest.skip("SENTINELA_TEST_DSN não definido")
    with psycopg.connect(DSN) as c:
        yield c


def _verdict(prov="pass", label="pass"):
    return FakeLLMClient(json.dumps({
        "provenance": {"result": prov, "rationale": "r"},
        "epistemic_label": {"result": label, "rationale": "r"},
        "calibration": {"result": "pass", "rationale": "r"},
    }))


def _seed(conn, ext, title, url, llm):
    src = Source(name=f"f-{uuid4().hex[:6]}", kind=SourceKind.RSS, url="https://ex.org/f")
    raw = RawItem(source_id=uuid4(), external_id=ext, title=title, url=url,
                  normalized_content="resumo.", content_hash=f"h-{ext}",
                  published_at=datetime.now(timezone.utc))
    inp = EvidenceBuilder().build(raw)
    out = evaluate(inp, llm)
    res = persist_pipeline_result(conn, raw, inp, out, src)
    conn.commit()
    return res


def test_reader_devolve_events_do_core(conn):
    _seed(conn, f"i{uuid4().hex[:6]}", "evento validado", "https://www.noaa.gov/x", _verdict())
    events = PostgresEventReader(conn).fetch_eligible_events(limit=50)
    assert events and all(isinstance(e, Event) for e in events)


def test_reader_ignora_rejects(conn):
    r = _seed(conn, f"rj{uuid4().hex[:6]}", "rejeitado", "https://www.nature.com/x", _verdict(prov="fail"))
    assert r["event_id"] is None                       # reject não cria evento
    events = PostgresEventReader(conn).fetch_eligible_events(limit=200)
    assert all(e.title != "rejeitado" for e in events)


def test_reader_traz_escalated_com_review(conn):
    _seed(conn, f"es{uuid4().hex[:6]}", "escalado para curadoria",
          "https://www.nature.com/x", _verdict(label="flag"))
    events = PostgresEventReader(conn).fetch_eligible_events(limit=200)
    esc = [e for e in events if e.title == "escalado para curadoria"]
    assert esc and esc[0].requires_human_review is True


def test_fluxo_completo_writer_reader_engine(conn):
    _seed(conn, f"fc{uuid4().hex[:6]}", "fluxo completo", "https://www.noaa.gov/x", _verdict())
    events = PostgresEventReader(conn).fetch_eligible_events(limit=200)
    model = BulletinEngine().build(events)
    assert model.total_items == len(events)
    # itens que exigem revisão nunca vêm antes dos que não exigem, dentro da seção
    for s in model.sections:
        flags = [i.requires_review for i in s.items]
        assert flags == sorted(flags)                  # False antes de True
