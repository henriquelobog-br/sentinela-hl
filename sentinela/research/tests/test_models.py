from __future__ import annotations

import ast
from pathlib import Path

from sentinela.research.models import (
    AuthorSnapshot,
    CitationDecision,
    TopicAssignment,
    WorkComparison,
    bibliographic_metadata_hash,
    citation_decision,
    compare_works,
)
from sentinela.research.tests.conftest import make_work

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_IMPORTS = {
    "sentinela.core.models",
    "sentinela.persistence.canonical_store",
    "sentinela.persistence.event_store",
    "sentinela.cli.generate_real_signals",
    "sentinela.canonical_provenance.ownership",
    "sentinela.real_signals",
}


def test_first_observation_citation_decision():
    assert citation_decision(4, None, previous_observed=False) == CitationDecision.FIRST_OBSERVATION


def test_same_cited_by_count_is_unchanged():
    assert citation_decision(4, 4, previous_observed=True) == CitationDecision.UNCHANGED


def test_different_cited_by_count_is_changed():
    assert citation_decision(9, 4, previous_observed=True) == CitationDecision.CHANGED


def test_missing_current_count_is_missing_not_zero():
    assert citation_decision(None, 4, previous_observed=True) == CitationDecision.MISSING
    assert citation_decision(None, None, previous_observed=False) == CitationDecision.MISSING


def test_same_w_same_hash_same_citation_is_unchanged():
    current = make_work()
    previous = make_work()
    assert compare_works(current, previous) == WorkComparison.SAME_WORK_UNCHANGED


def test_same_w_hash_changed_is_metadata_changed():
    previous = make_work()
    current = make_work(title="Updated title")
    assert current.source_work_id == previous.source_work_id
    assert current.bibliographic_metadata_hash != previous.bibliographic_metadata_hash
    assert compare_works(current, previous) == WorkComparison.SAME_WORK_METADATA_CHANGED


def test_same_w_hash_same_citation_changed():
    previous = make_work(cited_by_count=4)
    current = make_work(cited_by_count=9)
    assert current.bibliographic_metadata_hash == previous.bibliographic_metadata_hash
    assert compare_works(current, previous) == WorkComparison.SAME_WORK_CITATION_CHANGED


def test_different_w_same_doi_is_identity_conflict():
    previous = make_work(source_work_id="W111")
    current = make_work(source_work_id="W222")
    assert current.doi == previous.doi
    assert compare_works(current, previous) == WorkComparison.IDENTITY_CONFLICT


def test_different_w_different_doi_are_distinct():
    previous = make_work(source_work_id="W111", doi="10.1000/aaa")
    current = make_work(source_work_id="W222", doi="10.1000/bbb")
    assert compare_works(current, previous) == WorkComparison.DISTINCT_WORKS


def test_different_w_both_doi_null_are_distinct():
    previous = make_work(source_work_id="W111", doi=None)
    current = make_work(source_work_id="W222", doi=None)
    assert compare_works(current, previous) == WorkComparison.DISTINCT_WORKS


def test_work_type_change_does_not_change_identity():
    previous = make_work(work_type="article")
    current = make_work(work_type="preprint")
    assert current.source_work_id == previous.source_work_id
    assert current.bibliographic_metadata_hash != previous.bibliographic_metadata_hash
    assert compare_works(current, previous) == WorkComparison.SAME_WORK_METADATA_CHANGED


def test_hash_ignores_cited_by_count_and_source_updated_date():
    base = make_work(cited_by_count=1, source_updated_date="2024-01-01")
    mutated = make_work(cited_by_count=99, source_updated_date="2026-01-01")
    assert bibliographic_metadata_hash(base) == bibliographic_metadata_hash(mutated)


def test_hash_includes_title_doi_type_authors_topics_and_created_date():
    base = make_work()
    assert bibliographic_metadata_hash(make_work(title="Other")) != bibliographic_metadata_hash(base)
    assert bibliographic_metadata_hash(make_work(doi="10.1000/other")) != bibliographic_metadata_hash(base)
    assert bibliographic_metadata_hash(make_work(work_type="preprint")) != bibliographic_metadata_hash(base)
    assert bibliographic_metadata_hash(make_work(source_created_date="2018-01-01")) != bibliographic_metadata_hash(base)
    assert bibliographic_metadata_hash(make_work(authors=())) != bibliographic_metadata_hash(base)
    assert bibliographic_metadata_hash(make_work(topics=())) != bibliographic_metadata_hash(base)


def test_authors_are_hashed_in_source_order_not_alphabetical():
    first = make_work(
        authors=(
            AuthorSnapshot(position=1, display_name="Zed"),
            AuthorSnapshot(position=2, display_name="Ann"),
        )
    )
    second = make_work(
        authors=(
            AuthorSnapshot(position=1, display_name="Ann"),
            AuthorSnapshot(position=2, display_name="Zed"),
        )
    )
    assert bibliographic_metadata_hash(first) != bibliographic_metadata_hash(second)


def test_topics_are_hashed_in_rank_then_id_order():
    first = make_work(
        topics=(
            TopicAssignment(external_topic_id="T2", external_topic_name="B", topic_rank=2, is_primary=False),
            TopicAssignment(external_topic_id="T1", external_topic_name="A", topic_rank=1, is_primary=True),
        )
    )
    second = make_work(
        topics=(
            TopicAssignment(external_topic_id="T1", external_topic_name="A", topic_rank=1, is_primary=True),
            TopicAssignment(external_topic_id="T2", external_topic_name="B", topic_rank=2, is_primary=False),
        )
    )
    assert bibliographic_metadata_hash(first) == bibliographic_metadata_hash(second)


def test_research_package_file_allowlist():
    files = sorted(
        path.relative_to(RESEARCH_ROOT).as_posix()
        for path in RESEARCH_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    assert files == [
        "__init__.py",
        "identity.py",
        "models.py",
        "openalex.py",
        "openalex_http.py",
        "persistence.py",
        "relevance.py",
        "tests/__init__.py",
        "tests/conftest.py",
        "tests/test_identity.py",
        "tests/test_models.py",
        "tests/test_openalex.py",
        "tests/test_openalex_http.py",
        "tests/test_persistence.py",
        "tests/test_relevance.py",
    ]


def test_research_package_does_not_reuse_event_signal_or_provenance_modules():
    for path in RESEARCH_ROOT.rglob("*.py"):
        if path.parent.name == "tests" or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] if False else alias.name for alias in node.names)
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        assert imported.isdisjoint(FORBIDDEN_IMPORTS), path
        source = path.read_text(encoding="utf-8")
        assert "EventStore" not in source
        assert "generate_real_signals" not in source
        assert "class Event" not in source
