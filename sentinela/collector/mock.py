"""Collector mock — itens sintéticos in-memory. Zero rede, zero arquivo.
Serve para exercitar a fronteira collector → RawItem sem dependências."""
from __future__ import annotations

from datetime import datetime, timezone

from sentinela.collector.base import Collector, content_hash
from sentinela.core.models import RawItem, Source


class MockCollector:
    kind = "mock"

    def collect(self, source: Source) -> list[RawItem]:
        now = datetime.now(timezone.utc)
        seeds = [
            ("mock-1", "estudo preliminar sobre variabilidade de bloqueios atmosféricos",
             "resumo sintético de um achado de clima para teste do pipeline."),
            ("mock-2", "nova estimativa de sumidouro de carbono em turfeiras",
             "resumo sintético de geociências para teste do pipeline."),
        ]
        items = []
        for ext_id, title, summary in seeds:
            items.append(RawItem(
                source_id=source.id,
                external_id=ext_id,
                url=f"https://example.org/{ext_id}",
                title=title,
                raw_payload={"summary": summary},
                normalized_content=summary,
                content_hash=content_hash(title, summary),
                published_at=now,
                collected_at=now,
            ))
        return items
