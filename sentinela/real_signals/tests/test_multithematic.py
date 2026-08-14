from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from sentinela.core.models import EventStatus
from sentinela.real_signals.config import ForecastLocation, RealSignalSettings
from sentinela.real_signals.multithematic import (
    DonkiCollector, OpenMeteoMarineCollector, OpenMeteoWeatherCollector,
    UsgsCollector,
)
from sentinela.real_signals.collectors import _event
from sentinela.real_signals.orchestrator import _pipeline_with_eligibility, run_real_signals

NOW = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)


def settings(**changes):
    return replace(RealSignalSettings.from_env(), **changes)


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://source.test")
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


def usgs_feature(identifier="us7000test", magnitude=5.2, updated=1785848400000, coordinates=None, status="reviewed"):
    return {
        "type": "Feature",
        "id": identifier,
        "properties": {
            "mag": magnitude, "magType": "mww", "place": "100 km ao sul de Teste",
            "time": 1785844800000, "updated": updated, "status": status,
            "type": "earthquake",
            "tsunami": 1, "alert": None, "sig": 420,
            "detail": f"https://earthquake.usgs.gov/detail/{identifier}.geojson",
            "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{identifier}",
        },
        "geometry": {"type": "Point", "coordinates": coordinates or [-20.0, -25.0, 12.4]},
    }


def test_usgs_acima_do_threshold():
    result = UsgsCollector(settings(), Client([{"features": [usgs_feature()]}])).collect(NOW)
    assert result.received == 1
    assert len(result.events) == 1
    event = result.events[0]
    assert event.category == "earthquake_detected"
    assert "magnitude 5.2" in event.title
    assert "não implica" in event.summary
    assert event.evidence[0]["tsunami"] == 1
    assert event.event_status is EventStatus.OBSERVED_FACT


def test_usgs_abaixo_do_threshold():
    result = UsgsCollector(settings(), Client([{"features": [usgs_feature(magnitude=4.0)]}])).collect(NOW)
    assert result.events == ()
    assert result.discarded == 1


def test_usgs_revisao_mantem_grupo_e_muda_evento():
    first = UsgsCollector(settings(), Client([{"features": [usgs_feature(updated=1785848400000)]}])).collect(NOW)
    second = UsgsCollector(settings(), Client([{"features": [usgs_feature(updated=1785852000000)]}])).collect(NOW)
    assert first.events[0].id != second.events[0].id
    assert first.events[0].primary_claim_id is None
    assert second.events[0].primary_claim_id is None
    assert (
        first.events[0].evidence[0]["canonical_group_id"]
        == second.events[0].evidence[0]["canonical_group_id"]
    )


def test_usgs_eventos_distintos_nao_agrupam():
    result = UsgsCollector(settings(), Client([{"features": [usgs_feature("a"), usgs_feature("b")]}])).collect(NOW)
    assert len(result.events) == 2
    assert (
        result.events[0].evidence[0]["canonical_group_id"]
        != result.events[1].evidence[0]["canonical_group_id"]
    )


def test_usgs_sem_coordenadas():
    feature = usgs_feature()
    feature["geometry"]["coordinates"] = []
    result = UsgsCollector(settings(), Client([{"features": [feature]}])).collect(NOW)
    assert result.events == ()
    assert result.discarded == 1


def test_usgs_descarta_evento_que_nao_e_terremoto():
    feature = usgs_feature()
    feature["properties"]["type"] = "quarry blast"
    result = UsgsCollector(settings(), Client([{"features": [feature]}])).collect(NOW)
    assert result.events == ()


def test_usgs_erro_http_sanitizado():
    result = UsgsCollector(settings(), Client([Response({}, 401)])).collect(NOW)
    assert result.events == ()
    assert result.error == "HTTPStatusError: falha na consulta USGS"
    assert "secret" not in result.error


def test_usgs_lote_vazio():
    result = UsgsCollector(settings(), Client([{"features": []}])).collect(NOW)
    assert result.received == 0
    assert result.events == ()


def test_usgs_request_tem_limites_e_tipo():
    client = Client([{"features": []}])
    UsgsCollector(settings(), client).collect(NOW)
    params = client.calls[0][1]["params"]
    assert params["eventtype"] == "earthquake"
    assert params["endtime"] == NOW.isoformat()


