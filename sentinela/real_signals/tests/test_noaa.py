from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx

from sentinela.cli.generate_real_signals import _parser
from sentinela.real_signals.collectors import CollectionResult, _event
from sentinela.real_signals.config import CoopsStation, NdbcStation, RealSignalSettings
from sentinela.real_signals.noaa import (
    NoaaCoopsCollector, NoaaNdbcCollector, possible_forecast_observation_matches,
)
from sentinela.real_signals.orchestrator import _pipeline_with_eligibility, run_real_signals

NOW = datetime(2026, 8, 11, 18, tzinfo=timezone.utc)


def settings(**changes):
    return replace(RealSignalSettings.from_env(), **changes)


class Response:
    def __init__(self, payload=None, *, text="", status=200):
        self.payload = payload
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://source.test?secret=hidden")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("secret external message", request=request, response=response)

    def json(self):
        return self.payload


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, Response) else Response(response)


def coops_station(product="water_level", **changes):
    values = {
        "id": "8724580", "name": "Key West, FL", "latitude": 24.5557,
        "longitude": -81.8079, "products": (product,), "datum": "MLLW",
    }
    values.update(changes)
    return CoopsStation(**values)


def coops_payload(values, key="data"):
    return {
        "metadata": {"id": "8724580", "name": "Key West", "lat": "24.5557", "lon": "-81.8079"},
        key: [{"t": timestamp, "v": str(value), "f": "0,0,0"} for timestamp, value in values],
    }


def collect_coops(payload, station=None, **changes):
    configured = settings(
        coops_stations=(station or coops_station(),),
        coops_water_level_threshold_m=1.0,
        coops_current_threshold_ms=1.0,
        coops_temp_anomaly_c=3.0,
        **changes,
    )
    return NoaaCoopsCollector(configured, Client([payload])).collect(NOW)


def test_coops_water_level_acima_do_threshold():
    result = collect_coops(coops_payload([("2026-08-11 17:00", 1.2)]))
    event = result.events[0]
    assert event.category == "coastal_water_level_anomaly"
    assert "Nivel d'agua elevado" in event.title
    assert event.evidence[0]["station_id"] == "8724580"
    assert event.evidence[0]["datum"] == "MLLW"
    assert event.evidence[0]["observed_value"] == 1.2


def test_coops_water_level_abaixo_do_threshold():
    result = collect_coops(coops_payload([("2026-08-11 17:00", 0.9)]))
    assert result.events == ()


def test_coops_corrente_forte_converte_cm_s_para_m_s():
    station = coops_station("currents", id="cb1401", name="Newport News", current_bin=30)
    payload = {
        "metadata": {"id": "cb1401", "name": "Newport News", "lat": "36.9", "lon": "-76.4"},
        "data": [{"t": "2026-08-11 17:00", "s": "125.0", "d": "160", "b": "30"}],
    }
    result = collect_coops(payload, station)
    assert result.events[0].category == "strong_tidal_current"
    assert result.events[0].evidence[0]["observed_value"] == 1.25


def test_coops_temperatura_exige_baseline_explicito():
    station = coops_station("water_temperature")
    result = collect_coops(coops_payload([("2026-08-11 17:00", 31.0)]), station)
    assert result.events == ()
    assert "baseline_ausente" in result.notice


def test_coops_temperatura_com_baseline_configurado():
    station = coops_station("water_temperature", temperature_baseline_c=26.0)
    result = collect_coops(coops_payload([("2026-08-11 17:00", 30.0)]), station)
    assert result.events[0].category == "coastal_temperature_anomaly"
    assert result.events[0].evidence[0]["temperature_baseline_c"] == 26.0


def test_coops_station_invalida_e_erro_http_sanitizado():
    result = NoaaCoopsCollector(
        settings(coops_stations=(coops_station(id="invalid"),)), Client([Response({}, status=400)]),
    ).collect(NOW)
    assert result.events == ()
    assert result.notice == "falhas parciais: invalid/water_level=HTTP 400"
    assert "secret" not in result.notice


def test_coops_produto_ausente_e_lote_vazio():
    result = collect_coops({"metadata": {"id": "8724580"}})
    assert result.received == 0
    assert result.events == ()


def test_coops_vento_e_preservado_somente_como_contexto():
    station = coops_station("wind")
    payload = {
        "metadata": {"id": "8724580"},
        "data": [{"t": "2026-08-11 17:00", "s": "12.5", "d": "90", "g": "15.0"}],
    }
    result = collect_coops(payload, station)
    assert result.events == ()
    assert result.details[0]["value"] == 12.5
    assert result.details[0]["unit"] == "m/s"


