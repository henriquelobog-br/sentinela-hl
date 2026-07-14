"""
Sentinela HL — leitura de eventos para o boletim (Documento 112.6A).

Responsabilidade ÚNICA: buscar eventos do banco. Nenhum agrupamento, nenhuma
ordenação de boletim, nenhuma lógica de produto. Só leitura.

Consumidor da Knowledge Base — NUNCA produtor. Este módulo não escreve em
knowledge.events (nem em nenhuma outra tabela).

psycopg direto, queries parametrizadas, sem ORM.
"""

from __future__ import annotations

from typing import Optional

import psycopg
from psycopg.rows import dict_row

from sentinela.core.models import Event

# Eventos elegíveis: validated/escalated e review_decision != rejected.
_ELIGIBLE_SQL = """
select id, primary_claim_id, title, summary, epistemic_status, confidence_score,
       category, country, scientific_area, entities, keywords, evidence,
       occurred_at, pipeline_status, requires_human_review, review_decision,
       validated_by, validated_at
  from knowledge.events
 where pipeline_status = any(%(statuses)s)
   and review_decision <> 'rejected'
 order by created_at desc
 limit %(limit)s
"""


class PostgresEventReader:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def fetch_eligible_events(self, *, limit: int = 500,
                              statuses: Optional[list[str]] = None) -> list[Event]:
        """Lê eventos elegíveis e devolve models Event (contrato do core)."""
        params = {
            "statuses": statuses or ["validated", "escalated"],
            "limit": limit,
        }
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_ELIGIBLE_SQL, params)
            rows = cur.fetchall()
        return [Event.model_validate(_coerce(r)) for r in rows]


def _coerce(row: dict) -> dict:
    """psycopg devolve numeric como Decimal e text[] como list — normaliza para
    o que o Pydantic espera. Nada além de coerção de tipo."""
    out = dict(row)
    if out.get("confidence_score") is not None:
        out["confidence_score"] = float(out["confidence_score"])
    out["keywords"] = list(out.get("keywords") or [])
    out["entities"] = out.get("entities") or []
    out["evidence"] = out.get("evidence") or []
    return out