def test_usgs_local_geografico_nao_cria_elegibilidade_tematica():
    feature = usgs_feature()
    feature["properties"]["place"] = "55 km NW de Teste, Iran"
    result = UsgsCollector(settings(), Client([{"features": [feature]}])).collect(NOW)
    run = run_real_signals(
        settings=settings(), sources=("usgs",), now=NOW,
        collectors={"usgs": type("Fixed", (), {"collect": lambda self, now: result})()},
    )
    assert run.signals[0].relevance_score > 0
    assert run.eligible_signal_ids == ()


def hourly_payload(**variables):
    times = [f"2026-08-04T{hour:02d}:00" for hour in range(12, 24)]
    base = {
        "temperature_2m": [20.0] * 12,
        "precipitation": [0.0] * 12,
        "wind_speed_10m": [10.0] * 12,
        "wind_gusts_10m": [20.0] * 12,
        "surface_pressure": [1010.0] * 12,
        "visibility": [10000.0] * 12,
    }
    base.update(variables)
    return {
        "latitude": -20.3, "longitude": -40.3,
        "hourly": {"time": times, **base},
        "hourly_units": {
            "temperature_2m": "°C", "precipitation": "mm",
            "wind_speed_10m": "km/h", "wind_gusts_10m": "km/h",
            "surface_pressure": "hPa", "visibility": "m",
        },
    }


def weather_settings(**changes):
    return settings(
        weather_locations=(ForecastLocation("vitoria_es", "Vitória", -20.3155, -40.3128),),
        **changes,
    )


def weather_result(payload, configured=None):
    return OpenMeteoWeatherCollector(configured or weather_settings(), Client([payload])).collect(NOW)


def test_weather_vento_acima():
    gusts = [20.0, 80.0, 75.0, 20.0, 20.0, 20.0] + [20.0] * 6
    result = weather_result(hourly_payload(wind_gusts_10m=gusts))
    events = [event for event in result.events if event.category == "weather_strong_wind_forecast"]
    assert len(events) == 1
    assert "80" in events[0].summary


def test_weather_chuva_acima():
    result = weather_result(hourly_payload(precipitation=[35.0] + [0.0] * 11))
    assert any(event.category == "weather_heavy_precipitation_forecast" for event in result.events)


def test_weather_temperatura_extrema():
    result = weather_result(hourly_payload(temperature_2m=[42.0] + [20.0] * 11))
    assert any(event.category == "weather_extreme_temperature_forecast" for event in result.events)


def test_weather_visibilidade_baixa():
    result = weather_result(hourly_payload(visibility=[2500.0] + [10000.0] * 11))
    event = next(event for event in result.events if event.category == "weather_low_visibility_forecast")
    assert event.event_status is EventStatus.FORECAST


def test_weather_abaixo_dos_limites():
    result = weather_result(hourly_payload())
    assert result.events == ()


def test_weather_agrupa_seis_horas():
    gusts = [80.0] * 6 + [90.0] * 6
    result = weather_result(hourly_payload(wind_gusts_10m=gusts))
    events = [event for event in result.events if event.category == "weather_strong_wind_forecast"]
    assert len(events) == 3
    assert len({event.id for event in events}) == 3


def test_weather_resposta_incompleta():
    payload = hourly_payload()
    del payload["hourly"]["visibility"]
    result = weather_result(payload)
    assert result.events == ()
    assert result.discarded > 0


def test_weather_erro_parcial():
    configured = settings(weather_locations=(
        ForecastLocation("a", "A", 0, 0), ForecastLocation("b", "B", 1, 1),
    ))
    client = Client([httpx.ConnectError("offline"), hourly_payload(wind_gusts_10m=[80.0] + [20.0] * 11)])
    result = OpenMeteoWeatherCollector(configured, client).collect(NOW)
    assert result.notice == "falhas parciais em 1 local(is)"
    assert len(result.events) == 1


def marine_payload(**variables):
    times = [f"2026-08-04T{hour:02d}:00" for hour in range(12, 24)]
    base = {
        "wave_height": [1.0] * 12, "wave_direction": [120.0] * 12,
        "wave_period": [8.0] * 12, "wind_wave_height": [0.5] * 12,
        "swell_wave_height": [1.0] * 12,
        "ocean_current_velocity": [1.2] * 12,
        "sea_surface_temperature": [24.0] * 12,
    }
    base.update(variables)
    return {
        "hourly": {"time": times, **base},
        "hourly_units": {
            "wave_height": "m", "wave_direction": "°", "wave_period": "s",
            "wind_wave_height": "m", "swell_wave_height": "m",
            "ocean_current_velocity": "km/h", "sea_surface_temperature": "°C",
        },
    }