def test_coops_idempotencia_e_nova_revisao_na_mesma_janela():
    first = collect_coops(coops_payload([("2026-08-11 17:00", 1.2)]))
    same = collect_coops(coops_payload([("2026-08-11 17:00", 1.2)]))
    revised = collect_coops(coops_payload([("2026-08-11 17:06", 1.3)]))
    assert first.events[0].id == same.events[0].id
    assert first.events[0].id != revised.events[0].id
    assert first.events[0].primary_claim_id is None
    assert first.events[0].evidence[0]["canonical_group_id"] == revised.events[0].evidence[0]["canonical_group_id"]


def ndbc_text(rows):
    header = "#YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE"
    units = "#yr mo dy hr mn degT m/s m/s m sec sec degT hPa degC degC degC nmi hPa ft"
    return "\n".join((header, units, *rows))


def ndbc_row(timestamp="2026 08 11 17 20", *, wspd="6.0", gst="8.0", wvht="1.0", dpd="8", apd="5.0", mwd="90", pres="1016.0", wtmp="29.0"):
    return f"{timestamp} 90 {wspd} {gst} {wvht} {dpd} {apd} {mwd} {pres} 28.0 {wtmp} 24.0 MM MM MM"


def ndbc_station(identifier="41013", name="Frying Pan Shoals, NC", latitude=33.436, longitude=-77.764):
    return NdbcStation(identifier, name, latitude, longitude)


def collect_ndbc(rows, stations=None, responses=None, **changes):
    configured = settings(
        ndbc_stations=stations or (ndbc_station(),),
        ndbc_wave_height_threshold_m=3.0,
        ndbc_swell_period_threshold_s=14.0,
        ndbc_wind_threshold_ms=17.2,
        **changes,
    )
    client = Client(responses or [Response(text=ndbc_text(rows))])
    return NoaaNdbcCollector(configured, client).collect(NOW)


def test_ndbc_wave_height_alta_preserva_variaveis():
    result = collect_ndbc([ndbc_row(wvht="3.5", dpd="10", apd="7.0", mwd="120", wtmp="25.0")])
    event = next(event for event in result.events if event.category == "high_wave_observation")
    assert event.evidence[0]["significant_wave_height"] == 3.5
    assert event.evidence[0]["average_wave_period"] == 7.0
    assert event.evidence[0]["wave_direction"] == 120.0
    assert "risco" not in event.summary.lower()


def test_ndbc_long_period_swell_sem_afirmar_ressaca():
    result = collect_ndbc([ndbc_row(dpd="15")])
    event = next(event for event in result.events if event.category == "long_period_swell_observation")
    assert "nao afirma ressaca" in event.summary
    assert "wave_period" in event.keywords
    assert "swell" not in event.keywords
    assert "marine_forecast" not in event.keywords


def test_ndbc_vento_forte_por_variavel():
    result = collect_ndbc([ndbc_row(wspd="18", gst="20")])
    events = [event for event in result.events if event.category == "strong_marine_wind_observation"]
    assert len(events) == 2
    assert {event.evidence[0]["variable"] for event in events} == {"wind_speed", "wind_gust"}


def test_ndbc_missing_values_e_dados_ausentes():
    result = collect_ndbc([ndbc_row(wvht="MM", dpd="MM", wspd="MM", gst="MM", wtmp="MM")])
    assert result.events == ()
    assert result.discarded > 0


def test_ndbc_station_distinta_e_janela_distinta():
    stations = (ndbc_station("a", "A"), ndbc_station("b", "B"))
    text_a = ndbc_text([ndbc_row("2026 08 11 11 20", wvht="3.5"), ndbc_row("2026 08 11 17 20", wvht="3.6")])
    text_b = ndbc_text([ndbc_row("2026 08 11 17 20", wvht="3.7")])
    result = collect_ndbc([], stations=stations, responses=[Response(text=text_a), Response(text=text_b)])
    waves = [event for event in result.events if event.category == "high_wave_observation"]
    assert len(waves) == 3
    assert len({event.id for event in waves}) == 3
    assert len({event.evidence[0]["canonical_group_id"] for event in waves}) == 2


def test_ndbc_lote_vazio_e_erro_sanitizado():
    empty = collect_ndbc([], responses=[Response(text=ndbc_text([]))])
    failed = collect_ndbc([], responses=[Response(status=503)])
    assert empty.received == 0 and empty.events == ()
    assert failed.notice == "falhas parciais: 41013=HTTP 503"
    assert "secret" not in failed.notice


