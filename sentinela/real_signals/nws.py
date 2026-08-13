"""Alertas meteorológicos ativos e oficiais NOAA/NWS."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from sentinela.core.models import EventStatus

from .collectors import CollectionResult, _dt, _event
from .config import RealSignalSettings

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

ALERT_RULES = {
    "Extreme Heat Warning": ("nws_extreme_heat_alert", ("weather_alert", "extreme_temperature", "heatwave")),
    "Heat Advisory": ("nws_heat_advisory", ("weather_alert", "extreme_temperature", "heatwave")),
    "Extreme Cold Warning": ("nws_extreme_cold_alert", ("weather_alert", "extreme_temperature")),
    "Cold Weather Advisory": ("nws_cold_weather_advisory", ("weather_alert", "extreme_temperature")),
    "Freeze Warning": ("nws_freeze_warning", ("weather_alert", "extreme_temperature")),
    "Winter Storm Warning": ("nws_winter_storm_warning", ("weather_alert", "extreme_weather")),
    "Flood Warning": ("nws_flood_warning", ("weather_alert", "extreme_weather")),
    "Flash Flood Warning": ("nws_flash_flood_warning", ("weather_alert", "extreme_weather")),
    "Severe Thunderstorm Warning": ("nws_severe_thunderstorm_warning", ("weather_alert", "extreme_weather")),
    "Tornado Warning": ("nws_tornado_warning", ("weather_alert", "extreme_weather")),
    "Hurricane Warning": ("nws_hurricane_warning", ("weather_alert", "extreme_weather", "strong_wind")),
    "Tropical Storm Warning": ("nws_tropical_storm_warning", ("weather_alert", "extreme_weather", "strong_wind")),
    "High Wind Warning": ("nws_high_wind_warning", ("weather_alert", "strong_wind")),
    "Dense Fog Advisory": ("nws_dense_fog_advisory", ("weather_alert", "low_visibility")),
    "Red Flag Warning": ("nws_red_flag_warning", ("weather_alert", "extreme_weather")),
}

_VTEC = re.compile(r"/O\.[A-Z]{3}\.([A-Z0-9]{4})\.([A-Z]{2})\.([A-Z])\.(\d{4})\.")


def _first(values: Any) -> str | None:
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def _stable_alert_id(properties: dict[str, Any]) -> str:
    parameters = properties.get("parameters") or {}
    vtec = _first(parameters.get("VTEC"))
    if vtec:
        match = _VTEC.search(vtec)
        if match:
            office, phenomenon, significance, number = match.groups()
            return f"{office}.{phenomenon}.{significance}.{number}"
    references = properties.get("references") or []
    for reference in references:
        if isinstance(reference, dict) and reference.get("identifier"):
            return str(reference["identifier"])
    return str(properties.get("id") or properties.get("@id") or "")


class NwsAlertsCollector:
    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        if not self.settings.nws_user_agent:
            return CollectionResult(source="nws-alerts", error="SENTINELA_NWS_USER_AGENT ausente")
        try:
            response = self.client.get(
                NWS_ALERTS_URL,
                params={"status": "actual"},
                headers={
                    "User-Agent": self.settings.nws_user_agent,
                    "Accept": "application/geo+json",
                },
            )
            response.raise_for_status()
            features = response.json().get("features", [])
        except Exception as exc:
            return CollectionResult(
                source="nws-alerts", error=f"{type(exc).__name__}: falha na consulta NOAA/NWS",
            )

        events = []
        details = []
        discarded = 0
        for feature in features:
            properties = feature.get("properties") or {}
            official_type = str(properties.get("event") or "")
            rule = ALERT_RULES.get(official_type)
            if rule is None:
                discarded += 1
                continue
            try:
                sent = _dt(str(properties["sent"]))
                expires = _dt(str(properties.get("ends") or properties["expires"]))
            except (KeyError, TypeError, ValueError):
                discarded += 1
                continue
            if (
                str(properties.get("status") or "").lower() != "actual"
                or str(properties.get("messageType") or "").lower() not in {"alert", "update"}
                or expires <= now.astimezone(timezone.utc)
            ):
                discarded += 1
                continue
            official_id = str(properties.get("id") or properties.get("@id") or feature.get("id") or "")
            stable_id = _stable_alert_id(properties)
            if not official_id or not stable_id:
                discarded += 1
                continue
            event_type, concepts = rule
            area = str(properties.get("areaDesc") or "área coberta pelo alerta")
            sender = str(properties.get("senderName") or "NOAA/NWS")
            headline = str(properties.get("headline") or "").strip()
            summary = (
                f"A NOAA/NWS, por meio de {sender}, emitiu {official_type} para {area}. "
                f"O alerta oficial foi enviado em {sent.isoformat()} e permanece válido "
                f"até {expires.isoformat()}."
            )
            if headline:
                summary += f" Headline oficial: {headline}"
            parameters = properties.get("parameters") or {}
            evidence = {
                "source": "NOAA/NWS", "product": "api.weather.gov active alerts",
                "official_alert_id": official_id, "stable_alert_id": stable_id,
                "official_event_type": official_type, "area": area,
                "sent": sent.isoformat(), "effective": properties.get("effective"),
                "onset": properties.get("onset"), "expires": expires.isoformat(),
                "status": properties.get("status"), "message_type": properties.get("messageType"),
                "severity": properties.get("severity"), "certainty": properties.get("certainty"),
                "urgency": properties.get("urgency"), "sender_name": sender,
                "headline": headline or None, "official_description": properties.get("description"),
                "official_instruction": properties.get("instruction"),
                "geometry": feature.get("geometry"), "affected_zones": properties.get("affectedZones") or [],
                "ugc": (properties.get("geocode") or {}).get("UGC") or [],
                "same": (properties.get("geocode") or {}).get("SAME") or [],
                "vtec": _first(parameters.get("VTEC")),
                "event_codes": properties.get("eventCode") or {},
                "retrieved_at": now.isoformat(), "classification": "operational_weather_alert",
            }
            events.append(_event(
                event_type=event_type, source="NOAA/NWS", product="active-alert",
                region=stable_id, window=f"{official_id}|{sent.isoformat()}",
                group=f"nws-alert:{stable_id}",
                title=f"NOAA/NWS emitiu {official_type} para {area}",
                summary=summary, occurred_at=sent, evidence=evidence,
                keywords=list(concepts),
                entities=[{"name": "NOAA/NWS", "type": "source"}, {"name": area, "type": "location"}],
                scientific_area="climate_science", evidence_text=concepts[0],
                event_status=EventStatus.OFFICIAL_ALERT,
            ))
            details.append({
                "source": "NOAA/NWS", "region": area,
                "variable": official_type, "value": properties.get("severity"),
                "window_start": sent.isoformat(), "window_end": expires.isoformat(),
            })
        return CollectionResult(
            source="nws-alerts", received=len(features), discarded=discarded,
            events=tuple(events), details=tuple(details),
        )


__all__ = ["ALERT_RULES", "NWS_ALERTS_URL", "NwsAlertsCollector"]