def marine_settings(**changes):
    return settings(
        marine_locations=(ForecastLocation("espirito_santo_coast", "costa do Espírito Santo", -20.5, -39.5),),
        **changes,
    )


def marine_result(payload, configured=None):
    return OpenMeteoMarineCollector(configured or marine_settings(), Client([payload])).collect(NOW)


def test_marine_onda_acima():
    result = marine_result(marine_payload(wave_height=[3.5] + [1.0] * 11))
    event = next(event for event in result.events if event.category == "marine_high_waves_forecast")
    assert event.evidence[0]["ocean_current_velocity"] == 1.2
    assert event.evidence[0]["sea_surface_temperature"] == 24.0
    assert event.event_status is EventStatus.FORECAST


def test_marine_swell_acima():
    result = marine_result(marine_payload(swell_wave_height=[2.8] + [1.0] * 11))
    assert any(event.category == "marine_high_swell_forecast" for event in result.events)


def test_marine_periodo_longo():
    result = marine_result(marine_payload(wave_period=[15.0] + [8.0] * 11))
    assert any(event.category == "marine_long_period_swell_forecast" for event in result.events)


def test_marine_abaixo_limites():
    assert marine_result(marine_payload()).events == ()


def test_marine_variavel_ausente():
    payload = marine_payload()
    del payload["hourly"]["swell_wave_height"]
    result = marine_result(payload)
    assert result.events == ()
    assert result.discarded > 0


def test_marine_agrupamento():
    result = marine_result(marine_payload(wave_height=[3.5] * 12))
    events = [event for event in result.events if event.category == "marine_high_waves_forecast"]
    assert len(events) == 2


def test_marine_erro_parcial():
    configured = settings(marine_locations=(
        ForecastLocation("a", "A", 0, 0), ForecastLocation("b", "B", 1, 1),
    ))
    client = Client([httpx.ConnectError("offline"), marine_payload(wave_height=[3.5] + [1.0] * 11)])
    result = OpenMeteoMarineCollector(configured, client).collect(NOW)
    assert result.notice == "falhas parciais em 1 local(is)"
    assert len(result.events) == 1


def test_marine_fingerprints_somente_com_fenomenos_sustentados():
    payload = marine_payload(
        wave_height=[3.5] + [1.0] * 11,
        swell_wave_height=[2.8] + [1.0] * 11,
        wave_period=[15.0] + [8.0] * 11,
    )
    result = marine_result(payload)
    expected = {
        "marine_high_waves_forecast": ["wave_height", "marine_forecast"],
        "marine_high_swell_forecast": ["swell", "marine_forecast"],
        "marine_long_period_swell_forecast": ["wave_period", "marine_forecast"],
    }
    for event in result.events:
        assert event.keywords == expected[event.category]
        assert "ocean_current" not in event.keywords
        assert "sea_surface_temperature" not in event.keywords


def test_marine_fenomenos_diretos_ficam_elegiveis_sem_excecao():
    result = marine_result(marine_payload(wave_height=[3.5] + [1.0] * 11))
    signals, unmatched, eligible = _pipeline_with_eligibility(result.events, settings())
    assert "wave_height" not in unmatched
    assert "marine_forecast" not in unmatched
    assert len(signals) == len(eligible) == 1
    assert any("canal concept" in reason and "wave_height" in reason for reason in signals[0].reasons)


def donki_row(endpoint, identifier="2026-01"):
    id_field = {"CME": "activityID", "FLR": "flrID", "GST": "gstID", "SEP": "sepID", "IPS": "activityID"}[endpoint]
    time_field = {"CME": "startTime", "FLR": "beginTime", "GST": "startTime", "SEP": "eventTime", "IPS": "eventTime"}[endpoint]
    row = {
        id_field: identifier, time_field: "2026-08-03T10:00Z",
        "sourceLocation": "S10W20", "activeRegionNum": 12345,
        "linkedEvents": [{"activityID": "linked-1"}],
        "instruments": [{"displayName": "Instrument"}],
        "catalog": "M2M_CATALOG", "note": "Nota factual", "link": "https://kauai.ccmc.gsfc.nasa.gov/DONKI/view/test",
    }
    if endpoint == "CME":
        row["cmeAnalyses"] = [{"speed": 700, "type": "C"}]
    if endpoint == "FLR":
        row["classType"] = "M1.2"
    return row


