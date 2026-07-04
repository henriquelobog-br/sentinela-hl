"""Collector de arquivo — lê itens de um JSON local (lista de objetos).
Útil para replay/fixtures de coleta sem depender de rede."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sentinela.collector.base import content_hash
from sentinela.core.models import RawItem, Source


class FileCollector:
    kind = "file"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def collect(self, source: Source) -> list[RawItem]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("arquivo de coleta deve ser uma lista de objetos")
        now = datetime.now(timezone.utc)
        items = []
        for obj in data:
            title = obj.get("title")
            summary = obj.get("summary") or obj.get("content")
            items.append(RawItem(
                source_id=source.id,
                external_id=obj.get("id") or obj.get("guid"),
                url=obj.get("url") or obj.get("link"),
                title=title,
                raw_payload=obj,
                normalized_content=summary,
                content_hash=content_hash(title, summary),
                collected_at=now,
            ))
        return items
