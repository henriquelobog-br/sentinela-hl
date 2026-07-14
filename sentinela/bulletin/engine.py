"""
Sentinela HL — Bulletin Engine (Documento 112.6A).

Recebe eventos → organiza → produz BulletinModel. Determinístico: sem banco,
sem rede, sem LLM, sem apresentação.

O engine NÃO decide o que é publicável. Ele preserva `requires_review` para que
a curadoria decida depois — conhecimento validado != decisão editorial.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from sentinela.bulletin.models import BulletinItem, BulletinModel, BulletinSection
from sentinela.core.models import Event

_OTHERS = "outros"

# ---------------------------------------------------------------- ordenação
# requires_human_review ASC · confidence DESC NULLS LAST ·
# occurred_at DESC NULLS LAST · created_at DESC
_MIN_DT = datetime.min.replace(tzinfo=timezone.utc)


def _as_aware(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return _MIN_DT
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _sort_key(e: Event):
    return (
        e.requires_human_review,                     # False (0) antes de True (1)
        -(e.confidence_score if e.confidence_score is not None else -1.0),  # DESC, nulls last
        -_as_aware(e.occurred_at).timestamp(),       # DESC, nulls last
        -_as_aware(e.validated_at).timestamp(),      # proxy de created_at, DESC
    )


def sort_events(events: list[Event]) -> list[Event]:
    return sorted(events, key=_sort_key)


# ------------------------------------------------------------- deduplicação
def _normalize_title(title: str) -> str:
    """minúsculas, sem acento, sem pontuação, espaços colapsados."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _dedup_key(e: Event):
    """primary_claim_id quando houver; senão (título normalizado, categoria)."""
    if e.primary_claim_id:
        return ("claim", str(e.primary_claim_id))
    return ("title", _normalize_title(e.title), (e.category or "").lower())


def dedup_events(events: list[Event]) -> list[tuple[Event, int]]:
    """Colapsa duplicatas DENTRO do boletim. Nunca apaga nem atualiza o banco.
    Devolve (evento_representante, source_count)."""
    groups: dict[tuple, list[Event]] = {}
    order: list[tuple] = []
    for e in events:
        k = _dedup_key(e)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(e)
    # o representante é o primeiro (a lista já vem ordenada = o "melhor")
    return [(groups[k][0], len(groups[k])) for k in order]


# -------------------------------------------------------------- agrupamento
def _group_key(e: Event) -> tuple[Optional[str], str]:
    """scientific_area → category → 'outros'. Retorna (area, título da seção)."""
    if e.scientific_area and e.scientific_area.strip():
        return e.scientific_area, e.scientific_area
    if e.category and e.category.strip():
        return None, e.category
    return None, _OTHERS


# ------------------------------------------------------------------- engine
def _to_item(event: Event, source_count: int) -> BulletinItem:
    return BulletinItem(
        event_id=event.id,
        title=event.title,
        summary=event.summary,
        epistemic_status=event.epistemic_status,
        confidence=event.confidence_score,
        category=event.category,
        scientific_area=event.scientific_area,
        keywords=list(event.keywords),
        evidence=list(event.evidence),
        source_count=source_count,
        requires_review=event.requires_human_review,   # preservado p/ a curadoria
    )


class BulletinEngine:
    """Eventos → BulletinModel. Sem acesso a banco."""

    def build(self, events: list[Event]) -> BulletinModel:
        ordered = sort_events(events)
        deduped = dedup_events(ordered)

        sections: dict[str, BulletinSection] = {}
        section_order: list[str] = []
        for event, count in deduped:
            area, title = _group_key(event)
            if title not in sections:
                sections[title] = BulletinSection(title=title, scientific_area=area, items=[])
                section_order.append(title)
            sections[title].items.append(_to_item(event, count))

        ordered_sections = [sections[t] for t in section_order]
        total = sum(len(s.items) for s in ordered_sections)
        return BulletinModel(total_items=total, sections=ordered_sections)