def donki_result(overrides=None, key="DEMO_KEY"):
    overrides = overrides or {}
    responses = []
    for endpoint in ("CME", "FLR", "GST", "SEP", "IPS"):
        responses.append(overrides.get(endpoint, [donki_row(endpoint, f"{endpoint}-1")]))
    configured = settings(donki_api_key=key)
    client = Client(responses)
    return DonkiCollector(configured, client).collect(NOW), client


def test_donki_cme():
    result, _ = donki_result({"FLR": [], "GST": [], "SEP": [], "IPS": []})
    event = result.events[0]
    assert event.category == "coronal_mass_ejection_detected"
    assert event.evidence[0]["speed"] == 700
    assert event.event_status is EventStatus.CATALOG_RECORD
    assert "não implica impacto" in event.summary
    assert event.evidence[0]["cme_analyses"] == [{"speed": 700, "type": "C"}]


def test_donki_flare():
    result, _ = donki_result({"CME": [], "GST": [], "SEP": [], "IPS": []})
    assert result.events[0].title == "Explosão solar classe M1.2 registrada"
    assert result.events[0].evidence[0]["class_type"] == "M1.2"


def test_donki_tempestade_geomagnetica():
    result, _ = donki_result({"CME": [], "FLR": [], "SEP": [], "IPS": []})
    assert result.events[0].category == "geomagnetic_storm_detected"


def test_donki_sep_e_ips_usam_event_time():
    result, _ = donki_result({"CME": [], "FLR": [], "GST": []})
    assert {event.category for event in result.events} == {
        "solar_energetic_particle_event", "interplanetary_shock_detected",
    }


def test_donki_evento_duplicado():
    duplicate = donki_row("CME", "same")
    result, _ = donki_result({"CME": [duplicate, duplicate], "FLR": [], "GST": [], "SEP": [], "IPS": []})
    assert len(result.events) == 1
    assert result.duplicates == 1


def test_donki_linked_events_preservados():
    result, _ = donki_result({"FLR": [], "GST": [], "SEP": [], "IPS": []})
    assert result.events[0].evidence[0]["linked_events"] == [{"activityID": "linked-1"}]
    assert len(result.events) == 1


def test_donki_campos_opcionais_ausentes():
    row = {"activityID": "CME-min", "startTime": "2026-08-03T10:00Z"}
    result, _ = donki_result({"CME": [row], "FLR": [], "GST": [], "SEP": [], "IPS": []})
    assert len(result.events) == 1
    assert result.events[0].evidence[0]["speed"] is None


def test_donki_demo_key_enviado_sem_impressao():
    _, client = donki_result()
    assert all(call[1]["params"]["api_key"] == "DEMO_KEY" for call in client.calls)


def test_donki_erro_sanitizado():
    responses = [Response({}, 403)] * 5
    result = DonkiCollector(settings(donki_api_key="secret-key"), Client(responses)).collect(NOW)
    assert result.events == ()
    assert result.notice == "falhas parciais: CME=HTTP 403, FLR=HTTP 403, GST=HTTP 403, SEP=HTTP 403, IPS=HTTP 403"
    assert "secret-key" not in str(result)


def test_donki_usa_fallback_oficial_ccmc_em_rate_limit():
    responses = [Response({}, 429), [donki_row("CME")], [], [], [], []]
    client = Client(responses)
    result = DonkiCollector(settings(donki_api_key="DEMO_KEY"), client).collect(NOW)
    assert len(result.events) == 1
    assert result.notice == "fallback oficial CCMC: CME"
    assert "/DONKI/WS/get/CME" in client.calls[1][0]
    assert "api_key" not in client.calls[1][1]["params"]


