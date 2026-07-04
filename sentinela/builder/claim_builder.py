"""
Sentinela HL — Claim Builder (Documento 112.2C).

Adapta RawItem -> FilterAgentInput. NÃO classifica: aplica sinais mecânicos
(domínio, tier, keywords) e um rótulo provisório conservador (hypothesis).
Quem julga é o Agente 113. Sem LLM, sem rede, fora do caminho de custo.

Decisão consciente de V1: epistemic_status = hypothesis sempre. Isso deixa o
filtro 2 (overclaim) dormente no pipeline real — o agente atua sobretudo na
proveniência. É a escolha segura (subclama em vez de superclamar). Um
SmartClassifier opcional (Milestone 5/6) pode melhorar o chute sem tocar no resto.
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


class ClaimBuilder:
    scope = "science_research"

    def build(self, raw_item: RawItem) -> FilterAgentInput:
        excerpt = _excerpt(raw_item)
        text = f"{raw_item.title or ''} {excerpt}"

        reliability = signals.derive_reliability(raw_item.url)
        confidence = signals.confidence_for(reliability)
        category = signals.derive_category(text)
        keywords = signals.extract_keywords(text)
        statement = signals.statement_from(raw_item.title, excerpt)

        claim = Claim(
            raw_item_id=raw_item.id or uuid4(),
            statement=statement,
            epistemic_status=EpistemicStatus.HYPOTHESIS,   # sempre — provisório
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
        # sinais auditáveis registrados no contexto
        ctx = CaseContext(
            case_id=raw_item.external_id or (raw_item.content_hash or str(uuid4()))[:24],
            scope=self.scope,
            notes=f"signals: reliability={reliability.value} confidence={confidence} category={category} keywords={len(keywords)}",
        )
        return FilterAgentInput(claim=claim, source=src, context=ctx)
