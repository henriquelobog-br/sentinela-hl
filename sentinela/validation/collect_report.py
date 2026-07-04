"""
Sentinela HL — Scientific Validation Report (Documento 112.4).

Roda o pipeline real (collector -> builder -> agente) sobre N itens e materializa:
  reports/validation-YYYY-MM-DD.json   registro completo (fonte da verdade)
  reports/validation-YYYY-MM-DD.html   ficha legível para o Henrique revisar

Não persiste em banco, não usa n8n. Só executa o pipeline e reporta — com os
sinais do builder, o rationale de cada filtro e o tempo por item.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sentinela.builder.claim_builder import ClaimBuilder
from sentinela.clients.base import LLMClient
from sentinela.collector.base import Collector
from sentinela.core.contract import FilterAgentInput
from sentinela.core.models import Source
from sentinela.engines.agent import evaluate
from sentinela.validation.render_html import render_html


def _run_item(inp: FilterAgentInput, llm: LLMClient) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = evaluate(inp, llm)
    ms = round((time.perf_counter() - t0) * 1000)
    usage = getattr(llm, "last_usage", None)  # tokens, se o client expuser
    return {
        "input": inp.model_dump(mode="json"),
        "output": out.model_dump(mode="json"),
        "elapsed_ms": ms,
        "usage": usage,
    }


def build_report(collector: Collector, source: Source, llm: LLMClient,
                 *, raw_xml: str | None = None, model: str | None = None) -> dict[str, Any]:
    builder = ClaimBuilder()
    raws = collector.collect(source, raw_xml=raw_xml) if raw_xml is not None else collector.collect(source)
    items = [_run_item(builder.build(raw), llm) for raw in raws]
    decisions = [i["output"].get("report", {}).get("decision") if i["output"]["ok"] else "error" for i in items]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "source": {"name": source.name, "url": source.url},
        "summary": {
            "total": len(items),
            "pass": decisions.count("pass"),
            "escalate": decisions.count("escalate"),
            "reject": decisions.count("reject"),
            "error": decisions.count("error"),
            "total_ms": sum(i["elapsed_ms"] for i in items),
        },
        "items": items,
    }


def write_report(report: dict[str, Any], out_dir: str | Path = "reports") -> tuple[Path, Path]:
    out = Path(out_dir); out.mkdir(exist_ok=True)
    stamp = date.today().isoformat()
    json_path = out / f"validation-{stamp}.json"
    html_path = out / f"validation-{stamp}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return json_path, html_path
