from __future__ import annotations

from enum import Enum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from sentinela.research.identity import OPENALEX_SOURCE


V1_WORK_TYPES = frozenset({"article", "preprint"})


class WorkComparison(str, Enum):
    SAME_WORK_UNCHANGED = "same_work_unchanged"
    SAME_WORK_METADATA_CHANGED = "same_work_metadata_changed"
    SAME_WORK_CITATION_CHANGED = "same_work_citation_changed"
    IDENTITY_CONFLICT = "identity_conflict"
    DISTINCT_WORKS = "distinct_works"


class CitationDecision(str, Enum):
    FIRST_OBSERVATION = "first_observation"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    MISSING = "missing"


class AuthorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int
    display_name: str
    openalex_author_id: str | None = None
    orcid: str | None = None


class TopicAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_topic_id: str
    external_topic_name: str
    topic_rank: int
    topic_score: float | None = None
    is_primary: bool = False


class NormalizedResearchWork(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = OPENALEX_SOURCE
    source_work_id: str
    doi: str | None = None
    title: str
    work_type: str
    publication_date: str | None = None
    publication_year: int | None = None
    language: str | None = None
    primary_source_id: str | None = None
    primary_source_name: str | None = None
    is_open_access: bool | None = None
    oa_status: str | None = None
    source_created_date: str | None = None
    source_updated_date: str | None = None
    authors: tuple[AuthorSnapshot, ...] = ()
    topics: tuple[TopicAssignment, ...] = ()
    cited_by_count: int | None = None
    raw_payload_hash: str
    bibliographic_metadata_hash: str

    @field_validator("cited_by_count")
    @classmethod
    def _citation_non_negative(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("cited_by_count must be non-negative")
        return value


class SourceAlias(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = OPENALEX_SOURCE
    alias_source_work_id: str
    canonical_source_work_id: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def raw_payload_hash(payload: Any) -> str:
    encoded = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bibliographic_metadata_payload(work: NormalizedResearchWork) -> dict[str, Any]:
    return {
        "authors": [
            {
                "display_name": author.display_name,
                "openalex_author_id": author.openalex_author_id,
                "orcid": author.orcid,
                "position": author.position,
            }
            for author in work.authors
        ],
        "doi": work.doi,
        "is_open_access": work.is_open_access,
        "language": work.language,
        "oa_status": work.oa_status,
        "primary_source_id": work.primary_source_id,
        "primary_source_name": work.primary_source_name,
        "publication_date": work.publication_date,
        "publication_year": work.publication_year,
        "source": work.source,
        "source_created_date": work.source_created_date,
        "source_work_id": work.source_work_id,
        "title": work.title,
        "topics": [
            {
                "external_topic_id": topic.external_topic_id,
                "external_topic_name": topic.external_topic_name,
                "is_primary": topic.is_primary,
                "topic_rank": topic.topic_rank,
                "topic_score": topic.topic_score,
            }
            for topic in sorted(work.topics, key=lambda item: (item.topic_rank, item.external_topic_id))
        ],
        "work_type": work.work_type,
    }


def bibliographic_metadata_hash(work: NormalizedResearchWork) -> str:
    encoded = _canonical_json(bibliographic_metadata_payload(work)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_v1_work_type(work_type: str) -> bool:
    return work_type in V1_WORK_TYPES


def is_bibliographically_valid(work: NormalizedResearchWork) -> bool:
    return bool(work.source_work_id and work.title.strip() and is_v1_work_type(work.work_type))


def citation_decision(
    current: int | None,
    previous: int | None,
    *,
    previous_observed: bool,
) -> CitationDecision:
    if current is None:
        return CitationDecision.MISSING
    if not previous_observed:
        return CitationDecision.FIRST_OBSERVATION
    if previous is None:
        return CitationDecision.FIRST_OBSERVATION
    if current == previous:
        return CitationDecision.UNCHANGED
    return CitationDecision.CHANGED


def compare_works(
    current: NormalizedResearchWork,
    previous: NormalizedResearchWork | None = None,
) -> WorkComparison:
    if previous is None:
        return WorkComparison.DISTINCT_WORKS
    if current.source != previous.source:
        return WorkComparison.DISTINCT_WORKS
    if current.source_work_id == previous.source_work_id:
        same_bib = current.bibliographic_metadata_hash == previous.bibliographic_metadata_hash
        if same_bib and current.cited_by_count == previous.cited_by_count:
            return WorkComparison.SAME_WORK_UNCHANGED
        if same_bib:
            return WorkComparison.SAME_WORK_CITATION_CHANGED
        return WorkComparison.SAME_WORK_METADATA_CHANGED
    if current.doi and previous.doi and current.doi == previous.doi:
        return WorkComparison.IDENTITY_CONFLICT
    return WorkComparison.DISTINCT_WORKS