def test_donki_tempestade_preserva_kp_oficial():
    storm = donki_row("GST")
    storm["allKpIndex"] = [{"observedTime": "2026-08-03T12:00Z", "kpIndex": 6}]
    result, _ = donki_result({"CME": [], "FLR": [], "GST": [storm], "SEP": [], "IPS": []})
    assert result.events[0].evidence[0]["all_kp_index"][0]["kpIndex"] == 6


def test_donki_flare_classe_c24_preservada_sem_exagero():
    flare = donki_row("FLR")
    flare["classType"] = "C2.4"
    result, _ = donki_result({"CME": [], "FLR": [flare], "GST": [], "SEP": [], "IPS": []})
    event = result.events[0]
    assert "classe C2.4" in event.title
    assert "grande" not in (event.title + event.summary).lower()


def test_donki_cme_sem_evidencia_terrestre_nao_afirma_impacto():
    result, _ = donki_result({"FLR": [], "GST": [], "SEP": [], "IPS": []})
    summary = result.events[0].summary.lower()
    assert "ainda não implica impacto geomagnético na terra" in summary
    assert "atingirá a terra" not in summary


def test_donki_tipos_recebem_relevancia_elegibilidade_naturais():
    result, _ = donki_result()
    signals, unmatched, eligible = _pipeline_with_eligibility(result.events, settings())
    expected = {
        "coronal_mass_ejection_detected": "cme",
        "solar_flare_detected": "solar_flare",
        "geomagnetic_storm_detected": "geomagnetic_storm",
        "solar_energetic_particle_event": "solar_energetic_particles",
        "interplanetary_shock_detected": "interplanetary_shock",
    }
    assert len(signals) == len(eligible) == 5
    assert "interplanetary_shock" not in unmatched
    assert "solar_energetic_particles" not in unmatched
    event_by_id = {str(event.id): event for event in result.events}
    for signal in signals:
        event = event_by_id[signal.representative_event_id]
        concept = expected[event.category]
        assert concept in event.keywords
        assert signal.relevance_score > 0
        assert signal.id in eligible
        assert any(f"Conceito {concept}," in reason for reason in signal.reasons)


def test_evento_generico_fora_dos_interesses_permanece_baixo():
    event = _event(
        event_type="generic_space_observation", source="Fonte científica",
        product="generic", region="space", window="2026-08-04",
        title="Observação espacial genérica", summary="Observação factual genérica.",
        occurred_at=NOW, evidence={"source": "Fonte científica"},
        keywords=["unrelated_space_observation"], entities=[],
        scientific_area="astronomy", evidence_text="unrelated_space_observation",
    )
    signals, _, eligible = _pipeline_with_eligibility((event,), settings())
    assert signals[0].relevance_score == 0
    assert eligible == ()


