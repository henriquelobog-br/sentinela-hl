from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from sentinela.research.models import NormalizedResearchWork, TopicAssignment


class TopicMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_version: str
    external_topic_id: str
    external_topic_name: str
    scientific_area: str
    enabled: bool = True


class TopicMappingTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_version: str
    mappings: tuple[TopicMapping, ...] = ()

    def enabled_for(self, mapping_version: str) -> dict[str, TopicMapping]:
        return {
            item.external_topic_id: item
            for item in self.mappings
            if item.enabled and item.mapping_version == mapping_version
        }


class RelevanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relevant: bool
    mapping_version: str
    scientific_areas: tuple[str, ...]
    primary_scientific_area: str | None
    mapped_topic_ids: tuple[str, ...]


def mapped_topics(
    topics: tuple[TopicAssignment, ...],
    table: TopicMappingTable,
    mapping_version: str,
) -> list[tuple[TopicAssignment, TopicMapping]]:
    enabled = table.enabled_for(mapping_version)
    matched: list[tuple[TopicAssignment, TopicMapping]] = []
    for topic in topics:
        mapping = enabled.get(topic.external_topic_id)
        if mapping is not None:
            matched.append((topic, mapping))
    return matched


def evaluate_relevance(
    work: NormalizedResearchWork,
    table: TopicMappingTable,
    mapping_version: str,
) -> RelevanceResult:
    matched = mapped_topics(work.topics, table, mapping_version)
    areas: list[str] = []
    seen: set[str] = set()
    for _topic, mapping in matched:
        if mapping.scientific_area not in seen:
            seen.add(mapping.scientific_area)
            areas.append(mapping.scientific_area)
    primary: str | None = None
    primary_matches = [pair for pair in matched if pair[0].is_primary]
    if primary_matches:
        primary = primary_matches[0][1].scientific_area
    elif matched:
        ordered = sorted(matched, key=lambda pair: (pair[0].topic_rank, pair[0].external_topic_id))
        primary = ordered[0][1].scientific_area
    return RelevanceResult(
        relevant=bool(matched),
        mapping_version=mapping_version,
        scientific_areas=tuple(areas),
        primary_scientific_area=primary,
        mapped_topic_ids=tuple(topic.external_topic_id for topic, _mapping in matched),
    )
