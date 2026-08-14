from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx

from sentinela.core.models import EventStatus
from sentinela.real_signals.config import RealSignalSettings
from sentinela.real_signals import run_real_signals
from sentinela.real_signals.collectors import CollectionResult
from sentinela.real_signals.firms import FirmsCollector
from sentinela.real_signals.orchestrator import _pipeline, _pipeline_with_eligibility
from sentinela.persistence import ResearcherSignalStoreResult, is_signal_eligible_for_persistence

NOW = datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)
REGIONS = {"test": ("Região teste", (-60.0, -20.0, -40.0, 0.0))}


def settings(**changes):
    values = {"firms_map_key": "secret-test-key", "firms_day_range": 1, "firms_max_clusters": 50}
    values.update(changes)
    return replace(RealSignalSettings.from_env(), **values)


class Response:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://firms.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("external", request=request, response=response)


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return next(self.responses)


VIIRS_HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight"
MODIS_HEADER = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight"


def viirs(lat=-10.0, lon=-50.0, time="2100", confidence="h", satellite="N", frp="12.5", brightness="340.0"):
    return f"{lat},{lon},{brightness},0.4,0.4,2026-08-10,{time},{satellite},VIIRS,{confidence},2.0NRT,300.0,{frp},N"


def modis(lat=-10.0, lon=-50.0, time="2100", confidence="80", satellite="Terra", frp="15.0", brightness="330.0"):
    return f"{lat},{lon},{brightness},1.0,1.0,2026-08-10,{time},{satellite},MODIS,{confidence},6.1NRT,295.0,{frp},N"


def csv_text(header, *rows):
    return header + "\n" + "\n".join(rows)


def collect(snpp_rows=(), noaa_rows=(), modis_rows=(), *, volcanoes=None, configured=None):
    responses = [
        Response(csv_text(VIIRS_HEADER, *snpp_rows)),
        Response(csv_text(VIIRS_HEADER, *noaa_rows)),
        Response(csv_text(MODIS_HEADER, *modis_rows)),
    ]
    collector = FirmsCollector(
        configured or settings(), Client(responses),
        monitored_volcanoes=[] if volcanoes is None else volcanoes,
        regions=REGIONS,
    )
    return collector.collect(NOW)


def test_firms_hotspot_unico():
    result = collect(snpp_rows=[viirs()])
    assert result.received == 1
    assert len(result.events) == 1
    assert result.events[0].category == "thermal_anomaly_detected"
    assert result.events[0].evidence[0]["hotspot_count"] == 1
    assert result.events[0].event_status is EventStatus.OBSERVED_FACT
    assert "incêndio confirmado" not in result.events[0].summary.lower()


def test_firms_varios_hotspots_mesmo_cluster():
    result = collect(snpp_rows=[viirs(), viirs(-10.05, -50.05, "2110")])
    assert len(result.events) == 1
    event = result.events[0]
    assert event.category == "wildfire_hotspot_cluster"
    assert len(event.evidence[0]["member_event_ids"]) == 2


def test_firms_clusters_distintos():
    result = collect(snpp_rows=[viirs(), viirs(-12.0, -52.0, "2110")])
    assert len(result.events) == 2
    assert len({event.id for event in result.events}) == 2


def test_firms_mesma_regiao_janela_idempotente():
    first = collect(snpp_rows=[viirs(), viirs(-10.05, -50.05, "2110")])
    second = collect(snpp_rows=[viirs(), viirs(-10.05, -50.05, "2110")])
    assert first.events[0].id == second.events[0].id
    assert first.events[0].primary_claim_id is None
    assert first.events[0].evidence[0]["canonical_group_id"] == second.events[0].evidence[0]["canonical_group_id"]


def test_firms_proximidade_com_vulcao():
    volcano = {
        "volcano_name": "Vulcão Teste", "volcano_number": "123456",
        "latitude": -10.02, "longitude": -50.02,
        "alert_level": "WATCH", "aviation_color_code": "ORANGE",
    }
    result = collect(snpp_rows=[viirs()], volcanoes=[volcano])
    event = result.events[0]
    assert event.category == "volcanic_thermal_anomaly_candidate"
    assert event.evidence[0]["volcano_number"] == "123456"
    assert event.evidence[0]["distance_to_volcano_km"] < 25


