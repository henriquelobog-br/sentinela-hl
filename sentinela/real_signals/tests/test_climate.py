from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, datetime, timezone

import httpx

from sentinela.core.models import EventStatus
from sentinela.cli.generate_real_signals import OPERATIONAL_SOURCES, _parser
from sentinela.real_signals import RealSignalSettings
from sentinela.real_signals.climate import CLIMATE_URL, OpenMeteoClimateCollector
from sentinela.real_signals.config import ForecastLocation
from sentinela.real_signals.orchestrator import _pipeline_with_eligibility, run_real_signals

NOW = datetime(2026, 8, 11, 20, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://climate.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("external", request=request, response=response)

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


def settings(**changes):
    values = {
        "climate_locations": (ForecastLocation("outside", "Região teste", 0, 0),),
        "climate_model": "EC_Earth3P_HR",
        "climate_baseline_start": "1991-01-01",
        "climate_baseline_end": "1991-12-31",
        "climate_target_start": "2040-01-01",
        "climate_target_end": "2040-12-31",
        "climate_temperature_anomaly_threshold_c": 2.0,
        "climate_precipitation_anomaly_threshold_fraction": 0.25,
        "climate_precipitation_anomaly_threshold_mm": 20.0,
        "climate_precipitation_min_baseline_mm": 20.0,
    }
    values.update(changes)
    return replace(RealSignalSettings.from_env(), **values)


def _month(year, month=1):
    return [date(year, month, day).isoformat() for day in range(1, calendar.monthrange(year, month)[1] + 1)]


def payload(*, baseline_temp=20.0, target_temp=20.0, baseline_precip=100.0, target_precip=100.0, baseline=True):
    baseline_times = _month(1991) if baseline else []
    target_times = _month(2040)
    times = baseline_times + target_times
    return {
        "latitude": 0, "longitude": 0,
        "daily_units": {"temperature_2m_mean": "°C", "precipitation_sum": "mm"},
        "daily": {
            "time": times,
            "temperature_2m_mean": [baseline_temp] * len(baseline_times) + [target_temp] * len(target_times),
            "precipitation_sum": (
                [baseline_precip / len(baseline_times)] * len(baseline_times) if baseline_times else []
            ) + [target_precip / len(target_times)] * len(target_times),
        },
    }


def period_payloads(data):
    times = data["daily"]["time"]
    baseline_indexes = [index for index, value in enumerate(times) if value.startswith("1991-")]
    target_indexes = [index for index, value in enumerate(times) if value.startswith("2040-")]

    def selected(indexes):
        return {
            **{key: value for key, value in data.items() if key != "daily"},
            "daily": {
                key: [values[index] for index in indexes]
                for key, values in data["daily"].items()
            },
        }

    return selected(baseline_indexes), selected(target_indexes)


def collect(data, configured=None):
    return OpenMeteoClimateCollector(configured or settings(), Client(period_payloads(data))).collect(NOW)


def test_climate_baseline_valido_preserva_metadados_e_request_oficial():
    data = payload(target_temp=23.0)
    client = Client(period_payloads(data))
    result = OpenMeteoClimateCollector(settings(), client).collect(NOW)
    event = next(event for event in result.events if event.category == "climate_temperature_anomaly")
    evidence = event.evidence[0]
    assert client.calls[0][0] == CLIMATE_URL
    assert client.calls[0][1]["params"]["daily"] == "temperature_2m_mean,precipitation_sum"
    assert evidence["baseline_start"] == "1991-01-01"
    assert evidence["baseline_end"] == "1991-12-31"
    assert evidence["target_period"] == "2040-01-01/2040-12-31"
    assert evidence["climatology_mean"] == 20.0
    assert evidence["projected_mean"] == 23.0
    assert evidence["anomaly"] == 3.0
    assert evidence["model"] == "EC_Earth3P_HR"
    assert evidence["source_semantics"] == "climate_model_projection_not_observation"
    assert evidence["classification"] == "climate_projection"
    assert evidence["operational_feed"] is False
    assert event.event_status is EventStatus.MODEL_PROJECTION


def test_climate_baseline_ausente_nao_cria_evento():
    result = collect(payload(target_temp=23.0, baseline=False))
    assert result.events == ()
    assert "series_sem_baseline_ou_modelo" in result.notice


def test_climate_temperatura_acima_e_abaixo():
    above = collect(payload(target_temp=23.0))
    below = collect(payload(target_temp=17.0))
    above_event = next(event for event in above.events if event.category == "climate_temperature_anomaly")
    below_event = next(event for event in below.events if event.category == "climate_temperature_anomaly")
    assert above_event.evidence[0]["anomaly"] == 3.0
    assert below_event.evidence[0]["anomaly"] == -3.0
    assert "modelada acima" in above_event.title
    assert "modelada abaixo" in below_event.title


def test_climate_precipitacao_acima_e_abaixo():
    above = collect(payload(target_precip=150.0))
    below = collect(payload(target_precip=50.0))
    above_event = next(event for event in above.events if event.category == "climate_precipitation_anomaly")
    below_event = next(event for event in below.events if event.category == "climate_precipitation_anomaly")
    assert round(above_event.evidence[0]["relative_anomaly"], 2) == 0.5
    assert round(below_event.evidence[0]["relative_anomaly"], 2) == -0.5
    assert "seca" not in (above_event.title + below_event.title).lower()


def test_climate_periodo_incompativel_e_modelo_ausente():
    overlap = collect(payload(), settings(climate_target_start="1991-01-01", climate_target_end="1991-12-31"))
    missing_model = collect(payload(), settings(climate_model=""))
    assert "incompatíveis" in overlap.error
    assert missing_model.error == "modelo climático ausente"


def test_climate_modelo_ausente_na_resposta():
    data = payload()
    del data["daily"]["temperature_2m_mean"]
    del data["daily"]["precipitation_sum"]
    result = collect(data)
    assert result.events == ()
    assert "series_sem_baseline_ou_modelo=2" in result.notice


def test_climate_rate_limit_tenta_novamente_sem_mudar_identidade():
    data = payload(target_temp=23.0)
    baseline, target = period_payloads(data)
    waits = []
    collector = OpenMeteoClimateCollector(
        settings(), Client([Response({}, 429), baseline, target]),
        sleeper=waits.append,
    )
    result = collector.collect(NOW)
    assert waits == [61]
    assert len(result.events) == 1


def test_climate_rate_limit_persistente_interrompe_lote():
    waits = []
    collector = OpenMeteoClimateCollector(
        settings(), Client([Response({}, 429), Response({}, 429)]),
        sleeper=waits.append,
    )
    result = collector.collect(NOW)
    assert waits == [61]
    assert result.events == ()
    assert result.notice == "falhas parciais: outside"


def test_climate_regiao_fora_do_perfil_permanece_bloqueada():
    result = collect(payload(target_temp=23.0))
    signals, _, eligible = _pipeline_with_eligibility(result.events, settings())
    assert signals
    assert eligible == ()


def test_climate_projection_continua_inelegivel_com_linha_operacional():
    result = collect(payload(target_temp=23.0, target_precip=150.0))
    signals, _, eligible = _pipeline_with_eligibility(result.events, settings())
    assert signals
    assert eligible == ()
    assert all(event.evidence[0]["classification"] == "climate_projection" for event in result.events)


def test_climate_relevancia_apenas_regional_e_bloqueada():
    configured = settings(climate_locations=(ForecastLocation("south_atlantic", "Atlântico Sul", -25, -20),))
    result = collect(payload(target_temp=23.0), configured)
    signals, _, eligible = _pipeline_with_eligibility(result.events, configured)
    assert signals[0].relevance_score > 0
    assert eligible == ()


def test_climate_idempotencia_e_agrupamento_mensal():
    first = collect(payload(target_temp=23.0, target_precip=150.0))
    second = collect(payload(target_temp=23.0, target_precip=150.0))
    assert [event.id for event in first.events] == [event.id for event in second.events]
    assert [event.primary_claim_id for event in first.events] == [event.primary_claim_id for event in second.events]
    assert len({event.primary_claim_id for event in first.events}) == 2


def test_climate_nao_declara_extremo_seca_ou_observacao():
    result = collect(payload(target_temp=23.0, target_precip=50.0))
    text = " ".join(event.title + " " + event.summary for event in result.events).lower()
    assert "onda de calor" not in text
    assert "evento extremo" not in text
    assert "seca" not in text
    assert "não de observação meteorológica" in text


def test_cli_permite_openmeteo_climate_explicito():
    assert _parser().parse_args(["--dry-run", "--source", "openmeteo-climate"]).source == "openmeteo-climate"
    assert "openmeteo-climate" not in OPERATIONAL_SOURCES

    class Fixed:
        def collect(self, now):
            return collect(payload(target_temp=23.0))

    run = run_real_signals(
        settings=settings(), sources=("openmeteo-climate",), now=NOW,
        collectors={"openmeteo-climate": Fixed()},
    )
    assert len(run.events) == 1
    assert run.collections[0].source == "openmeteo_climate"
