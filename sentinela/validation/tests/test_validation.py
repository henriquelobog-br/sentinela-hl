"""Testes do 112.4 — mecânica offline (fake LLM). O RSS+OpenRouter reais são teste de máquina."""
from __future__ import annotations

import json
from uuid import uuid4

from sentinela.collector.rss import RssCollector
from sentinela.core.models import Source, SourceKind
from sentinela.validation.collect_report import build_report, write_report
from sentinela.validation.render_html import render_html

SRC = Source(id=uuid4(), name="feed teste", kind=SourceKind.RSS, url="https://www.nature.com/feed")

RSS_XML = ("""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>"""
           """<item><title>estudo sobre transporte de poeira atmosférica</title>"""
           """<link>https://www.nature.com/a1</link><guid>g1</guid>"""
           """<description>análise de reanálise sobre poeira; classificado como hipótese.</description></item>"""
           """<item><title>segundo achado climático</title><link>https://www.nature.com/a2</link>"""
           """<guid>g2</guid><description>resumo do segundo item.</description></item></channel></rss>""")


class RouterFake:
    def complete(self, *, system, user, temperature=0.0, max_tokens=1024, extra=None):
        return json.dumps({
            "provenance": {"result": "pass", "rationale": "a fonte sustenta a afirmação."},
            "epistemic_label": {"result": "pass", "rationale": "hipótese é honesta para a evidência."},
            "calibration": {"result": "pass", "rationale": "confiança condiz com evidência parcial."},
        })


def test_build_report_structure():
    rep = build_report(RssCollector(), SRC, RouterFake(), raw_xml=RSS_XML, model="modelo-teste")
    assert rep["summary"]["total"] == 2
    assert rep["summary"]["pass"] == 2
    assert len(rep["items"]) == 2
    assert rep["items"][0]["output"]["ok"]


def test_render_html_valido():
    rep = build_report(RssCollector(), SRC, RouterFake(), raw_xml=RSS_XML, model="modelo-teste")
    h = render_html(rep)
    assert h.startswith("<!doctype html>")
    assert "scientific validation report" in h
    assert "#08090a" in h            # dark
    assert "#ffffff" not in h.lower() # sem branco puro
    assert "transition" not in h and "animation" not in h and "@keyframes" not in h  # zero motion


def test_write_report(tmp_path):
    rep = build_report(RssCollector(), SRC, RouterFake(), raw_xml=RSS_XML, model="m")
    jp, hp = write_report(rep, out_dir=tmp_path)
    assert jp.exists() and hp.exists()
    json.loads(jp.read_text(encoding="utf-8"))  # json válido