def test_firms_hotspot_distante_de_vulcao():
    volcano = {
        "volcano_name": "Vulcão Distante", "volcano_number": "654321",
        "latitude": 10.0, "longitude": 10.0,
    }
    result = collect(snpp_rows=[viirs()], volcanoes=[volcano])
    assert result.events[0].category == "thermal_anomaly_detected"
    assert "volcano_number" not in result.events[0].evidence[0]


def test_firms_campos_ausentes_descartados():
    broken = viirs().replace("-10.0,-50.0", ",-50.0")
    result = collect(snpp_rows=[broken])
    assert result.events == ()
    assert result.discarded == 1


def test_firms_preserva_confidence_brightness_frp_daynight():
    result = collect(snpp_rows=[viirs(confidence="l", frp="7.5", brightness="321.5")])
    evidence = result.events[0].evidence[0]
    assert evidence["confidence"] == ["l"]
    assert evidence["brightness_max"] == 321.5
    assert evidence["frp_total"] == 7.5
    assert evidence["daynight"] == ["N"]


def test_firms_sensores_distintos_sao_consolidados_com_proveniencia():
    result = collect(snpp_rows=[viirs()], noaa_rows=[viirs(satellite="N20")], modis_rows=[modis()])
    assert len(result.events) == 1
    evidence = result.events[0].evidence[0]
    assert set(evidence["sensors"]) == {
        "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT",
    }
    assert len(evidence["source_observations"]) == 3


def test_firms_novo_sensor_atualiza_mesma_ocorrencia():
    initial = collect(snpp_rows=[viirs(), viirs(-10.02, -50.02, "2110")]).events[0]
    updated = collect(
        snpp_rows=[viirs(), viirs(-10.02, -50.02, "2110")],
        noaa_rows=[viirs(-10.01, -50.01, "2130", satellite="N20")],
    ).events[0]
    assert initial.id == updated.id
    assert initial.primary_claim_id is None
    assert initial.evidence[0]["canonical_group_id"] == updated.evidence[0]["canonical_group_id"]
    assert len(initial.evidence[0]["member_event_ids"]) == 2
    assert len(updated.evidence[0]["member_event_ids"]) == 3
    assert initial.evidence[0]["occurrence_id"] == updated.evidence[0]["occurrence_id"]


def test_firms_nova_passagem_no_mesmo_dia_atualiza_ocorrencia():
    initial = collect(snpp_rows=[viirs(time="0100")]).events[0]
    updated = collect(snpp_rows=[viirs(time="0100"), viirs(-10.01, -50.01, "1300")]).events[0]
    assert initial.primary_claim_id is None
    assert initial.evidence[0]["canonical_group_id"] == updated.evidence[0]["canonical_group_id"]
    assert initial.evidence[0]["occurrence_id"] == updated.evidence[0]["occurrence_id"]
    initial_signal = _pipeline((initial,), settings())[0][0]
    updated_signal = _pipeline((updated,), settings())[0][0]
    assert initial_signal.id == updated_signal.id
    assert len(updated.evidence[0]["source_observations"]) == 2
    assert updated.evidence[0]["duration_minutes"] == 720


def test_firms_erro_api_sanitizado():
    client = Client([Response(status=500), Response(status=500), Response(status=500)])
    result = FirmsCollector(settings(), client, monitored_volcanoes=[], regions=REGIONS).collect(NOW)
    assert result.error == "falha nas consultas NASA FIRMS"
    assert "secret-test-key" not in result.error


def test_firms_lote_vazio():
    result = collect()
    assert result.received == 0
    assert result.events == ()
    assert "hotspots_validos=0" in result.notice


def test_firms_sem_chave_falha_sem_expor_segredo():
    result = FirmsCollector(settings(firms_map_key=""), Client([]), monitored_volcanoes=[], regions=REGIONS).collect(NOW)
    assert result.error == "credencial FIRMS ausente: configure SENTINELA_FIRMS_MAP_KEY"


def test_firms_scores_atuais_separam_vulcanico_e_nao_vulcanico():
    volcano = {
        "volcano_name": "Vulcão Teste", "volcano_number": "123456",
        "latitude": -10.02, "longitude": -50.02,
        "alert_level": "WATCH", "aviation_color_code": "ORANGE",
    }
    volcanic = collect(snpp_rows=[viirs()], volcanoes=[volcano]).events[0]
    non_volcanic = collect(snpp_rows=[viirs()]).events[0]
    volcanic_signal = _pipeline((volcanic,), settings())[0][0]
    non_volcanic_signal = _pipeline((non_volcanic,), settings())[0][0]
    assert volcanic_signal.relevance_score > 0.0
    assert volcanic_signal.priority_score > 0.0
    assert abs(volcanic_signal.priority_score - volcanic_signal.relevance_score * 0.75) <= 0.000001
    assert is_signal_eligible_for_persistence(volcanic_signal)
    assert non_volcanic_signal.relevance_score == 0.0
    assert non_volcanic_signal.priority_score == 0.0
    assert not is_signal_eligible_for_persistence(non_volcanic_signal)