def test_ndbc_idempotencia():
    first = collect_ndbc([ndbc_row(wvht="3.5")])
    second = collect_ndbc([ndbc_row(wvht="3.8")])
    first_wave = next(event for event in first.events if event.category == "high_wave_observation")
    second_wave = next(event for event in second.events if event.category == "high_wave_observation")
    assert first_wave.id == second_wave.id
    assert first_wave.primary_claim_id is None
    assert first_wave.evidence[0]["canonical_group_id"] == second_wave.evidence[0]["canonical_group_id"]


def test_possible_forecast_observation_match_nao_funde_identidades():
    observed = collect_ndbc([ndbc_row(wvht="3.5")]).events[0]
    forecast = _event(
        event_type="marine_high_waves_forecast", source="Open-Meteo Marine",
        product="marine-forecast", region="nearby", window="2026-08-11T12:00:00+00:00",
        title="Previsao", summary="Previsao", occurred_at=datetime(2026, 8, 11, 17, tzinfo=timezone.utc),
        evidence={"latitude": 33.5, "longitude": -77.8}, keywords=["wave_height"],
        entities=[], scientific_area="oceanography", evidence_text="wave_height",
    )
    matches = possible_forecast_observation_matches((observed,), (forecast,))
    assert matches[0]["kind"] == "possible_forecast_observation_match"
    assert matches[0]["ndbc_event_id"] != matches[0]["openmeteo_marine_event_id"]
    assert observed.evidence[0]["canonical_group_id"] != forecast.evidence[0]["canonical_group_id"]


def test_possible_match_exige_fenomeno_compativel():
    observed = collect_ndbc([ndbc_row(wvht="3.5")]).events[0]
    swell_forecast = _event(
        event_type="marine_high_swell_forecast", source="Open-Meteo Marine",
        product="marine-forecast", region="nearby", window="2026-08-11T12:00:00+00:00",
        title="Previsao", summary="Previsao", occurred_at=datetime(2026, 8, 11, 17, tzinfo=timezone.utc),
        evidence={"latitude": 33.5, "longitude": -77.8}, keywords=["swell", "marine_forecast"],
        entities=[], scientific_area="oceanography", evidence_text="swell",
    )
    assert possible_forecast_observation_matches((observed,), (swell_forecast,)) == ()


def test_noaa_falha_parcial_nao_interrompe_outra_estacao():
    stations = (ndbc_station("a", "A"), ndbc_station("b", "B"))
    result = collect_ndbc(
        [], stations=stations,
        responses=[Response(status=500), Response(text=ndbc_text([ndbc_row(wvht="3.5")]))],
    )
    assert len(result.events) == 1
    assert "a=HTTP 500" in result.notice


def test_regiao_oceanografica_sem_fenomeno_e_bloqueada():
    event = _event(
        event_type="generic_regional_observation", source="Fonte",
        product="generic", region="south_atlantic", window="2026-08-11",
        title="Observacao regional", summary="Observacao no South Atlantic.",
        occurred_at=NOW, evidence={"region": "south_atlantic"},
        keywords=["south_atlantic"], entities=[{"name": "South Atlantic", "type": "region"}],
        scientific_area="geology", evidence_text="south_atlantic",
    )
    signals, _, eligible = _pipeline_with_eligibility((event,), settings())
    assert signals[0].relevance_score > 0
    assert eligible == ()


def test_sea_surface_temperature_factual_e_tematicamente_elegivel():
    station = coops_station("water_temperature", temperature_baseline_c=26.0)
    result = collect_coops(coops_payload([("2026-08-11 17:00", 30.0)]), station)
    signals, unmatched, eligible = _pipeline_with_eligibility(result.events, settings())
    assert "sea_surface_temperature" not in unmatched
    assert signals[0].relevance_score > 0
    assert eligible == (signals[0].id,)
    assert "marine_forecast" not in result.events[0].keywords


def test_ndbc_wave_height_direto_tem_contribuicao_tematica():
    result = collect_ndbc([ndbc_row(wvht="3.5")])
    event = next(event for event in result.events if event.category == "high_wave_observation")
    signals, unmatched, eligible = _pipeline_with_eligibility((event,), settings())
    assert "wave_height" not in unmatched
    assert signals[0].relevance_score > 0
    assert eligible == (signals[0].id,)
    assert any("canal concept" in reason and "wave_height" in reason for reason in signals[0].reasons)
    assert "marine_forecast" not in event.keywords


