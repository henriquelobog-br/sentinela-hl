from __future__ import annotations

import re
from typing import Any

from sentinela.research.identity import (
    OPENALEX_SOURCE,
    DoiError,
    OpenAlexIdError,
    normalize_doi,
    normalize_openalex_work_id,
)
from sentinela.research.models import (
    AuthorSnapshot,
    NormalizedResearchWork,
    TopicAssignment,
    bibliographic_metadata_hash,
    is_v1_work_type,
    raw_payload_hash,
)


class ResearchParseError(ValueError):
    pass


_AUTHOR_ID_PREFIXES = ("https://openalex.org/", "http://openalex.org/")
_TOPIC_ID = re.compile(r"^T\d+$")
_ORCID = re.compile(r"^https://orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", re.I)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _compact_openalex_id(value: object, prefix: str) -> str | None:
    text = _text(value)
    if text is None:
        return None
    lowered = text.lower()
    for url in _AUTHOR_ID_PREFIXES:
        if lowered.startswith(url):
            text = text[len(url) :]
            break
    text = text.strip().split("?", 1)[0].rstrip("/")
    if text.startswith(prefix) and text[1:].isdigit():
        return text
    return None


def _normalize_topic_id(value: object) -> str | None:
    compact = _compact_openalex_id(value, "T")
    if compact is None:
        return None
    if not _TOPIC_ID.match(compact):
        return None
    return compact


def _orcid(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    lowered = text.lower()
    if "orcid.org/" in lowered:
        suffix = text.split("orcid.org/", 1)[1].strip().rstrip("/")
        text = f"https://orcid.org/{suffix}"
    if not _ORCID.match(text):
        return None
    return "https://orcid.org/" + text.split("orcid.org/", 1)[1]


def _nonneg_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        if value < 0:
            raise ResearchParseError("cited_by_count must be non-negative")
        return value
    if isinstance(value, float) and value.is_integer():
        number = int(value)
        if number < 0:
            raise ResearchParseError("cited_by_count must be non-negative")
        return number
    return None


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _year(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 1000 <= value <= 9999:
        return value
    return None


def _parse_authors(payload: dict[str, Any]) -> tuple[AuthorSnapshot, ...]:
    authorships = payload.get("authorships")
    if not isinstance(authorships, list):
        return ()
    authors: list[AuthorSnapshot] = []
    for index, item in enumerate(authorships, start=1):
        if not isinstance(item, dict):
            continue
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        display = _text(author.get("display_name")) or _text(item.get("raw_author_name"))
        if not display:
            continue
        authors.append(
            AuthorSnapshot(
                position=index,
                display_name=display,
                openalex_author_id=_compact_openalex_id(author.get("id"), "A"),
                orcid=_orcid(author.get("orcid")),
            )
        )
    return tuple(authors)


def _parse_topics(payload: dict[str, Any]) -> tuple[TopicAssignment, ...]:
    primary = payload.get("primary_topic") if isinstance(payload.get("primary_topic"), dict) else {}
    primary_id = _normalize_topic_id(primary.get("id"))
    raw_topics = payload.get("topics")
    items: list[dict[str, Any]] = []
    if isinstance(raw_topics, list):
        items.extend(item for item in raw_topics if isinstance(item, dict))
    elif primary_id:
        items.append(primary)
    seen: set[str] = set()
    topics: list[TopicAssignment] = []
    ranked = sorted(
        items,
        key=lambda item: (
            0 if _normalize_topic_id(item.get("id")) == primary_id else 1,
            -(item.get("score") or 0),
            _normalize_topic_id(item.get("id")) or "",
        ),
    )
    rank = 1
    for item in ranked:
        topic_id = _normalize_topic_id(item.get("id"))
        name = _text(item.get("display_name"))
        if not topic_id or not name or topic_id in seen:
            continue
        seen.add(topic_id)
        score = item.get("score")
        topics.append(
            TopicAssignment(
                external_topic_id=topic_id,
                external_topic_name=name,
                topic_rank=rank,
                topic_score=float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
                is_primary=topic_id == primary_id,
            )
        )
        rank += 1
    if primary_id and primary_id not in seen:
        name = _text(primary.get("display_name"))
        if name:
            topics.insert(
                0,
                TopicAssignment(
                    external_topic_id=primary_id,
                    external_topic_name=name,
                    topic_rank=1,
                    topic_score=None,
                    is_primary=True,
                ),
            )
            for offset, topic in enumerate(topics[1:], start=2):
                topics[offset - 1] = topic.model_copy(update={"topic_rank": offset})
    return tuple(topics)


def _location_source(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    location = payload.get("primary_location")
    if not isinstance(location, dict):
        return None, None
    source = location.get("source")
    if not isinstance(source, dict):
        return None, None
    return _compact_openalex_id(source.get("id"), "S"), _text(source.get("display_name"))


def parse_openalex_work(payload: object) -> NormalizedResearchWork:
    if not isinstance(payload, dict):
        raise ResearchParseError("OpenAlex payload must be an object")
    try:
        source_work_id = normalize_openalex_work_id(payload.get("id"))
    except OpenAlexIdError as exc:
        raise ResearchParseError(str(exc)) from exc
    title = _text(payload.get("title")) or _text((payload.get("display_name")))
    if not title:
        raise ResearchParseError("title is empty")
    work_type = _text(payload.get("type"))
    if not work_type:
        raise ResearchParseError("work type is missing")
    if not is_v1_work_type(work_type):
        raise ResearchParseError("work type is not V1-eligible")
    try:
        doi = normalize_doi(payload.get("doi"))
    except DoiError as exc:
        raise ResearchParseError(str(exc)) from exc
    oa = payload.get("open_access") if isinstance(payload.get("open_access"), dict) else {}
    source_id, source_name = _location_source(payload)
    citation = _nonneg_int(payload.get("cited_by_count"))
    work = NormalizedResearchWork(
        source=OPENALEX_SOURCE,
        source_work_id=source_work_id,
        doi=doi,
        title=title,
        work_type=work_type,
        publication_date=_text(payload.get("publication_date")),
        publication_year=_year(payload.get("publication_year")),
        language=_text(payload.get("language")),
        primary_source_id=source_id,
        primary_source_name=source_name,
        is_open_access=_bool(oa.get("is_oa")),
        oa_status=_text(oa.get("oa_status")),
        source_created_date=_text(payload.get("created_date")),
        source_updated_date=_text(payload.get("updated_date")),
        authors=_parse_authors(payload),
        topics=_parse_topics(payload),
        cited_by_count=citation,
        raw_payload_hash=raw_payload_hash(payload),
        bibliographic_metadata_hash="",
    )
    return work.model_copy(update={"bibliographic_metadata_hash": bibliographic_metadata_hash(work)})
