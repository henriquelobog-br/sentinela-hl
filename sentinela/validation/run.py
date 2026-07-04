"""
Sentinela HL — CLI do Scientific Validation Report (112.4).

    export OPENROUTER_API_KEY=... OPENROUTER_MODEL_PRIMARY=...
    uv run python -m sentinela.validation.run --collector rss --url <FEED_URL>

Gera reports/validation-YYYY-MM-DD.{json,html} com dados REAIS.
"""

from __future__ import annotations

import argparse
import sys
from uuid import uuid4

from sentinela.clients.base import LLMError
from sentinela.clients.openrouter import OpenRouterClient
from sentinela.collector.mock import MockCollector
from sentinela.collector.rss import RssCollector
from sentinela.core.models import Source, SourceKind
from sentinela.validation.collect_report import build_report, write_report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="validation.run")
    ap.add_argument("--collector", choices=["rss", "mock"], default="rss")
    ap.add_argument("--url", help="URL do feed RSS (obrigatório para --collector rss)")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)

    if args.collector == "rss" and not args.url:
        print("erro: --url é obrigatório para --collector rss", file=sys.stderr)
        return 2

    try:
        llm = OpenRouterClient.from_env()
    except LLMError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1

    source = Source(id=uuid4(), name=args.url or "mock",
                    kind=SourceKind.RSS if args.collector == "rss" else SourceKind.MANUAL,
                    url=args.url)
    collector = RssCollector() if args.collector == "rss" else MockCollector()

    report = build_report(collector, source, llm, model=llm.model_primary)
    jp, hp = write_report(report, out_dir=args.out)
    print(f"json: {jp}")
    print(f"html: {hp}")
    print(f"resumo: {report['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
