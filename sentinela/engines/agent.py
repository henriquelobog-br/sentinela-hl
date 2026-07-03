"""
Sentinela HL — orquestração do agente (Documento 113.5).

Une FilterEngine (avaliação) + DecisionEngine (política) num FilterReport,
gera um run_id para correlação e mapeia exceções para os erros do 112A.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import ValidationError

from sentinela.clients.base import LLMClient, LLMError, LLMTimeout
from sentinela.core.contract import (
    FilterAgentError, FilterAgentInput, FilterAgentOutput, FilterErrorCode,
)
from sentinela.core.models import FilterReport
from sentinela.engines.decision import DecisionEngine
from sentinela.engines.filter_engine import FilterEngine, FilterParseError
from sentinela.filters.prompt import DEFAULT_PROMPT_VERSION


def _err(code: FilterErrorCode, message: str, run_id: str) -> FilterAgentOutput:
    return FilterAgentOutput(ok=False, error=FilterAgentError(error=code, message=message), run_id=run_id)


def evaluate(inp: FilterAgentInput, llm: LLMClient, *,
             prompt_version: str = DEFAULT_PROMPT_VERSION) -> FilterAgentOutput:
    run_id = str(uuid4())
    if not inp.source.excerpt.strip():
        return _err(FilterErrorCode.MISSING_SOURCE, "source.excerpt está vazio", run_id)
    try:
        classifications = FilterEngine(llm, prompt_version=prompt_version).run(inp)
    except LLMTimeout as e:
        return _err(FilterErrorCode.LLM_TIMEOUT, str(e), run_id)
    except LLMError as e:
        return _err(FilterErrorCode.LLM_ERROR, str(e), run_id)
    except FilterParseError as e:
        return _err(FilterErrorCode.INVALID_JSON, str(e), run_id)
    except (ValueError, ValidationError) as e:
        return _err(FilterErrorCode.INVALID_ENUM, str(e), run_id)

    decision, review = DecisionEngine.decide(classifications)
    report = FilterReport(claim_id=inp.claim.id, classifications=classifications,
                          decision=decision, requires_human_review=review)
    return FilterAgentOutput(ok=True, report=report, run_id=run_id)
