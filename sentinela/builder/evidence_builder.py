"""
Sentinela HL — Evidence Builder (Documento 112.2C Rev 2).

Antes chamado Claim Builder. Agora, além de montar o FilterAgentInput, enriquece
com sinais objetivos de evidência (observação vs estudo). Continua 100%
determinístico, sem LLM.

SEGURANÇA: confirmed_fact só com porta tripla (agência oficial + observação +
sem sinal de estudo). Default é hypothesis. O rótulo permanece provisório — o
Agente 113 audita e o humano confirma na curadoria.
"""

from __future__ import annotations

from uuid import uuid4

from sentinela.builder import signals
from sentinela.core.contract import CaseContext, FilterAgentInput, SourceRef
from sentinela.core.models import Claim, EpistemicStatus, RawItem


def _excerpt(raw_item: RawItem) -> str:
    if raw_item.normalized_content:
        return raw_item.normalized_content
    payload = raw_item.raw_payload or {}
    return payload.get("summary") or payload.get("content") or raw_item.title or ""


class EvidenceBuilder:
    scope = "science_research"

    def build(self, raw_item: RawItem) -> FilterAgentInput:
        excerpt = _excerpt(raw_item)
        text = f"{raw_item.title or ''} {excerpt}"

        # sinais de evidência (Rev 2)
        epistemic, confidence, reliability, ev_notes = signals.derive_epistemics(raw_item.url, text)
        category = signals.derive_category(text)
        keywords = signals.extract_keywords(text)
        statement = signals.statement_from(raw_item.title, excerpt)

        claim = Claim(
            raw_item_id=raw_item.id or uuid4(),
            statement=statement,
            epistemic_status=EpistemicStatus(epistemic),   # confirmed_fact ou hypothesis
            confidence_score=confidence,
            source_reliability=reliability,
            category=category,
            keywords=keywords,
        )
        src = SourceRef(
            excerpt=excerpt,
            url=raw_item.url,
            title=raw_item.title,
            reliability=reliability,
            published_at=raw_item.published_at,
        )
        ctx = CaseContext(
            case_id=raw_item.external_id or (raw_item.content_hash or str(uuid4()))[:24],
            scope=self.scope,
            notes=f"signals: {ev_notes} | category={category} keywords={len(keywords)}",
        )
        return FilterAgentInput(claim=claim, source=src, context=ctx)