def test_ndbc_wave_period_direto_tem_contribuicao_tematica():
    result = collect_ndbc([ndbc_row(dpd="15")])
    event = next(event for event in result.events if event.category == "long_period_swell_observation")
    signals, unmatched, eligible = _pipeline_with_eligibility((event,), settings())
    assert "wave_period" not in unmatched
    assert eligible == (signals[0].id,)
    assert any("canal concept" in reason and "wave_period" in reason for reason in signals[0].reasons)


def test_marine_forecast_sozinho_tem_contribuicao_direta_pequena():
    event = _event(
        event_type="marine_context_forecast", source="Open-Meteo Marine",
        product="marine-forecast", region="outside", window="2026-08-11",
        title="Previsao maritima", summary="Previsao maritima factual.",
        occurred_at=NOW, evidence={"latitude": 0, "longitude": 0},
        keywords=["marine_forecast"], entities=[], scientific_area="oceanography",
        evidence_text="marine_forecast",
    )
    signals, unmatched, eligible = _pipeline_with_eligibility((event,), settings())
    assert "marine_forecast" not in unmatched
    assert 0 < signals[0].relevance_score < 0.1
    assert eligible == (signals[0].id,)


def test_southern_africa_sem_fenomeno_nao_fica_elegivel():
    event = _event(
        event_type="generic_regional_observation", source="Fonte",
        product="generic", region="southern_africa", window="2026-08-11",
        title="Observacao regional", summary="Observacao em Southern Africa.",
        occurred_at=NOW, evidence={"region": "southern_africa"},
        keywords=["southern_africa"], entities=[{"name": "Southern Africa", "type": "region"}],
        scientific_area="geology", evidence_text="southern_africa",
    )
    signals, _, eligible = _pipeline_with_eligibility((event,), settings())
    assert eligible == ()


def test_coops_observado_nao_recebe_marine_forecast():
    result = collect_coops(coops_payload([("2026-08-11 17:00", 1.2)]))
    assert result.events[0].keywords == ["water_level"]


def test_cli_aceita_fontes_noaa_e_all():
    assert _parser().parse_args(["--dry-run", "--source", "noaa-coops"]).source == "noaa-coops"
    assert _parser().parse_args(["--dry-run", "--source", "noaa-ndbc"]).source == "noaa-ndbc"
    assert _parser().parse_args(["--dry-run", "--source", "all"]).source == "all"


def test_orquestrador_source_all_isola_falhas_e_reporta_match():
    observed = collect_ndbc([ndbc_row(wvht="3.5")])
    forecast = _event(
        event_type="marine_high_waves_forecast", source="Open-Meteo Marine",
        product="marine-forecast", region="nearby", window="2026-08-11T12:00:00+00:00",
        title="Previsao", summary="Previsao", occurred_at=datetime(2026, 8, 11, 17, tzinfo=timezone.utc),
        evidence={"latitude": 33.5, "longitude": -77.8}, keywords=["wave_height"],
        entities=[], scientific_area="oceanography", evidence_text="wave_height",
    )

    class Fixed:
        def __init__(self, result):
            self.result = result

        def collect(self, now):
            return self.result

    run = run_real_signals(
        settings=settings(), sources=("noaa-coops", "noaa-ndbc", "openmeteo-marine"),
        now=NOW, collectors={
            "noaa-coops": Fixed(CollectionResult(source="noaa-coops", error="HTTP 500")),
            "noaa-ndbc": Fixed(observed),
            "openmeteo-marine": Fixed(CollectionResult(source="openmeteo_marine", events=(forecast,))),
        },
    )
    ndbc = next(item for item in run.collections if item.source == "noaa-ndbc")
    assert "possible_forecast_observation_matches=1" in ndbc.notice
    assert ndbc.details[-1]["kind"] == "possible_forecast_observation_match"
    assert len(run.events) == 2


def test_ndbc_consulta_marine_como_fonte_auxiliar():
    observed = collect_ndbc([ndbc_row(wvht="3.5")])

    class Fixed:
        def __init__(self, result):
            self.result = result

        def collect(self, now):
            return self.result

    run = run_real_signals(
        settings=settings(), sources=("noaa-ndbc",), now=NOW,
        collectors={
            "noaa-ndbc": Fixed(observed),
            "openmeteo-marine": Fixed(CollectionResult(source="openmeteo_marine")),
        },
    )

    assert run.result.consulted_sources == ("noaa-ndbc", "openmeteo-marine")
    assert run.result.supporting_sources == ("openmeteo-marine",)
    assert all(event.supporting_sources == ("openmeteo-marine",) for event in run.events)
