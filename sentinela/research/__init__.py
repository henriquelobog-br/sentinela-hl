"""Pure V1 ResearchWork domain: OpenAlex identity, parse, relevance, hashing."""

from sentinela.research.identity import (
    OPENALEX_SOURCE,
    DoiError,
    OpenAlexIdError,
    normalize_doi,
    normalize_openalex_work_id,
)
from sentinela.research.models import (
    AuthorSnapshot,
    CitationDecision,
    NormalizedResearchWork,
    SourceAlias,
    TopicAssignment,
    WorkComparison,
    bibliographic_metadata_hash,
    citation_decision,
    compare_works,
    is_bibliographically_valid,
    is_v1_work_type,
    raw_payload_hash,
)
from sentinela.research.openalex import ResearchParseError, parse_openalex_work
from sentinela.research.relevance import (
    RelevanceResult,
    TopicMapping,
    TopicMappingTable,
    evaluate_relevance,
)

__all__ = [
    "AuthorSnapshot",
    "CitationDecision",
    "DoiError",
    "NormalizedResearchWork",
    "OPENALEX_SOURCE",
    "OpenAlexIdError",
    "RelevanceResult",
    "ResearchParseError",
    "SourceAlias",
    "TopicAssignment",
    "TopicMapping",
    "TopicMappingTable",
    "WorkComparison",
    "bibliographic_metadata_hash",
    "citation_decision",
    "compare_works",
    "evaluate_relevance",
    "is_bibliographically_valid",
    "is_v1_work_type",
    "normalize_doi",
    "normalize_openalex_work_id",
    "parse_openalex_work",
    "raw_payload_hash",
]