def test_profile_climate_weather_preserva_linhas_e_pesos_anteriores():
    profile = yaml.safe_load((Path(__file__).parents[3] / "profiles" / "henrique_lobo.yaml").read_text())
    lines = {line["id"]: line for line in profile["research_lines"]}
    assert profile["researcher"] == {"id": "henrique_lobo", "name": "Henrique Lobo", "version": 6}
    assert profile["domains"] == {
        "atmospheric_science": 1.0, "remote_sensing": 0.9, "geopolitics": 0.02,
    }
    assert profile["concepts"] == {"mineral_dust": {"weight": 1.0}}
    assert [line["id"] for line in profile["research_lines"][:5]] == [
        "transatlantic_mineral_dust", "middle_east_geopolitics",
        "volcanology_monitoring", "space_weather_monitoring", "oceanography_monitoring",
    ]
    expected_hashes = {
        "transatlantic_mineral_dust": "d6d15f04be874fcb3de8c3e1ea742cdeac9bea9cae56ff1bf194ceeee3b083e5",
        "middle_east_geopolitics": "b280310880841f6bf7130da4c8f7f3fc7d1267a919cf916ef2e0ba0586ca9b26",
        "volcanology_monitoring": "e707b7e3b5751bb7e786c401983ac09e87c71af51b15e175ac7de1706f352326",
        "space_weather_monitoring": "1d9869dfd5e94793e72b4c4feec04d1e41c2d47397cdc38dd998d58faee12273",
        "oceanography_monitoring": "67dc06d24a3895002e2d70a78daf7a6a1231df9c496a481f07ee9e9eeaf8f593",
    }
    for line in profile["research_lines"][:5]:
        canonical = json.dumps(line, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        assert hashlib.sha256(canonical.encode()).hexdigest() == expected_hashes[line["id"]]
    assert lines["transatlantic_mineral_dust"] == {
        "id": "transatlantic_mineral_dust",
        "title": "Transporte transatlântico de poeira mineral",
        "description": "Investigar mecanismos, recorrência e evidências do transporte de poeira mineral da África para a América do Sul.\n",
        "question": "Existe transporte recorrente de poeira mineral da África Austral para o Sudeste do Brasil?\n",
        "priority": 1.0, "concepts": {"mineral_dust": 1.0},
        "regions": {"south_atlantic": 1.0},
        "instruments": {"calipso": 0.9, "modis": 0.9},
    }
    assert lines["middle_east_geopolitics"]["concepts"] == {
        "israel": 0.25, "middle_east": 0.10, "conflict": 0.25,
        "military_action": 0.25, "diplomacy": 0.20, "peace": 0.12,
        "ceasefire": 0.15, "iran": 0.15, "palestine": 0.15,
        "abraham_accords": 0.25,
    }
    assert lines["volcanology_monitoring"]["concepts"] == {
        "volcano": 0.02, "volcanic_activity": 0.08,
        "volcanic_alert": 0.18, "volcanic_eruption": 0.18,
        "volcanic_ash": 0.20,
    }
    assert lines["space_weather_monitoring"]["concepts"] == {
        "geomagnetic_storm": 0.30, "solar_flare": 0.17, "cme": 0.10,
        "interplanetary_shock": 0.22, "solar_energetic_particles": 0.22,
    }
    assert lines["oceanography_monitoring"]["priority"] == 0.70
    assert lines["oceanography_monitoring"]["concepts"] == {
        "wave_height": 0.18, "swell": 0.16, "wave_period": 0.12,
        "ocean_current": 0.10, "tide": 0.08, "water_level": 0.14,
        "sea_surface_temperature": 0.08, "marine_forecast": 0.05,
    }
    assert lines["climate_weather_monitoring"]["priority"] == 0.70
    assert lines["climate_weather_monitoring"]["concepts"] == {
        "extreme_temperature": 0.20, "heavy_precipitation": 0.18,
        "strong_wind": 0.14, "heatwave": 0.22, "drought": 0.12,
        "weather_alert": 0.18, "low_visibility": 0.08,
        "extreme_weather": 0.14,
    }


def test_donki_idempotencia_e_atualizacao_da_mesma_atividade():
    first_row = donki_row("CME", "CME-stable")
    updated_row = donki_row("CME", "CME-stable")
    updated_row["cmeAnalyses"] = [{"speed": 900, "type": "C"}]
    first, _ = donki_result({"CME": [first_row], "FLR": [], "GST": [], "SEP": [], "IPS": []})
    updated, _ = donki_result({"CME": [updated_row], "FLR": [], "GST": [], "SEP": [], "IPS": []})
    first_signal = _pipeline_with_eligibility(first.events, settings())[0][0]
    updated_signal = _pipeline_with_eligibility(updated.events, settings())[0][0]
    assert first.events[0].id != updated.events[0].id
    assert first.events[0].primary_claim_id is None
    assert first.events[0].evidence[0]["canonical_group_id"] == updated.events[0].evidence[0]["canonical_group_id"]
    assert first_signal.id == updated_signal.id


def test_integracao_multitematica_e_lacunas_taxonomicas():
    usgs = UsgsCollector(settings(), Client([{"features": [usgs_feature()]}])).collect(NOW)
    weather = weather_result(hourly_payload(wind_gusts_10m=[80.0] + [20.0] * 11))
    donki, _ = donki_result({"FLR": [], "GST": [], "SEP": [], "IPS": []})

    class Fixed:
        def __init__(self, result):
            self.result = result

        def collect(self, now):
            return self.result

    run = run_real_signals(
        settings=settings(), sources=("usgs", "openmeteo-weather", "donki"),
        now=NOW, collectors={
            "usgs": Fixed(usgs), "openmeteo-weather": Fixed(weather),
            "donki": Fixed(donki),
        },
    )
    assert len(run.events) == 3
    assert len(run.signals) == 3
    assert "strong_wind" not in run.unmatched_terms
    assert "weather_forecast" in run.unmatched_terms
