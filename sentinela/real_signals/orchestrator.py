"""Orquestracao fontes reais -> pipeline cientifico -> ResearcherSignal."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal
from uuid import uuid4

import httpx

from sentinela.fingerprint import ConceptFingerprintEngine, FingerprintConfig
from sentinela.fingerprint.models import ConceptMatchType, FingerprintField
from sentinela.interest import (
    InterestChannelWeights, InterestEngine, InterestEngineConfig,
    InterestEngineLimits, InterestPriority, InterestPriorityThresholds,
    InterestReasonTemplates, InterestReasonType, InterestScoringConfig,
    load_research_profile,
)
from sentinela.persistence import (
    CanonicalProvenanceStore, CanonicalProvenanceStoreError, CollectorRunAudit,
    EventStore, EventStoreResult,
    PipelineRunAuditFinal,
    PipelineRunAuditStart, PipelineRunAuditStore, PipelineRunAuditStoreError,
    ResearcherSignalStore, ResearcherSignalStoreResult,
    is_signal_eligible_for_persistence, safe_error_type, sanitize_audit_error,
)
from sentinela.canonical_provenance import (
    CanonicalEventAcceptance,
    CanonicalEventCandidate,
    CollectorRole,
    accept_canonical_events,
    build_canonical_signal_record,
)
from sentinela.canonical_provenance.models import (
    CanonicalEventPersistenceResult,
    CanonicalSignalPersistenceResult,
    RunManifestFinal,
)
from sentinela.prioritized_bulletin.engine import _event_dedup_key
from sentinela.prioritized_bulletin import (
    PrioritizedBulletinConfig, PrioritizedBulletinContext,
    PrioritizedBulletinDeduplicationPolicy, PrioritizedBulletinEngine,
    PrioritizedBulletinEntry, PrioritizedBulletinGroupingPolicy,
    PrioritizedBulletinRequest, PrioritizedBulletinSectionTitle,
)
from sentinela.projection import ResearcherSignal, project_researcher_signals
from sentinela.radar import (
    EventRadar, EventRadarConfig, EventRadarLimits, EventRadarThresholds,
    RadarDomain, RadarSignal,
)
from sentinela.taxonomy.loader import load_taxonomy
from sentinela.taxonomy.models import normalize_term
from sentinela.taxonomy.taxonomy import TaxonomyIndex

from .collectors import CamsCollector, CmrCollector, CollectionResult, Merra2Collector
from .acled import AcledCollector, possible_cross_source_matches
from .config import RealSignalSettings
from .climate import OpenMeteoClimateCollector
from .firms import FirmsCollector
from .multithematic import (
    DonkiCollector, OpenMeteoMarineCollector, OpenMeteoWeatherCollector,
    UsgsCollector,
)
from .noaa import (
    NoaaCoopsCollector, NoaaNdbcCollector, possible_forecast_observation_matches,
)
from .nws import NwsAlertsCollector
from .volcano_geopolitics import GdeltCollector, GvpCollector, UsgsVolcanoCollector

ROOT = Path(__file__).resolve().parents[2]
REASON = "Sinal {signal_id} ativado pelo conceito {concept_id}: peso do sinal {signal_weight}, peso do conceito {concept_weight}, contribuicao {contribution}."


@dataclass(frozen=True)
class RunResult:
    run_id: str
    started_at: datetime
    completed_at: datetime
    requested_sources: tuple[str, ...]
    consulted_sources: tuple[str, ...]
    supporting_sources: tuple[str, ...]
    successful_sources: tuple[str, ...]
    failed_sources: tuple[str, ...]
    records_received: int
    events_produced: int
    signals_produced: int
    signals_eligible: int
    signals_persisted: int

    @property
    def status(self) -> str:
        requested_successes = set(self.requested_sources) & set(self.successful_sources)
        if not requested_successes:
            return "failed"
        if self.failed_sources:
            return "partial"
        return "complete"

    @property
    def partial(self) -> bool:
        return self.status == "partial"


@dataclass(frozen=True)
class RealSignalRun:
    collections: tuple[CollectionResult, ...]
    events: tuple[Any, ...]
    signals: tuple[ResearcherSignal, ...]
    result: RunResult
    persistence: ResearcherSignalStoreResult | None = None
    event_persistence: EventStoreResult | None = None
    canonical_event_persistence: CanonicalEventPersistenceResult | None = None
    canonical_signal_persistence: CanonicalSignalPersistenceResult | None = None
    canonical_event_acceptance: CanonicalEventAcceptance | None = None
    unmatched_terms: tuple[str, ...] = ()
    eligible_signal_ids: tuple[str, ...] = ()

    @property
    def received(self) -> int:
        return sum(item.received for item in self.collections)

    @property
    def discarded(self) -> int:
        return sum(item.discarded for item in self.collections)

    @property
    def duplicates(self) -> int:
        return sum(item.duplicates for item in self.collections)


@dataclass
class _AuditProgress:
    stage: str = "initialization"
    consulted_sources: tuple[str, ...] = ()
    successful_sources: tuple[str, ...] = ()
    failed_sources: tuple[str, ...] = ()
    records_received: int = 0
    candidates_generated: int = 0
    signals_generated: int = 0
    signals_eligible: int = 0
    signals_persisted: int = 0
    canonical_events_accepted: int = 0
    canonical_events_rejected: int = 0
    canonical_signals_persisted: int = 0


_COLLECTOR_AREAS: dict[str, tuple[str, ...]] = {
    "cams": ("atmospheric_science",),
    "cmr": ("atmospheric_science",),
    "merra2": ("atmospheric_science",),
    "usgs": ("seismology",),
    "openmeteo-weather": ("climate_science",),
    "openmeteo-marine": ("oceanography",),
    "openmeteo-climate": ("climate_science",),
    "nws-alerts": ("climate_science",),
    "noaa-coops": ("oceanography",),
    "noaa-ndbc": ("oceanography",),
    "donki": ("space_weather",),
    "usgs-volcano": ("volcanology",),
    "gvp": ("volcanology",),
    "gdelt": ("scientific_geopolitics",),
    "acled": ("scientific_geopolitics",),
    "firms": ("environmental_monitoring", "volcanology"),
}


def _configs(taxonomy_version: str):
    fingerprint = FingerprintConfig(version="1.0")
    radar = EventRadarConfig(
        config_version="real-signals-1", algorithm_version="1.0",
        compatible_taxonomy_version=taxonomy_version,
        thresholds=EventRadarThresholds(),
        limits=EventRadarLimits(maximum_signals=16, maximum_concepts_per_signal=16, maximum_signal_id_length=128, maximum_description_length=1024, maximum_reason_template_length=2048),
        signals=(
            RadarSignal(id="atmosphere.mineral_dust", domain=RadarDomain.ATMOSPHERE, description="Evidencia objetiva relacionada a poeira mineral.", concept_ids=("mineral_dust",), weight=0.60, reason_template=REASON),
            RadarSignal(id="atmosphere.aerosol", domain=RadarDomain.ATMOSPHERE, description="Novo produto ou medida de aerossol.", concept_ids=("aerosols", "aerosol_optical_depth"), weight=0.30, reason_template=REASON),
            RadarSignal(id="remote_sensing.observation", domain=RadarDomain.REMOTE_SENSING, description="Evidencia de sensoriamento remoto ou reanalise.", concept_ids=("satellite_observation", "satellite_instruments", "reanalysis"), weight=0.30, reason_template=REASON),
        ),
    )
    interest = InterestEngineConfig(
        config_version="real-signals-1", algorithm_version="1.0",
        compatible_taxonomy_version=taxonomy_version,
        compatible_fingerprint_algorithm_version="1.0",
        scoring=InterestScoringConfig(relevance_factor=0.75, significance_factor=0.25),
        channel_weights=InterestChannelWeights(concept=1.0, domain=0.65, region=0.55, instrument=0.55, research_line=0.85),
        thresholds=InterestPriorityThresholds(moderate_min=0.25, high_min=0.50, urgent_min=0.75),
        limits=InterestEngineLimits(maximum_profile_domains=1024, maximum_profile_concepts=4096, maximum_profile_regions=1024, maximum_profile_instruments=1024, maximum_research_lines=256, maximum_items_per_research_line=512, maximum_total_research_line_items=16384, maximum_fingerprint_concepts=4096, maximum_matches=8192, maximum_reason_length=2048),
        reason_templates=InterestReasonTemplates(
            system_reason_order=(InterestReasonType.NO_POSITIVE_MATCH, InterestReasonType.RADAR_CONTRIBUTION, InterestReasonType.CRITICAL_WITHOUT_ALIGNMENT, InterestReasonType.HUMAN_REVIEW, InterestReasonType.IGNORED_V1_FIELDS),
            positive_global_match="Conceito {fingerprint_concept_id}, dominio {domain_id}, escopo {scope}, canal {channel}, item do perfil {profile_item_id}: peso do fingerprint {fingerprint_weight}, peso do perfil {profile_weight}, peso efetivo do canal {channel_weight}, contribuicao {contribution}.",
            positive_research_line_match="Conceito {fingerprint_concept_id}, dominio {domain_id}, escopo {scope}, canal {channel}, item do perfil {profile_item_id}, linha {research_line_id}: peso do fingerprint {fingerprint_weight}, peso do perfil {profile_weight}, prioridade da linha {line_priority}, peso efetivo do canal {channel_weight}, contribuicao {contribution}.",
            no_positive_match="Evento {event_id} sem alinhamento positivo com a agenda do pesquisador {researcher_id}.",
            radar_contribution="Significancia objetiva preservada: score {significance_score}, nivel {significance_level}, fator {significance_factor}, contribuicao para a prioridade {significance_contribution}.",
            critical_without_alignment="Evento critico sem alinhamento positivo: score {significance_score}, nivel {significance_level}, contribuicao objetiva {significance_contribution}.",
            human_review="Evento {event_id} no estado {pipeline_status} requer revisao humana.",
            ignored_v1_fields="Campos do perfil nao aplicados na V1: {ignored_fields}.",
        ),
    )
    bulletin = PrioritizedBulletinConfig(
        algorithm_version="1.0", config_version="real-signals-1",
        grouping_policy=PrioritizedBulletinGroupingPolicy.PRIORITY,
        deduplication_policy=PrioritizedBulletinDeduplicationPolicy.PRIMARY_CLAIM_OR_EVENT_ID,
        priority_order=(InterestPriority.URGENT, InterestPriority.HIGH, InterestPriority.MODERATE, InterestPriority.LOW),
        section_titles=(
            PrioritizedBulletinSectionTitle(priority=InterestPriority.URGENT, title="Urgente"),
            PrioritizedBulletinSectionTitle(priority=InterestPriority.HIGH, title="Alta prioridade"),
            PrioritizedBulletinSectionTitle(priority=InterestPriority.MODERATE, title="Prioridade moderada"),
            PrioritizedBulletinSectionTitle(priority=InterestPriority.LOW, title="Baixa prioridade"),
        ),
        maximum_entries=5000, maximum_group_members=500, maximum_sections=4, maximum_items_per_section=5000,
    )
    return fingerprint, radar, interest, bulletin


def _stable_group_signal(signal: ResearcherSignal, event_by_id: dict[str, Any]) -> ResearcherSignal:
    event = event_by_id[signal.representative_event_id]
    group_id = _event_dedup_key(event)[1]
    canonical = "|".join((signal.researcher_id, group_id, signal.research_profile_version, signal.taxonomy_version, signal.algorithm_version, signal.config_version))
    update: dict[str, Any] = {"id": hashlib.sha256(canonical.encode()).hexdigest()}
    if event.evidence:
        member_event_ids = event.evidence[0].get("member_event_ids")
        if member_event_ids:
            update["member_event_ids"] = tuple(member_event_ids)
    return signal.model_copy(update=update)


def _geographic_terms(event: Any) -> tuple[str, ...]:
    values: list[str] = []
    if event.country:
        values.append(event.country)
    for item in event.entities:
        if isinstance(item, dict) and item.get("type") in {"country", "location", "place", "region"}:
            values.append(str(item.get("name") or ""))
    for item in event.evidence:
        if not isinstance(item, dict):
            continue
        for key in ("country", "location", "place", "region"):
            if item.get(key):
                values.append(str(item[key]))
        values.extend(str(value) for value in item.get("regions", ()) if value)
    return tuple(
        normalize_term(value).replace("_", " ")
        for value in values if normalize_term(value)
    )


def _thematic_direct_concepts(event: Any, fingerprint: Any) -> frozenset[str]:
    geography = _geographic_terms(event)
    thematic = set()
    for concept in fingerprint.concepts:
        for evidence in concept.evidence:
            if evidence.match_type in {ConceptMatchType.PARENT, ConceptMatchType.RELATED}:
                continue
            term = normalize_term(evidence.matched_term).replace("_", " ")
            geographic_match = evidence.field == FingerprintField.COUNTRY or any(
                term == place or term in place for place in geography
            )
            if not geographic_match:
                thematic.add(concept.concept_id)
                break
    return frozenset(thematic)


def _pipeline_with_eligibility(
    events: tuple[Any, ...], settings: RealSignalSettings,
) -> tuple[tuple[ResearcherSignal, ...], tuple[str, ...], tuple[str, ...]]:
    taxonomy = load_taxonomy(ROOT / "taxonomy")
    index = TaxonomyIndex(taxonomy)
    profile = load_research_profile(ROOT / "profiles" / "henrique_lobo.yaml", index)
    if profile.researcher.id != settings.researcher_id:
        profile = profile.model_copy(update={"researcher": profile.researcher.model_copy(update={"id": settings.researcher_id})})
    fingerprint_config, radar_config, interest_config, bulletin_config = _configs(taxonomy.version)
    fingerprint_engine = ConceptFingerprintEngine(index, fingerprint_config)
    radar = EventRadar(radar_config)
    interest = InterestEngine(interest_config)
    entries = []
    unmatched_terms: set[str] = set()
    direct_concepts_by_event: dict[str, frozenset[str]] = {}
    for event in events:
        fingerprint = fingerprint_engine.build(event)
        direct_concepts_by_event[str(event.id)] = _thematic_direct_concepts(event, fingerprint)
        unmatched_terms.update(
            term.input_term
            for term in fingerprint.unmatched_terms
            if term.field.value == "keyword"
        )
        radar_result = radar.evaluate(event, fingerprint)
        interest_result = interest.evaluate(event=event, fingerprint=fingerprint, radar_result=radar_result, profile=profile)
        entries.append(PrioritizedBulletinEntry(event=event, interest_result=interest_result))
    context = PrioritizedBulletinContext(researcher_id=profile.researcher.id, profile_version=str(profile.researcher.version), taxonomy_version=taxonomy.version, interest_algorithm_version=interest_config.algorithm_version, interest_config_version=interest_config.config_version)
    bulletin = PrioritizedBulletinEngine(bulletin_config).build(PrioritizedBulletinRequest(context=context, entries=tuple(entries)))
    event_by_id = {str(event.id): event for event in events}
    signals = tuple(_stable_group_signal(signal, event_by_id) for signal in project_researcher_signals(bulletin))
    eligible_ids = tuple(
        signal.id for signal in signals
        if is_signal_eligible_for_persistence(
            signal,
            direct_concept_ids=direct_concepts_by_event.get(signal.representative_event_id, frozenset()),
        )
    )
    return signals, tuple(sorted(unmatched_terms)), eligible_ids


def _pipeline(events: tuple[Any, ...], settings: RealSignalSettings) -> tuple[tuple[ResearcherSignal, ...], tuple[str, ...]]:
    signals, unmatched_terms, _ = _pipeline_with_eligibility(events, settings)
    return signals, unmatched_terms


def run_real_signals(
    *,
    settings: RealSignalSettings,
    sources: Iterable[str] = ("cams", "cmr", "merra2"),
    now: datetime | None = None,
    collectors: dict[str, Any] | None = None,
    event_store: EventStore | None = None,
    store: ResearcherSignalStore | None = None,
    audit_store: PipelineRunAuditStore | None = None,
    canonical_store: CanonicalProvenanceStore | None = None,
    audit_mode: Literal["dry_run", "persist"] | None = None,
    audit_initiated_by: str = "python_api",
) -> RealSignalRun:
    started_at = datetime.now(timezone.utc)
    current = (now or started_at).astimezone(timezone.utc)
    requested_sources = tuple(dict.fromkeys(sources))
    run_id = str(uuid4())
    mode = audit_mode or (
        "persist" if store is not None or canonical_store is not None else "dry_run"
    )
    progress = _AuditProgress()

    if canonical_store is not None and audit_store is None:
        raise ValueError("canonical persistence requires PipelineRunAuditStore")
    if canonical_store is not None and (event_store is not None or store is not None):
        raise ValueError(
            "canonical persistence cannot be combined with legacy scientific stores"
        )
    if canonical_store is not None and mode != "persist":
        raise ValueError("canonical persistence requires persist audit mode")

    if audit_store is not None:
        audit_store.create_run(
            PipelineRunAuditStart(
                run_id=run_id,
                initiated_by=audit_initiated_by,
                mode=mode,
                started_at=started_at,
                requested_sources=requested_sources,
            )
        )

    try:
        run = _execute_real_signals(
            settings=settings,
            collectors=collectors,
            event_store=event_store,
            store=store,
            audit_store=audit_store,
            canonical_store=canonical_store,
            started_at=started_at,
            current=current,
            requested_sources=requested_sources,
            run_id=run_id,
            progress=progress,
        )
    except Exception as exc:
        if canonical_store is not None:
            try:
                canonical_store.finalize_manifest(
                    RunManifestFinal(
                        run_id=run_id,
                        stage="failed",
                        accepted_events=progress.canonical_events_accepted,
                        rejected_events=progress.canonical_events_rejected,
                        persisted_signals=progress.canonical_signals_persisted,
                        versions={"canonical_provenance": "v1"},
                        commit_ambiguous=(
                            isinstance(exc, CanonicalProvenanceStoreError)
                            and exc.commit_ambiguous
                        ),
                        error_type=type(exc).__name__,
                        error_message="canonical pipeline execution failed",
                    )
                )
            except Exception:
                pass
        if audit_store is not None:
            completed_at = datetime.now(timezone.utc)
            failed = PipelineRunAuditFinal(
                run_id=run_id,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                requested_sources=requested_sources,
                consulted_sources=progress.consulted_sources,
                successful_sources=progress.successful_sources,
                failed_sources=progress.failed_sources,
                records_received=progress.records_received,
                candidates_generated=progress.candidates_generated,
                signals_generated=progress.signals_generated,
                signals_eligible=progress.signals_eligible,
                signals_persisted=progress.signals_persisted,
                error_stage=progress.stage,
                error_type=safe_error_type(exc),
                error_message=(
                    "audit operation failed"
                    if isinstance(exc, PipelineRunAuditStoreError)
                    else "pipeline execution failed"
                ),
            )
            try:
                audit_store.finalize_run(failed)
            except Exception:
                # The original scientific/operational exception remains primary.
                pass
        raise

    if audit_store is not None:
        status = {
            "complete": "succeeded",
            "partial": "partial",
            "failed": "failed",
        }[run.result.status]
        audit_store.finalize_run(
            PipelineRunAuditFinal(
                run_id=run.result.run_id,
                status=status,
                started_at=run.result.started_at,
                completed_at=run.result.completed_at,
                requested_sources=run.result.requested_sources,
                consulted_sources=run.result.consulted_sources,
                successful_sources=run.result.successful_sources,
                failed_sources=run.result.failed_sources,
                records_received=run.result.records_received,
                candidates_generated=run.result.events_produced,
                signals_generated=run.result.signals_produced,
                signals_eligible=run.result.signals_eligible,
                signals_persisted=run.result.signals_persisted,
            )
        )
    if canonical_store is not None:
        canonical_store.finalize_manifest(
            RunManifestFinal(
                run_id=run.result.run_id,
                stage="finalized",
                accepted_events=progress.canonical_events_accepted,
                rejected_events=progress.canonical_events_rejected,
                persisted_signals=progress.canonical_signals_persisted,
                versions={"canonical_provenance": "v1"},
            )
        )
    return run


def _execute_real_signals(
    *,
    settings: RealSignalSettings,
    collectors: dict[str, Any] | None,
    event_store: EventStore | None,
    store: ResearcherSignalStore | None,
    audit_store: PipelineRunAuditStore | None,
    canonical_store: CanonicalProvenanceStore | None,
    started_at: datetime,
    current: datetime,
    requested_sources: tuple[str, ...],
    run_id: str,
    progress: _AuditProgress,
) -> RealSignalRun:
    configured = collectors or {
        "cams": CamsCollector(settings),
        "cmr": CmrCollector(settings),
        "merra2": Merra2Collector(settings),
        "usgs": UsgsCollector(settings),
        "openmeteo-weather": OpenMeteoWeatherCollector(settings),
        "openmeteo-marine": OpenMeteoMarineCollector(settings),
        "openmeteo-climate": OpenMeteoClimateCollector(settings),
        "nws-alerts": NwsAlertsCollector(settings),
        "noaa-coops": NoaaCoopsCollector(settings),
        "noaa-ndbc": NoaaNdbcCollector(settings),
        "donki": DonkiCollector(settings),
        "usgs-volcano": UsgsVolcanoCollector(settings),
        "gvp": GvpCollector(settings),
        "gdelt": GdeltCollector(settings),
        "acled": AcledCollector(settings),
        "firms": FirmsCollector(settings),
    }
    results: list[CollectionResult] = []
    requested_results: dict[str, CollectionResult] = {}
    consulted_sources: list[str] = []
    supporting_sources: list[str] = []
    source_outcomes: dict[str, CollectionResult] = {}

    def collect(source: str, *, supporting: bool = False) -> CollectionResult:
        consulted_sources.append(source)
        progress.consulted_sources = tuple(consulted_sources)
        if supporting:
            supporting_sources.append(source)
        collector_started_at = datetime.now(timezone.utc)
        role = "supporting" if supporting else "requested"
        progress.stage = "audit_collector_start"
        if audit_store is not None:
            audit_store.record_collector(
                CollectorRunAudit(
                    run_id=run_id,
                    collector=source,
                    collector_role=role,
                    scientific_areas=_COLLECTOR_AREAS.get(source, ()),
                    status="running",
                    started_at=collector_started_at,
                )
            )
        progress.stage = "collection"
        raised_error: Exception | None = None
        try:
            result = configured[source].collect(current)
        except Exception as exc:
            raised_error = exc
            result = CollectionResult(source=source, error=type(exc).__name__)
        collector_completed_at = datetime.now(timezone.utc)
        areas = tuple(
            dict.fromkeys(
                event.scientific_area
                for event in result.events
                if event.scientific_area
            )
        ) or _COLLECTOR_AREAS.get(source, ())
        progress.stage = "audit_collector_finish"
        if audit_store is not None:
            audit_store.record_collector(
                CollectorRunAudit(
                    run_id=run_id,
                    collector=source,
                    collector_role=role,
                    scientific_areas=areas,
                    status="failed" if result.error is not None else "succeeded",
                    started_at=collector_started_at,
                    completed_at=collector_completed_at,
                    records_received=result.received,
                    candidates_generated=len(result.events),
                    signals_generated=None,
                    error_type=(
                        safe_error_type(raised_error)
                        if raised_error is not None
                        else "CollectorReportedError" if result.error else None
                    ),
                    error_message=(
                        "collector execution failed"
                        if raised_error is not None
                        else sanitize_audit_error(result.error)
                    ),
                )
            )
        source_outcomes[source] = result
        results.append(result)
        progress.successful_sources = tuple(
            item for item in consulted_sources
            if source_outcomes.get(item) is not None
            and source_outcomes[item].error is None
        )
        progress.failed_sources = tuple(
            item for item in consulted_sources
            if source_outcomes.get(item) is not None
            and source_outcomes[item].error is not None
        )
        if not supporting:
            progress.records_received += result.received
        return result

    for source in requested_sources:
        requested_results[source] = collect(source)

    acled_result = requested_results.get("acled")
    if acled_result is not None and acled_result.events:
        gdelt_result = requested_results.get("gdelt")
        if gdelt_result is None:
            gdelt_result = collect("gdelt", supporting=True)
        matches = possible_cross_source_matches(
            acled_result.events,
            gdelt_result.events if gdelt_result is not None else (),
        )
        notice = "; ".join(filter(None, (
            acled_result.notice,
            f"possible_cross_source_matches={len(matches)}",
        )))
        supported_events = (
            tuple(
                event.model_copy(update={
                    "supporting_sources": tuple(dict.fromkeys((*event.supporting_sources, "gdelt")))
                })
                for event in acled_result.events
            )
            if gdelt_result.error is None else acled_result.events
        )
        updated = replace(
            acled_result, notice=notice,
            details=acled_result.details + matches, events=supported_events,
        )
        requested_results["acled"] = updated
        source_outcomes["acled"] = updated
        results[results.index(acled_result)] = updated

    ndbc_result = requested_results.get("noaa-ndbc")
    if ndbc_result is not None and ndbc_result.events:
        marine_result = requested_results.get("openmeteo-marine")
        if marine_result is None:
            marine_result = collect("openmeteo-marine", supporting=True)
        matches = possible_forecast_observation_matches(ndbc_result.events, marine_result.events)
        supported_events = (
            tuple(
                event.model_copy(update={
                    "supporting_sources": tuple(dict.fromkeys((*event.supporting_sources, "openmeteo-marine")))
                })
                for event in ndbc_result.events
            )
            if marine_result.error is None else ndbc_result.events
        )
        updated = replace(
            ndbc_result,
            notice="; ".join(filter(None, (ndbc_result.notice, f"possible_forecast_observation_matches={len(matches)}"))),
            details=ndbc_result.details + matches, events=supported_events,
        )
        requested_results["noaa-ndbc"] = updated
        source_outcomes["noaa-ndbc"] = updated
        results[results.index(ndbc_result)] = updated
    unique = {}
    duplicate_count = 0
    for result in requested_results.values():
        for event in result.events:
            if event.id in unique:
                duplicate_count += 1
            unique[event.id] = event
    if duplicate_count:
        results.append(CollectionResult(source="batch", duplicates=duplicate_count))
    events = tuple(sorted(unique.values(), key=lambda event: (event.occurred_at or current, str(event.id))))
    canonical_acceptance = None
    canonical_event_persistence = None
    if canonical_store is not None:
        candidates = tuple(
            CanonicalEventCandidate(
                event=event,
                collector=source,
                collector_role=CollectorRole.REQUESTED,
            )
            for source, result in requested_results.items()
            for event in result.events
        )
        progress.stage = "canonical_acceptance"
        canonical_acceptance = accept_canonical_events(candidates)
        events = tuple(item.event for item in canonical_acceptance.accepted)
        progress.canonical_events_accepted = len(canonical_acceptance.accepted)
        progress.canonical_events_rejected = len(canonical_acceptance.rejected)
        progress.stage = "canonical_event_persistence"
        canonical_event_persistence = canonical_store.persist_events(
            run_id, canonical_acceptance
        )
    progress.candidates_generated = len(events)
    progress.stage = "event_persistence"
    event_persistence = event_store.upsert_many(events) if event_store is not None else None
    progress.stage = "scientific_pipeline"
    signals, unmatched_terms, eligible_signal_ids = _pipeline_with_eligibility(events, settings)
    progress.signals_generated = len(signals)
    progress.signals_eligible = len(eligible_signal_ids)
    eligible_id_set = set(eligible_signal_ids)
    eligible_signals = tuple(signal for signal in signals if signal.id in eligible_id_set)
    canonical_signal_persistence = None
    if canonical_store is not None:
        accepted_event_ids = frozenset(str(event.id) for event in events)
        grouped_event_ids: dict[tuple[Any, ...], tuple[str, ...]] = {}
        for event in events:
            key = _event_dedup_key(event)
            grouped_event_ids[key] = tuple(
                str(member.id)
                for member in events
                if _event_dedup_key(member) == key
            )
        canonical_signal_records = []
        event_by_id = {str(event.id): event for event in events}
        for signal in eligible_signals:
            representative_event = event_by_id[signal.representative_event_id]
            members = grouped_event_ids[_event_dedup_key(representative_event)]
            canonical_signal_records.append(
                build_canonical_signal_record(
                    signal,
                    representative_event_id=signal.representative_event_id,
                    contributor_event_ids=tuple(
                        item for item in members
                        if item != signal.representative_event_id
                    ),
                    accepted_event_ids=accepted_event_ids,
                )
            )
        progress.stage = "canonical_signal_persistence"
        canonical_signal_persistence = canonical_store.persist_signals(
            run_id, tuple(canonical_signal_records)
        )
        progress.canonical_signals_persisted = canonical_signal_persistence.persisted
    progress.stage = "signal_persistence"
    persistence = store.upsert_many(eligible_signals) if store is not None else None
    progress.signals_persisted = (
        persistence.persisted if persistence is not None
        else canonical_signal_persistence.persisted
        if canonical_signal_persistence is not None else 0
    )
    completed_at = datetime.now(timezone.utc)
    successful_sources = tuple(
        source for source in consulted_sources
        if source_outcomes[source].error is None
    )
    failed_sources = tuple(
        source for source in consulted_sources
        if source_outcomes[source].error is not None
    )
    result = RunResult(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        requested_sources=requested_sources,
        consulted_sources=tuple(consulted_sources),
        supporting_sources=tuple(supporting_sources),
        successful_sources=successful_sources,
        failed_sources=failed_sources,
        records_received=sum(item.received for item in requested_results.values()),
        events_produced=len(events),
        signals_produced=len(signals),
        signals_eligible=len(eligible_signal_ids),
        signals_persisted=progress.signals_persisted,
    )
    progress.stage = "completed"
    return RealSignalRun(
        collections=tuple(results), events=events, signals=signals,
        result=result, persistence=persistence, event_persistence=event_persistence,
        canonical_event_persistence=canonical_event_persistence,
        canonical_signal_persistence=canonical_signal_persistence,
        canonical_event_acceptance=canonical_acceptance,
        unmatched_terms=unmatched_terms,
        eligible_signal_ids=eligible_signal_ids,
    )


__all__ = ["RealSignalRun", "RunResult", "run_real_signals"]
