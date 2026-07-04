"""
Sentinela HL — pipeline Collector -> Builder -> Agente (Documento 112.2B).

Costura as três peças SEM tocar em nenhuma. Item-a-item (sem batch, async ou
fila). Não reimplementa nada: só chama os contratos que já existem.

Dois modos:
  - emit-input : Collector -> Builder -> imprime FilterAgentInput (JSONL) no
                 stdout. É o que o n8n consome: `... | run_filters -`.
  - run        : Collector -> Builder -> Agente (evaluate) -> FilterAgentOutput.
                 Caminho Python puro, testável com FakeLLMClient.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from uuid import uuid4

from sentinela.builder.claim_builder import ClaimBuilder
from sentinela.clients.base import LLMClient, LLMError
from sentinela.clients.openrouter import OpenRouterClient
from sentinela.collector.base import Collector
from sentinela.collector.mock import MockCollector
from sentinela.collector.rss import RssCollector
from sentinela.core.contract import FilterAgentInput, FilterAgentOutput
from sentinela.core.models import Source, SourceKind
from sentinela.engines.agent import evaluate


def build_inputs(collector: Collector, source: Source, *, raw_xml: str | None = None) -> Iterator[FilterAgentInput]:
    """Collector -> RawItem -> Builder -> FilterAgentInput, item-a-item."""
    builder = ClaimBuilder()
    if raw_xml is not None and isinstance(collector, RssCollector):
        raws = collector.collect(source, raw_xml=raw_xml)
    else:
        raws = collector.collect(source)
    for raw in raws:
        yield builder.build(raw)   # RawItem -> FilterAgentInput (sem tocar no agente)


def run(collector: Collector, source: Source, llm: LLMClient, *, raw_xml: str | None = None) -> Iterator[FilterAgentOutput]:
    """Pipeline completo, item-a-item. Reusa evaluate() do agente 113 intacto."""
    for inp in build_inputs(collector, source, raw_xml=raw_xml):
        yield evaluate(inp, llm)


# ------------------------------------------------------------------ CLI
def _make_collector(kind: str) -> Collector:
    return {"mock": MockCollector, "rss": RssCollector}[kind]()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_pipeline",
                                 description="Collector -> Builder -> (Agente)")
    ap.add_argument("--collector", choices=["mock", "rss"], default="mock")
    ap.add_argument("--url", help="URL do feed (para --collector rss)")
    ap.add_argument("--mode", choices=["emit-input", "run"], default="emit-input",
                    help="emit-input: só Collector->Builder (p/ n8n via stdin). run: pipeline completo.")
    args = ap.parse_args(argv)

    source = Source(id=uuid4(), name=args.collector,
                    kind=SourceKind.RSS if args.collector == "rss" else SourceKind.MANUAL,
                    url=args.url)
    collector = _make_collector(args.collector)

    if args.mode == "emit-input":
        # JSONL: um FilterAgentInput por linha — o n8n encaminha cada linha ao run_filters
        try:
            for inp in build_inputs(collector, source):
                print(json.dumps(inp.model_dump(mode="json"), ensure_ascii=False))
        except BrokenPipeError:
            # consumidor fechou o pipe cedo (ex.: head) — encerra em silêncio
            try:
                sys.stdout.close()
            except Exception:
                pass
        return 0

    # mode == run: precisa de LLM real
    try:
        llm = OpenRouterClient.from_env()
    except LLMError as e:
        print(json.dumps({"ok": False, "error": {"error": "llm_error", "message": str(e)}}))
        return 1
    rc = 0
    for out in run(collector, source, llm):
        print(json.dumps(out.model_dump(mode="json"), ensure_ascii=False))
        if not out.ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
