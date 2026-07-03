from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sentinela.core.models import Claim, FilterReport, ReliabilityTier


class _Base(BaseModel):
   model_config = ConfigDict(extra="forbid")


class SourceRef(_Base):
   excerpt: str
   url: Optional[str] = None
   title: Optional[str] = None
   reliability: ReliabilityTier = ReliabilityTier.UNKNOWN
   published_at: Optional[datetime] = None


class CaseContext(_Base):
   case_id: str
   scope: str = "science_research"
   notes: Optional[str] = None


class FilterAgentInput(_Base):
   claim: Claim
   source: SourceRef
   context: CaseContext


class FilterErrorCode(str, Enum):
   MALFORMED_CLAIM = "malformed_claim"
   MISSING_SOURCE = "missing_source"
   INSUFFICIENT_EVIDENCE = "insufficient_evidence"
   LLM_TIMEOUT = "llm_timeout"
   LLM_ERROR = "llm_error"
   INVALID_JSON = "invalid_json"
   INVALID_ENUM = "invalid_enum"


class FilterAgentError(_Base):
   error: FilterErrorCode
   message: str
   detail: dict = Field(default_factory=dict)


class FilterAgentOutput(_Base):
   ok: bool
   report: Optional[FilterReport] = None
   error: Optional[FilterAgentError] = None
   run_id: Optional[str] = None