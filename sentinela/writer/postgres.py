"""
Sentinela HL — persistência PostgreSQL/Supabase (Documento 112.5).

psycopg direto, sem ORM. Queries parametrizadas. Uma transação por item, com
rollback automático em qualquer falha.

NENHUMA regra científica mora aqui. O writer não decide nada — ele traduz o que
o pipeline já decidiu (DecisionEngine) em linhas. O mapeamento decisão →
pipeline_status é tabela, não lógica.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sentinela.core.contract import FilterAgentInput, FilterAgentOutput
from sentinela.core.models import RawItem, Source

# decisão do DecisionEngine → estado persistido. Tabela, não regra.
_DECISION_MAP: dict[str, dict[str, Any]] = {
    "pass":     {"pipeline_status": "validated", "creates_event": True,  "requires_human_review": False},
    "escalate": {"pipeline_status": "escalated", "creates_event": True,  "requires_human_review": True},
    "reject":   {"pipeline_status": "rejected",  "creates_event": False, "requires_human_review": False},
}


class PostgresWriter:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # ------------------------------------------------------------- sources
    def ensure_source(self, source: Source) -> UUID:
        """Localiza a fonte por (name, kind) ou cria. Idempotente."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id from raw.sources where name = %s and kind = %s limit 1",
                (source.name, source.kind.value),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                """insert into raw.sources (name, kind, url, reliability, config, active)
                   values (%s, %s, %s, %s, %s, %s) returning id""",
                (source.name, source.kind.value, source.url,
                 source.reliability.value, Jsonb(source.config or {}), source.active),
            )
            return cur.fetchone()["id"]

    # ---------------------------------------------------------- fetch_runs
    def start_fetch_run(self, source_id: UUID) -> UUID:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "insert into raw.fetch_runs (source_id, status) values (%s, 'running') returning id",
                (source_id,),
            )
            return cur.fetchone()["id"]

    def finish_fetch_run(self, fetch_run_id: UUID, *, status: str = "success",
                         items_found: int = 0, items_new: int = 0,
                         items_duplicate: int = 0, error: Optional[str] = None,
                         log: Optional[dict] = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """update raw.fetch_runs
                      set status = %s, finished_at = now(), items_found = %s,
                          items_new = %s, items_duplicate = %s, error = %s, log = %s
                    where id = %s""",
                (status, items_found, items_new, items_duplicate, error,
                 Jsonb(log or {}), fetch_run_id),
            )

    # --------------------------------------------------------------- items
    def find_duplicate(self, source_id: UUID, item: RawItem) -> Optional[UUID]:
        """Dedup: (source_id, external_id) quando houver; senão content_hash."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            if item.external_id:
                cur.execute(
                    "select id from raw.items where source_id = %s and external_id = %s limit 1",
                    (source_id, item.external_id),
                )
                row = cur.fetchone()
                if row:
                    return row["id"]
            if item.content_hash:
                cur.execute(
                    "select id from raw.items where source_id = %s and content_hash = %s limit 1",
                    (source_id, item.content_hash),
                )
                row = cur.fetchone()
                if row:
                    return row["id"]
        return None

    def persist_item(self, item: RawItem, source_id: UUID,
                     fetch_run_id: Optional[UUID] = None) -> tuple[UUID, bool]:
        """Insere raw.items. Retorna (item_id, is_new). Se duplicado, devolve o
        id existente sem inserir."""
        dup = self.find_duplicate(source_id, item)
        if dup:
            return dup, False
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """insert into raw.items
                     (source_id, fetch_run_id, external_id, url, title, raw_payload,
                      normalized_content, content_hash, published_at, collected_at,
                      pipeline_status)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                (source_id, fetch_run_id, item.external_id, item.url, item.title,
                 Jsonb(item.raw_payload or {}), item.normalized_content,
                 item.content_hash, item.published_at, item.collected_at,
                 item.pipeline_status.value),
            )
            return cur.fetchone()["id"], True

    # -------------------------------------------------------------- result
    def persist_result(self, raw_item_id: UUID, filter_input: FilterAgentInput,
                       filter_output: FilterAgentOutput) -> dict[str, Any]:
        """Persiste claim + classifications (+ event quando cabível).
        Espera FilterAgentOutput.ok == True."""
        report = filter_output.report
        decision = report.decision
        rule = _DECISION_MAP[decision]
        claim = filter_input.claim
        run_id = filter_output.run_id

        with self.conn.cursor(row_factory=dict_row) as cur:
            # claim
            cur.execute(
                """insert into knowledge.claims
                     (raw_item_id, statement, epistemic_status, confidence_score,
                      source_reliability, category, country, scientific_area,
                      entities, keywords, pipeline_status, requires_human_review, review_reason)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                (raw_item_id, claim.statement,
                 claim.epistemic_status.value if claim.epistemic_status else None,
                 claim.confidence_score,
                 claim.source_reliability.value, claim.category, claim.country,
                 claim.scientific_area, Jsonb(claim.entities), claim.keywords,
                 rule["pipeline_status"], rule["requires_human_review"],
                 filter_input.context.notes),
            )
            claim_id = cur.fetchone()["id"]

            # classifications (upsert por claim_id + filter). run_id vai em detail.
            for c in report.classifications:
                detail = dict(c.detail or {})
                if run_id:
                    detail["run_id"] = run_id
                cur.execute(
                    """insert into knowledge.classifications
                         (claim_id, filter, result, rationale, detail, automated, model, prompt_version)
                       values (%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict (claim_id, filter) do update set
                         result = excluded.result, rationale = excluded.rationale,
                         detail = excluded.detail, model = excluded.model,
                         prompt_version = excluded.prompt_version""",
                    (claim_id, c.filter.value, c.result.value, c.rationale,
                     Jsonb(detail), c.automated, c.model, c.prompt_version),
                )

            # atualiza o item bruto com o estado final
            cur.execute("update raw.items set pipeline_status = %s where id = %s",
                        (rule["pipeline_status"], raw_item_id))

            event_id = None
            if rule["creates_event"]:
                evidence = [{
                    "url": filter_input.source.url,
                    "title": filter_input.source.title,
                    "excerpt": filter_input.source.excerpt,
                }]
                cur.execute(
                    """insert into knowledge.events
                         (primary_claim_id, title, summary, epistemic_status, confidence_score,
                          category, country, scientific_area, entities, keywords, evidence,
                          occurred_at, pipeline_status, requires_human_review, review_decision)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending') returning id""",
                    (claim_id, claim.statement, filter_input.source.excerpt,
                     claim.epistemic_status.value if claim.epistemic_status else "hypothesis",
                     claim.confidence_score, claim.category, claim.country,
                     claim.scientific_area, Jsonb(claim.entities), claim.keywords,
                     Jsonb(evidence), filter_input.source.published_at,
                     rule["pipeline_status"], rule["requires_human_review"]),
                )
                event_id = cur.fetchone()["id"]

        return {"claim_id": claim_id, "event_id": event_id,
                "decision": decision, "pipeline_status": rule["pipeline_status"]}


def persist_pipeline_result(conn: psycopg.Connection, raw_item: RawItem,
                            filter_input: FilterAgentInput,
                            filter_output: FilterAgentOutput,
                            source: Source,
                            fetch_run_id: Optional[UUID] = None) -> dict[str, Any]:
    """Alto nível: tudo em UMA transação por item. Rollback automático em falha."""
    with conn.transaction():                      # commit no fim; rollback em exceção
        w = PostgresWriter(conn)
        source_id = w.ensure_source(source)
        item_id, is_new = w.persist_item(raw_item, source_id, fetch_run_id)
        if not filter_output.ok:
            # agente falhou: item fica registrado no bruto, nada entra no conhecimento
            return {"raw_item_id": item_id, "is_new": is_new, "claim_id": None,
                    "event_id": None, "decision": None, "error": filter_output.error.error.value}
        res = w.persist_result(item_id, filter_input, filter_output)
        res.update({"raw_item_id": item_id, "is_new": is_new})
        return res
