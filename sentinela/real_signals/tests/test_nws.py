from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from sentinela.core.models import EventStatus
from sentinela.cli.generate_real_signals import _parser
from sentinela.real_signals import RealSignalSettings
from sentinela.real_signals.nws import NWS_ALERTS_URL, NwsAlertsCollector
from sentinela.real_signals.orchestrator import _pipeline_with_eligibility

NOW = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


def settings(**changes):
    return replace(
        RealSignalSettings.from_env(),
        nws_user_agent="(sentinela-hl-tests, https://example.test/contact)",
        **changes,
    )


class Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload or {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.weather.gov")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("external secret", request=request, response=response)

    def json(self):
        return self.payload


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def alert(
    event="Extreme Heat Warning", identifier="urn:oid:alert-1",
    sent="2026-08-11T19:00:00Z", expires="2026-08-11T22:00:00Z",
    message_type="Alert", geometry=None, vtec="/O.NEW.KXXX.EH.W.0001.260811T1900Z-260811T2200Z/",
    references=None,
):
    return {
        "id": f"https://api.weather.gov/alerts/{identifier}",
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "@id": f"https://api.weather.gov/alerts/{identifier}",
            "id": identifier,
            "areaDesc": "Test County, TX",
            "geocode": {"SAME": ["048001"], "UGC": ["TXC001"]},
            "affectedZones": ["https://api.weather.gov/zones/county/TXC001"],
            "references": references or [],
            "sent": sent, "effective": sent, "onset": sent,
            "expires": expires, "ends": None,
            "status": "Actual", "messageType": message_type,
            "category": "Met", "severity": "Severe",
            "certainty": "Likely", "urgency": "Expected",
            "event": event, "senderName": "NWS Test Office",
            "headline": f"{event} issued by NWS Test Office",
            "description": "Official factual description.",
            "instruction": "Official instruction.",
            "parameters": {"VTEC": [vtec]} if vtec else {},
            "eventCode": {"NationalWeatherService": ["TST"]},
        },
    }


def collect(*features, response_status=200):
    client = Client(Response({"type": "FeatureCollection", "features": list(features)}, response_status))
    result = NwsAlertsCollector(settings(), client).collect(NOW)
    return result, client


def test_nws_alerta_valido_usa_endpoint_headers_e_identidade_oficial():
    result, client = collect(alert())
    assert len(result.events) == 1
    event = result.events[0]
    assert client.calls[0][0] == NWS_ALERTS_URL
    assert client.calls[0][1]["headers"] == {
        "User-Agent": "(sentinela-hl-tests, https://example.test/contact)",
        "Accept": "application/geo+json",
    }
    assert event.evidence[0]["official_alert_id"] == "urn:oid:alert-1"
    assert event.evidence[0]["stable_alert_id"] == "KXXX.EH.W.0001"
    assert event.evidence[0]["classification"] == "operational_weather_alert"
    assert event.event_status is EventStatus.OFFICIAL_ALERT
    assert event.keywords == ["weather_alert", "extreme_temperature", "heatwave"]
    assert "NOAA/NWS emitiu" in event.title


def test_nws_atualizacao_mantem_grupo_e_muda_evento():
    first = collect(alert())[0].events[0]
    updated = collect(alert(
        identifier="urn:oid:alert-2", sent="2026-08-11T19:30:00Z", message_type="Update",
        vtec="/O.CON.KXXX.EH.W.0001.260811T1900Z-260811T2200Z/",
        references=[{"identifier": "urn:oid:alert-1"}],
    ))[0].events[0]
    assert first.id != updated.id
    assert first.primary_claim_id == updated.primary_claim_id
    first_signal = _pipeline_with_eligibility((first,), settings())[0][0]
    updated_signal = _pipeline_with_eligibility((updated,), settings())[0][0]
    assert first_signal.id == updated_signal.id


def test_nws_alertas_distintos_com_mesmo_titulo_nao_agrupam():
    first = alert(vtec="/O.NEW.KXXX.EH.W.0001.260811T1900Z-260811T2200Z/")
    second = alert(
        identifier="urn:oid:alert-distinct",
        vtec="/O.NEW.KXXX.EH.W.0002.260811T1900Z-260811T2200Z/",
    )
    events = collect(first, second)[0].events
    assert len(events) == 2
    assert events[0].title == events[1].title
    assert events[0].primary_claim_id != events[1].primary_claim_id


def test_nws_alerta_expirado_e_fora_do_escopo_sao_descartados():
    expired = alert(expires="2026-08-11T19:59:00Z")
    outside = alert(event="Special Weather Statement", identifier="urn:oid:outside")
    result, _ = collect(expired, outside)
    assert result.events == ()
    assert result.discarded == 2


@pytest.mark.parametrize(
    ("official_type", "concept"),
    [
        ("Extreme Heat Warning", "heatwave"),
        ("Flood Warning", "extreme_weather"),
        ("High Wind Warning", "strong_wind"),
        ("Dense Fog Advisory", "low_visibility"),
    ],
)
def test_nws_fenomenos_diretos_ficam_elegiveis(official_type, concept):
    event = collect(alert(event=official_type))[0].events[0]
    signals, unmatched, eligible = _pipeline_with_eligibility((event,), settings())
    assert concept in event.keywords
    assert concept not in unmatched
    assert signals[0].relevance_score > 0
    assert eligible == (signals[0].id,)


def test_nws_alerta_sem_geometry_e_valido():
    event = collect(alert(event="Flash Flood Warning", geometry=None))[0].events[0]
    assert event.evidence[0]["geometry"] is None


def test_nws_erro_http_sanitizado():
    result, _ = collect(response_status=500)
    assert result.events == ()
    assert result.error == "HTTPStatusError: falha na consulta NOAA/NWS"
    assert "secret" not in result.error


def test_nws_idempotencia():
    first = collect(alert(event="Tornado Warning"))[0]
    second = collect(alert(event="Tornado Warning"))[0]
    assert first.events[0].id == second.events[0].id
    assert first.events[0].primary_claim_id == second.events[0].primary_claim_id


def test_openmeteo_weather_continua_previsao_e_nao_alerta_oficial():
    from sentinela.real_signals.tests.test_multithematic import hourly_payload, weather_result

    result = weather_result(hourly_payload(wind_gusts_10m=[80.0] + [20.0] * 11))
    event = next(event for event in result.events if event.category == "weather_strong_wind_forecast")
    signals, unmatched, eligible = _pipeline_with_eligibility((event,), settings())
    assert "Open-Meteo prevê" in event.summary
    assert "NOAA/NWS emitiu" not in event.summary
    assert "strong_wind" not in unmatched
    assert eligible == (signals[0].id,)


def test_cli_aceita_nws_alerts():
    assert _parser().parse_args(["--dry-run", "--source", "nws-alerts"]).source == "nws-alerts"
