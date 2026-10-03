from __future__ import annotations

from sentinela.research.models import TopicAssignment
from sentinela.research.openalex import parse_openalex_work
from sentinela.research.relevance import TopicMappingTable, evaluate_relevance
from sentinela.research.tests.conftest import article_payload, make_work, mapping_table


def test_mapped_primary_topic_is_relevant():
    work = make_work(
        topics=(
            TopicAssignment(
                external_topic_id="T10178",
                external_topic_name="Scientometrics and bibliometrics",
                topic_rank=1,
                is_primary=True,
            ),
        )
    )
    result = evaluate_relevance(work, mapping_table(), "v1")
    assert result.relevant is True
    assert result.primary_scientific_area == "information_science"
    assert result.mapped_topic_ids == ("T10178",)


def test_mapped_non_primary_only_is_relevant():
    work = make_work(
        topics=(
            TopicAssignment(
                external_topic_id="T00001",
                external_topic_name="Unmapped",
                topic_rank=1,
                is_primary=True,
            ),
            TopicAssignment(
                external_topic_id="T11922",
                external_topic_name="Seismology and earthquake hazards",
                topic_rank=2,
                is_primary=False,
            ),
        )
    )
    result = evaluate_relevance(work, mapping_table(), "v1")
    assert result.relevant is True
    assert result.primary_scientific_area == "seismology"
    assert result.scientific_areas == ("seismology",)


def test_unmapped_topics_are_not_relevant_and_not_discarded():
    work = make_work(
        topics=(
            TopicAssignment(
                external_topic_id="T88888",
                external_topic_name="Unmapped topic",
                topic_rank=1,
                is_primary=True,
            ),
        )
    )
    result = evaluate_relevance(work, mapping_table(), "v1")
    assert result.relevant is False
    assert work.topics[0].external_topic_id == "T88888"
    assert result.mapped_topic_ids == ()


def test_disabled_mapping_is_ignored():
    work = make_work(
        topics=(
            TopicAssignment(
                external_topic_id="T19999",
                external_topic_name="Disabled volcano topic",
                topic_rank=1,
                is_primary=True,
            ),
        )
    )
    result = evaluate_relevance(work, mapping_table(), "v1")
    assert result.relevant is False


def test_mapping_version_mismatch_is_ignored():
    work = parse_openalex_work(article_payload())
    result = evaluate_relevance(work, mapping_table(), "v9")
    assert result.relevant is False
    assert result.mapping_version == "v9"


def test_multiple_mapped_topics_keep_areas_and_primary():
    work = parse_openalex_work(article_payload())
    result = evaluate_relevance(work, mapping_table(), "v1")
    assert result.relevant is True
    assert result.scientific_areas == ("information_science", "seismology")
    assert result.primary_scientific_area == "information_science"
    assert result.mapped_topic_ids == ("T10178", "T11922")


def test_empty_topics_are_not_relevant():
    work = make_work(topics=())
    result = evaluate_relevance(work, mapping_table(), "v1")
    assert result.relevant is False
    assert result.primary_scientific_area is None


def test_relevance_has_no_keyword_citation_journal_language_oa_or_geo_fallback():
    table = TopicMappingTable(mapping_version="v1", mappings=())
    work = make_work(
        title="volcano earthquake brazil amazon climate",
        language="pt",
        oa_status="gold",
        is_open_access=True,
        cited_by_count=999,
        primary_source_name="Nature",
        topics=(),
    )
    result = evaluate_relevance(work, table, "v1")
    assert result.relevant is False
    assert result.scientific_areas == ()
