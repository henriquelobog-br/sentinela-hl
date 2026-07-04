"""Testes do pipeline 112.2B — Collector -> Builder -> Agente. Offline, sem LLM."""
from __future__ import annotations

import json
from uuid import uuid4

from sentinela.clients.fake import FakeLLMClient
from sentinela.collector.mock import MockCollector
from sentinela.collector.rss import RssCollector
from sentinela.core.contract import FilterAgentInput, FilterAgentOutput
from sentinela.core.models import Source, SourceKind
from sentinela.pipeline.run_pipeline import build_inputs, run

SRC = Source(id=uuid4(), name="t", kind=SourceKind.MANUAL)

RSS_XML = ("""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>"""
           """<item><title>estudo sobre clima</title><link>https://www.nature.com/1</link>"""
           """<guid>g1</guid><description>resumo do achado.</description></item></channel></rss>""")

FAKE = FakeLLMClient(json.dumps({
    "provenance": {"result": "pass", "rationale": "x"},
    "epistemic_label": {"result": "pass", "rationale": "x"},
    "calibration": {"result": "pass", "rationale": "x"},
}))


def test_build_inputs_produz_filteragentinput():
    inputs = list(build_inputs(MockCollector(), SRC))
    assert inputs and all(isinstance(i, FilterAgentInput) for i in inputs)


def test_pipeline_completo_mock():
    outs = list(run(MockCollector(), SRC, FAKE))
    assert outs and all(isinstance(o, FilterAgentOutput) for o in outs)
    assert all(o.ok and o.report.decision == "pass" for o in outs)


def test_pipeline_rss_offline():
    outs = list(run(RssCollector(), SRC, FAKE, raw_xml=RSS_XML))
    assert len(outs) == 1 and outs[0].ok
    assert outs[0].report.decision == "pass"


def test_item_a_item():
    # cada RawItem gera exatamente um FilterAgentOutput (sem batch)
    n_inputs = len(list(build_inputs(MockCollector(), SRC)))
    n_outs = len(list(run(MockCollector(), SRC, FAKE)))
    assert n_inputs == n_outs
