from __future__ import annotations

from typing import Any

from sentinela.research.models import (
    AuthorSnapshot,
    NormalizedResearchWork,
    TopicAssignment,
    bibliographic_metadata_hash,
)
from sentinela.research.relevance import TopicMapping, TopicMappingTable


def article_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.7717/peerj.4375",
        "title": "The state of OA",
        "display_name": "The state of OA",
        "publication_year": 2018,
        "publication_date": "2018-02-13",
        "type": "article",
        "language": "en",
        "cited_by_count": 12,
        "created_date": "2017-08-01",
        "updated_date": "2024-01-15T12:00:00.000000",
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/A5023888391",
                    "display_name": "Heather Piwowar",
                    "orcid": "https://orcid.org/0000-0003-1613-5981",
                }
            },
            {
                "author": {
                    "id": "https://openalex.org/A5012345678",
                    "display_name": "Jason Priem",
                }
            },
        ],
        "primary_location": {
            "source": {
                "id": "https://openalex.org/S1983995261",
                "display_name": "PeerJ",
            }
        },
        "open_access": {"is_oa": True, "oa_status": "gold"},
        "primary_topic": {
            "id": "https://openalex.org/T10178",
            "display_name": "Scientometrics and bibliometrics",
            "score": 0.91,
        },
        "topics": [
            {
                "id": "https://openalex.org/T10178",
                "display_name": "Scientometrics and bibliometrics",
                "score": 0.91,
            },
            {
                "id": "https://openalex.org/T11922",
                "display_name": "Seismology and earthquake hazards",
                "score": 0.44,
            },
        ],
        "counts_by_year": [{"year": 2024, "cited_by_count": 2}],
    }
    payload.update(overrides)
    return payload


def preprint_payload(**overrides: Any) -> dict[str, Any]:
    payload = article_payload(
        id="https://openalex.org/W4381234567",
        doi="https://doi.org/10.1101/2023.01.01.522123",
        title="A volcanic unrest preprint",
        type="preprint",
        cited_by_count=3,
    )
    payload.update(overrides)
    return payload


def mapping_table() -> TopicMappingTable:
    return TopicMappingTable(
        mapping_version="v1",
        mappings=(
            TopicMapping(
                mapping_version="v1",
                external_topic_id="T10178",
                external_topic_name="Scientometrics and bibliometrics",
                scientific_area="information_science",
                enabled=True,
            ),
            TopicMapping(
                mapping_version="v1",
                external_topic_id="T11922",
                external_topic_name="Seismology and earthquake hazards",
                scientific_area="seismology",
                enabled=True,
            ),
            TopicMapping(
                mapping_version="v1",
                external_topic_id="T19999",
                external_topic_name="Disabled volcano topic",
                scientific_area="volcanology",
                enabled=False,
            ),
            TopicMapping(
                mapping_version="v0",
                external_topic_id="T10178",
                external_topic_name="Old mapping",
                scientific_area="legacy_area",
                enabled=True,
            ),
        ),
    )


def make_work(**overrides: Any) -> NormalizedResearchWork:
    data: dict[str, Any] = {
        "source_work_id": "W2741809807",
        "doi": "10.7717/peerj.4375",
        "title": "The state of OA",
        "work_type": "article",
        "publication_date": "2018-02-13",
        "publication_year": 2018,
        "language": "en",
        "primary_source_id": "S1983995261",
        "primary_source_name": "PeerJ",
        "is_open_access": True,
        "oa_status": "gold",
        "source_created_date": "2017-08-01",
        "source_updated_date": "2024-01-15T12:00:00.000000",
        "authors": (
            AuthorSnapshot(position=1, display_name="Heather Piwowar", openalex_author_id="A5023888391"),
            AuthorSnapshot(position=2, display_name="Jason Priem", openalex_author_id="A5012345678"),
        ),
        "topics": (
            TopicAssignment(
                external_topic_id="T10178",
                external_topic_name="Scientometrics and bibliometrics",
                topic_rank=1,
                topic_score=0.91,
                is_primary=True,
            ),
        ),
        "cited_by_count": 12,
        "raw_payload_hash": "0" * 64,
        "bibliographic_metadata_hash": "0" * 64,
    }
    data.update(overrides)
    work = NormalizedResearchWork(**data)
    return work.model_copy(update={"bibliographic_metadata_hash": bibliographic_metadata_hash(work)})
