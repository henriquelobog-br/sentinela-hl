"""Collector RSS — usa feedparser. Aceita URL (rede) ou conteúdo XML já
carregado (para teste offline). Produz RawItem, sem rótulo."""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from sentinela.collector.base import content_hash
from sentinela.core.models import RawItem, Source


def _published(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


class RssCollector:
    kind = "rss"

    def collect(self, source: Source, *, raw_xml: str | None = None) -> list[RawItem]:
        # raw_xml permite testar o parsing sem rede; em produção usa source.url
        feed = feedparser.parse(raw_xml if raw_xml is not None else source.url)
        now = datetime.now(timezone.utc)
        items = []
        for e in feed.entries:
            title = getattr(e, "title", None)
            summary = getattr(e, "summary", None) or getattr(e, "description", None)
            link = getattr(e, "link", None)
            items.append(RawItem(
                source_id=source.id,
                external_id=getattr(e, "id", None) or link,
                url=link,
                title=title,
                raw_payload={"summary": summary, "link": link},
                normalized_content=summary,
                content_hash=content_hash(title, summary),
                published_at=_published(e),
                collected_at=now,
            ))
        return items
