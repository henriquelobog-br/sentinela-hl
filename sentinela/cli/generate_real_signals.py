"""CLI para ingestao idempotente de sinais atmosfericos reais."""

from __future__ import annotations

import argparse
import sys

from sentinela.persistence import SupabaseResearcherSignalStore
from sentinela.real_signals import RealSignalSettings, run_real_signals

OPERATIONAL_SOURCES = (
    "cams", "cmr", "merra2", "usgs", "openmeteo-weather",
    "openmeteo-marine", "nws-alerts", "donki", "noaa-coops", "noaa-ndbc",
    "usgs-volcano", "gvp", "gdelt", "acled", "firms",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--persist", action="store_true")
    parser.add_argument("--source", choices=("cams", "cmr", "merra2", "usgs", "openmeteo-weather", "openmeteo-marine", "openmeteo-climate", "nws-alerts", "noaa-coops", "noaa-ndbc", "donki", "usgs-volcano", "gvp", "gdelt", "acled", "firms", "all"), default="all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = RealSignalSettings.from_env()
        store = SupabaseResearcherSignalStore(timeout=settings.timeout_seconds) if args.persist else None
        sources = OPERATIONAL_SOURCES if args.source == "all" else (args.source,)
        run = run_real_signals(settings=settings, sources=sources, store=store)
    except (ValueError, RuntimeError) as exc:
        print(f"erro: {type(exc).__name__}")
        return 1
    print(f"run_status: {run.result.status}")
    print("sources_requested: " + ", ".join(run.result.requested_sources))
    print("sources_consulted: " + ", ".join(run.result.consulted_sources))
    print("supporting_sources: " + ", ".join(run.result.supporting_sources))
    print("sources_successful: " + ", ".join(run.result.successful_sources))
    print("sources_failed: " + ", ".join(run.result.failed_sources))
    print(f"registros_recebidos: {run.received}")
    print(f"janelas_formadas: {len(run.events)}")
    print(f"eventos_candidatos: {len(run.events)}")
    print(f"eventos_descartados: {run.discarded}")
    print(f"sinais_produzidos: {len(run.signals)}")
    eligible = len(run.eligible_signal_ids)
    print(f"sinais_elegiveis_persistencia: {eligible}")
    print(f"sinais_bloqueados_persistencia: {len(run.signals) - eligible}")
    print(f"sinais_persistidos: {run.persistence.persisted if run.persistence else 0}")
    print("sinais_atualizados: nao_aplicavel" if not args.persist else "sinais_atualizados: contabilizados_por_upsert")
    print(f"duplicatas_evitadas: {run.duplicates}")
    if run.unmatched_terms:
        print("conceitos_sem_correspondencia: " + ", ".join(run.unmatched_terms))
    for item in run.collections:
        if item.error:
            print(f"erro_fonte[{item.source}]: {item.error}")
        if item.notice:
            print(f"aviso_fonte[{item.source}]: {item.notice}")
        if item.details:
            if item.source == "gdelt":
                categories = {"conflito_seguranca": 0, "diplomacia": 0, "abraham_accords": 0, "protesto": 0}
                for event in item.events:
                    if event.category == "abraham_accords_activity_reported":
                        categories["abraham_accords"] += 1
                    elif event.category == "geopolitical_diplomacy_reported":
                        categories["diplomacia"] += 1
                    elif event.category == "geopolitical_protest_reported":
                        categories["protesto"] += 1
                    else:
                        categories["conflito_seguranca"] += 1
                print("categorias[gdelt]: " + " | ".join(f"{key}={value}" for key, value in categories.items()))
            regions = sorted({str(detail.get("region")) for detail in item.details if detail.get("region")})
            if regions:
                print(f"regioes_avaliadas[{item.source}]: {', '.join(regions)}")
            for detail in item.details:
                fields = (
                    "region", "variable", "value", "unit", "threshold",
                    "window_start", "window_end", "latency_hours",
                    "max_latency_hours",
                )
                rendered = " | ".join(
                    f"{field}={detail[field]}"
                    for field in fields
                    if detail.get(field) is not None
                )
                if rendered:
                    print(f"valor_agregado[{item.source}]: {rendered}")
    for event in run.events:
        evidence = event.evidence[0]
        region = evidence.get("region") or ",".join(evidence.get("regions", []))
        print(f"EVENT {event.category} | source={evidence.get('source')} | occurred_at={event.occurred_at.isoformat()} | region={region}")
        print(f"title: {event.title}")
        print(f"summary: {event.summary}")
        if "granule_count" in evidence:
            print(f"member_event_ids: {len(evidence['member_event_ids'])}")
            print(f"earliest_occurred_at: {evidence['earliest_occurred_at']}")
            print(f"latest_occurred_at: {evidence['latest_occurred_at']}")
    return 1 if run.result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
