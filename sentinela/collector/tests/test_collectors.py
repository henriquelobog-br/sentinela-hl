"""Testes do Collector Adapter (112.2A) — offline, sem rede."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from sentinela.collector.base import Collector
from sentinela.collector.mock import MockCollector
from sentinela.collector.file import FileCollector
from sentinela.collector.rss import RssCollector
from sentinela.core.models import RawItem, Source, SourceKind

SRC = Source(id=uuid4(), name="t", kind=SourceKind.RSS)

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
<item><title>item um</title><link>https://ex.org/1</link><guid>g1</guid>
<description>resumo um</description><pubDate>Wed, 02 Oct 2024 10:00:00 GMT</pubDate></item>
<item><title>item dois</title><link>https://ex.org/2</link><guid>g2</guid>
<description>resumo dois</description></item></channel></rss>"""


def _all_rawitems(items):
    return items and all(isinstance(i, RawItem) for i in items)


def test_protocol():
    assert isinstance(MockCollector(), Collector)
    assert isinstance(RssCollector(), Collector)


def test_mock_sem_rotulo():
    items = MockCollector().collect(SRC)
    assert _all_rawitems(items)
    it = items[0]
    assert not hasattr(it, "epistemic_status")
    assert not hasattr(it, "confidence_score")
    assert it.content_hash


def test_file(tmp_path: Path):
    p = tmp_path / "coleta.json"
    p.write_text(json.dumps([
        {"id": "a1", "title": "t1", "summary": "s1", "link": "https://ex.org/a1"},
        {"id": "a2", "title": "t2", "content": "c2"},
    ]), encoding="utf-8")
    items = FileCollector(p).collect(SRC)
    assert _all_rawitems(items) and len(items) == 2
    assert items[0].external_id == "a1"


def test_rss_offline():
    items = RssCollector().collect(SRC, raw_xml=RSS_XML)
    assert _all_rawitems(items) and len(items) == 2
    assert items[0].external_id == "g1"
    assert items[0].published_at is not None
    assert items[1].published_at is None  # segundo item sem pubDate


def test_saida_sempre_rawitem():
    items = MockCollector().collect(SRC) + RssCollector().collect(SRC, raw_xml=RSS_XML)
    assert all(isinstance(i, RawItem) for i in items)
    assert all(i.content_hash for i in items)
