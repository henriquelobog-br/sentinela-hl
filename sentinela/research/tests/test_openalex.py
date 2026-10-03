from __future__ import annotations

import hashlib
import json

import pytest

from sentinela.research.models import bibliographic_metadata_hash, is_bibliographically_valid, raw_payload_hash
from sentinela.research.openalex import ResearchParseError, parse_openalex_work
from sentinela.research.tests.conftest import article_payload, preprint_payload


def test_complete_article_parses():
    work = parse_openalex_work(article_payload())
    assert work.source == "openalex"
    assert work.source_work_id == "W2741809807"
    assert work.doi == "10.7717/peerj.4375"
    assert work.title == "The state of OA"
    assert work.work_type == "article"
    assert work.cited_by_count == 12
    assert work.primary_source_id == "S1983995261"
    assert work.is_open_access is True
    assert is_bibliographically_valid(work)


def test_complete_preprint_is_accepted():
    work = parse_openalex_work(preprint_payload())
    assert work.work_type == "preprint"
    assert work.source_work_id == "W4381234567"
    assert is_bibliographically_valid(work)


@pytest.mark.parametrize("work_type", ["book", "dataset", "dissertation", "editorial", "letter", "other", None])
def test_non_v1_types_raise(work_type: str | None):
    payload = article_payload()
    if work_type is None:
        payload.pop("type")
    else:
        payload["type"] = work_type
    with pytest.raises(ResearchParseError):
        parse_openalex_work(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": None},
        {"id": "Wabc"},
        {"title": "", "display_name": ""},
        {"title": None, "display_name": None},
    ],
)
def test_missing_identity_or_title_raises(overrides: dict):
    payload = article_payload(**overrides)
    with pytest.raises(ResearchParseError):
        parse_openalex_work(payload)


def test_missing_doi_is_valid_none():
    payload = article_payload()
    payload["doi"] = None
    work = parse_openalex_work(payload)
    assert work.doi is None
    assert is_bibliographically_valid(work)


def test_invalid_payload_doi_raises():
    with pytest.raises(ResearchParseError):
        parse_openalex_work(article_payload(doi="not-a-doi"))


def test_authors_preserve_source_order_and_one_based_position():
    work = parse_openalex_work(article_payload())
    assert [author.display_name for author in work.authors] == ["Heather Piwowar", "Jason Priem"]
    assert [author.position for author in work.authors] == [1, 2]
    assert work.authors[0].openalex_author_id == "A5023888391"
    assert work.authors[0].orcid == "https://orcid.org/0000-0003-1613-5981"


def test_author_without_openalex_id_or_orcid_is_valid():
    payload = article_payload(
        authorships=[{"author": {"display_name": "Anonymous Reviewer"}, "raw_author_name": "Anonymous Reviewer"}]
    )
    work = parse_openalex_work(payload)
    assert len(work.authors) == 1
    assert work.authors[0].openalex_author_id is None
    assert work.authors[0].orcid is None
    assert work.authors[0].display_name == "Anonymous Reviewer"


def test_topics_persist_all_with_primary_and_rank():
    work = parse_openalex_work(article_payload())
    assert [topic.external_topic_id for topic in work.topics] == ["T10178", "T11922"]
    assert work.topics[0].is_primary is True
    assert work.topics[1].is_primary is False
    assert work.topics[0].topic_rank == 1
    assert work.topics[1].topic_rank == 2


def test_missing_topics_stay_empty():
    payload = article_payload()
    payload.pop("topics")
    payload.pop("primary_topic")
    work = parse_openalex_work(payload)
    assert work.topics == ()


def test_cited_by_count_integer_is_persisted():
    assert parse_openalex_work(article_payload(cited_by_count=42)).cited_by_count == 42


def test_missing_cited_by_count_is_none_not_zero():
    payload = article_payload()
    payload.pop("cited_by_count")
    work = parse_openalex_work(payload)
    assert work.cited_by_count is None


def test_source_updated_date_parsed_but_excluded_from_bibliographic_hash():
    work = parse_openalex_work(article_payload())
    mutated = parse_openalex_work(article_payload(updated_date="2025-12-01T00:00:00.000000"))
    assert work.source_updated_date != mutated.source_updated_date
    assert work.bibliographic_metadata_hash == mutated.bibliographic_metadata_hash
    assert work.bibliographic_metadata_hash == bibliographic_metadata_hash(work)


def test_raw_payload_hash_is_canonical_json_sha256():
    payload = article_payload()
    work = parse_openalex_work(payload)
    expected = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert work.raw_payload_hash == expected
    assert work.raw_payload_hash == raw_payload_hash(payload)


def test_bibliographic_hash_is_stable_for_equivalent_fields():
    first = parse_openalex_work(article_payload())
    second = parse_openalex_work(article_payload(updated_date="2099-01-01", counts_by_year=[{"year": 2020, "cited_by_count": 1}]))
    assert first.bibliographic_metadata_hash == second.bibliographic_metadata_hash
    assert first.raw_payload_hash != second.raw_payload_hash


def test_payload_extra_fields_are_ignored_for_identity():
    work = parse_openalex_work(article_payload(abstract_inverted_index={"the": [0]}, extra_flag=True))
    assert work.source_work_id == "W2741809807"


def test_malformed_nested_authorships_and_topics_are_skipped():
    payload = article_payload(
        authorships=["bad", {"author": {"display_name": "Valid Author"}}],
        topics=["bad", {"id": "https://openalex.org/T10178", "display_name": "Scientometrics and bibliometrics", "score": 0.9}],
    )
    work = parse_openalex_work(payload)
    assert [author.display_name for author in work.authors] == ["Valid Author"]
    assert [topic.external_topic_id for topic in work.topics] == ["T10178"]


def test_parser_has_no_network_client_attributes():
    from sentinela.research import openalex as module

    assert not hasattr(module, "httpx")
    assert "requests" not in dir(module)
    assert set(parse_openalex_work.__code__.co_names).isdisjoint({"urlopen", "Client", "httpx", "requests"})