def test_firms_kilauea_continua_tematicamente_elegivel():
    volcano = {
        "volcano_name": "Kilauea", "volcano_number": "332010",
        "latitude": 19.421, "longitude": -155.287,
        "alert_level": "ADVISORY", "aviation_color_code": "YELLOW",
    }
    responses = [
        Response(csv_text(VIIRS_HEADER, viirs(lat=19.42, lon=-155.29))),
        Response(csv_text(VIIRS_HEADER)),
        Response(csv_text(MODIS_HEADER)),
    ]
    event = FirmsCollector(
        settings(), Client(responses), monitored_volcanoes=[volcano],
        regions={"hawaii": ("Hawaii", (-156.0, 19.0, -154.5, 20.0))},
    ).collect(NOW).events[0]
    signal = _pipeline((event,), settings())[0][0]
    assert event.category == "volcanic_thermal_anomaly_candidate"
    assert event.evidence[0]["volcano_name"] == "Kilauea"
    assert is_signal_eligible_for_persistence(signal)


def test_firms_cluster_amazonia_apenas_regional_nao_elegivel():
    responses = [
        Response(csv_text(VIIRS_HEADER, viirs())),
        Response(csv_text(VIIRS_HEADER)),
        Response(csv_text(MODIS_HEADER)),
    ]
    event = FirmsCollector(
        settings(), Client(responses), monitored_volcanoes=[],
        regions={"amazon": ("Amazônia", (-60.0, -20.0, -40.0, 0.0))},
    ).collect(NOW).events[0]
    signal = _pipeline((event,), settings())[0][0]
    assert signal.relevance_score > 0.0
    assert _pipeline_with_eligibility((event,), settings())[2] == ()


def test_firms_falha_nao_interrompe_outra_fonte():
    class Collector:
        def __init__(self, result):
            self.result = result

        def collect(self, now):
            return self.result

    run = run_real_signals(
        settings=settings(), sources=("firms", "other"), now=NOW,
        collectors={
            "firms": Collector(CollectionResult(source="firms", error="falha sanitizada")),
            "other": Collector(CollectionResult(source="other", notice="fonte consultada")),
        },
    )
    assert [item.source for item in run.collections] == ["firms", "other"]
    assert run.collections[0].error == "falha sanitizada"
    assert run.collections[1].notice == "fonte consultada"


def test_persistencia_generica_recebe_apenas_firms_elegivel():
    volcano = {
        "volcano_name": "Vulcão Teste", "volcano_number": "123456",
        "latitude": -10.02, "longitude": -50.02,
        "alert_level": "WATCH", "aviation_color_code": "ORANGE",
    }
    volcanic = collect(snpp_rows=[viirs()], volcanoes=[volcano]).events[0]
    responses = [
        Response(csv_text(VIIRS_HEADER, viirs())),
        Response(csv_text(VIIRS_HEADER)),
        Response(csv_text(MODIS_HEADER)),
    ]
    amazon = FirmsCollector(
        settings(), Client(responses), monitored_volcanoes=[],
        regions={"amazon": ("Amazônia", (-60.0, -20.0, -40.0, 0.0))},
    ).collect(NOW).events[0]

    class Collector:
        def collect(self, now):
            return CollectionResult(source="firms", events=(volcanic, amazon))

    class Store:
        def __init__(self):
            self.batches = []

        def upsert_many(self, signals):
            self.batches.append(signals)
            return ResearcherSignalStoreResult(
                received=len(signals), persisted=len(signals),
                persisted_ids=tuple(signal.id for signal in signals),
            )

    store = Store()
    first = run_real_signals(
        settings=settings(), sources=("firms",), now=NOW,
        collectors={"firms": Collector()}, store=store,
    )
    second = run_real_signals(
        settings=settings(), sources=("firms",), now=NOW,
        collectors={"firms": Collector()}, store=store,
    )
    assert len(first.signals) == 2
    assert first.persistence.received == 1
    assert second.persistence.persisted_ids == first.persistence.persisted_ids
    assert len(store.batches[0]) == 1
