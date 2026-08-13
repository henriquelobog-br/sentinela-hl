"""Coletores reais gratuitos para sismologia, meteorologia, mar e clima espacial."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sentinela.core.models import EventStatus

from .collectors import CollectionResult, _dt, _event, _six_hour_window
from .config import ForecastLocation, RealSignalSettings

USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
DONKI_URL = "https://api.nasa.gov/DONKI"
DONKI_CCMC_URL = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get"


def _millis(value: Any) -> datetime:
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)


class UsgsCollector:
    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        start = now - timedelta(hours=self.settings.usgs_lookback_hours)
        try:
            response = self.client.get(USGS_URL, params={
                "format": "geojson",
                "starttime": start.isoformat(),
                "endtime": now.isoformat(),
                "minmagnitude": self.settings.usgs_min_magnitude,
                "orderby": "time",
                "limit": self.settings.usgs_limit,
                "eventtype": "earthquake",
            })
            response.raise_for_status()
            features = response.json().get("features", [])
        except Exception as exc:
            return CollectionResult(
                source="usgs",
                error=f"{type(exc).__name__}: falha na consulta USGS",
            )
        events = []
        details = []
        discarded = 0
        for feature in features:
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            source_id = feature.get("id")
            magnitude = properties.get("mag")
            status = str(properties.get("status") or "").lower()
            source_type = str(properties.get("type") or "earthquake").lower()
            if (
                not source_id
                or magnitude is None
                or float(magnitude) < self.settings.usgs_min_magnitude
                or status == "deleted"
                or source_type != "earthquake"
                or len(coordinates) < 3
                or any(value is None for value in coordinates[:3])
                or properties.get("time") is None
            ):
                discarded += 1
                continue
            occurred = _millis(properties["time"])
            updated = _millis(properties.get("updated") or properties["time"])
            longitude, latitude, depth = map(float, coordinates[:3])
            magnitude = float(magnitude)
            place = str(properties.get("place") or "local não informado")
            summary = (
                f"O USGS registrou um terremoto de magnitude {magnitude:g}, "
                f"profundidade de {depth:g} km, em {place}, às "
                f"{occurred.isoformat()} UTC. O registro não implica, por si "
                "só, ocorrência de danos."
            )
            evidence = {
                "source": "USGS",
                "product": "FDSN Event Web Service GeoJSON",
                "source_event_id": str(source_id),
                "region": place,
                "magnitude": magnitude,
                "magnitude_type": properties.get("magType"),
                "place": place,
                "latitude": latitude,
                "longitude": longitude,
                "depth_km": depth,
                "occurred_at": occurred.isoformat(),
                "updated_at": updated.isoformat(),
                "status": properties.get("status"),
                "tsunami": properties.get("tsunami"),
                "alert": properties.get("alert"),
                "significance": properties.get("sig"),
                "detail_url": properties.get("detail"),
                "event_url": properties.get("url"),
                "retrieved_at": now.isoformat(),
            }
            events.append(_event(
                event_type="earthquake_detected",
                source="USGS",
                product="earthquake-catalog",
                region=str(source_id),
                window=f"{source_id}|{updated.isoformat()}",
                group=f"usgs:{source_id}",
                title=f"Terremoto de magnitude {magnitude:g} registrado em {place}",
                summary=summary,
                occurred_at=occurred,
                evidence=evidence,
                keywords=["earthquake", "seismic_magnitude"],
                entities=[{"name": "USGS", "type": "source"}, {"name": place, "type": "place"}],
                scientific_area="seismology",
                evidence_text="earthquake",
                event_status=EventStatus.OBSERVED_FACT,
            ))
            details.append({
                "source": "USGS", "region": place, "variable": "magnitude",
                "value": magnitude, "threshold": self.settings.usgs_min_magnitude,
            })
        return CollectionResult(
            source="usgs", received=len(features), discarded=discarded,
            events=tuple(events), details=tuple(details),
        )


def _hourly_groups(
    payload: dict[str, Any], variable: str, *, preceding_hour: bool = False
) -> list[tuple[datetime, datetime, list[tuple[datetime, float, int]]]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get(variable) or []
    grouped: dict[datetime, list[tuple[datetime, float, int]]] = {}
    for index, (raw_time, raw_value) in enumerate(zip(times, values)):
        if raw_value is None:
            continue
        try:
            occurred = _dt(str(raw_time))
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        grouping_time = occurred - timedelta(microseconds=1) if preceding_hour else occurred
        window_start, window_end = _six_hour_window(grouping_time)
        grouped.setdefault(window_start, []).append((occurred, value, index))
    return [
        (start, start + timedelta(hours=6), members)
        for start, members in sorted(grouped.items())
    ]


def _at(values: dict[str, Any], key: str, index: int) -> Any:
    items = values.get(key)
    if not isinstance(items, list) or index >= len(items):
        return None
    return items[index]


class OpenMeteoWeatherCollector:
    VARIABLES = (
        "temperature_2m", "precipitation", "wind_speed_10m",
        "wind_gusts_10m", "surface_pressure", "visibility",
    )

    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        events = []
        details = []
        received = discarded = failures = 0
        for location in self.settings.weather_locations:
            try:
                response = self.client.get(WEATHER_URL, params={
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "hourly": ",".join(self.VARIABLES),
                    "forecast_hours": self.settings.weather_forecast_hours,
                    "timezone": "GMT",
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm",
                    "cell_selection": "nearest",
                })
                response.raise_for_status()
                payload = response.json()
            except Exception:
                failures += 1
                continue
            hourly = payload.get("hourly") or {}
            received += len(hourly.get("time") or [])
            units = payload.get("hourly_units") or {}
            for variable in ("wind_gusts_10m", "precipitation", "visibility", "temperature_2m"):
                if variable not in hourly:
                    discarded += 1
                    continue
                for window_start, window_end, members in _hourly_groups(
                    payload, variable,
                    preceding_hour=variable in {"wind_gusts_10m", "precipitation"},
                ):
                    event = self._weather_event(
                        now, location, payload, units, variable,
                        window_start, window_end, members,
                    )
                    if event is None:
                        discarded += 1
                        continue
                    events.append(event)
                    evidence = event.evidence[0]
                    details.append({
                        "source": "Open-Meteo Weather", "region": location.id,
                        "variable": variable, "value": evidence["value"],
                        "unit": evidence["unit"], "threshold": evidence["threshold"],
                        "window_start": window_start.isoformat(),
                        "window_end": window_end.isoformat(),
                    })
        notice = f"falhas parciais em {failures} local(is)" if failures else None
        return CollectionResult(
            source="openmeteo_weather", received=received, discarded=discarded,
            events=tuple(events), notice=notice, details=tuple(details),
        )

    def _weather_event(
        self, now: datetime, location: ForecastLocation, payload: dict[str, Any],
        units: dict[str, Any], variable: str, window_start: datetime,
        window_end: datetime, members: list[tuple[datetime, float, int]],
    ):
        event_type = title = summary = rule = None
        threshold: float
        if variable == "wind_gusts_10m":
            occurred, value, index = max(members, key=lambda item: item[1])
            threshold = self.settings.weather_wind_gust_threshold_kmh
            if value >= threshold:
                event_type = "weather_strong_wind_forecast"
                title = f"Rajadas fortes previstas para {location.name_pt}"
                summary = f"O Open-Meteo prevê rajadas máximas de {value:g} km/h em {location.name_pt} entre {window_start.isoformat()} e {window_end.isoformat()}. O valor ultrapassa o limiar operacional de {threshold:g} km/h."
        elif variable == "precipitation":
            occurred, value, index = max(members, key=lambda item: item[1])
            threshold = self.settings.weather_precipitation_threshold_mm_h
            if value >= threshold:
                event_type = "weather_heavy_precipitation_forecast"
                title = f"Precipitação intensa prevista para {location.name_pt}"
                summary = f"O Open-Meteo prevê precipitação horária máxima de {value:g} mm em {location.name_pt} entre {window_start.isoformat()} e {window_end.isoformat()}, acima do limiar operacional de {threshold:g} mm/h."
        elif variable == "visibility":
            occurred, value, index = min(members, key=lambda item: item[1])
            threshold = self.settings.weather_visibility_threshold_m
            if value <= threshold:
                event_type = "weather_low_visibility_forecast"
                title = f"Baixa visibilidade prevista para {location.name_pt}"
                summary = f"O Open-Meteo prevê visibilidade mínima de {value:g} m em {location.name_pt} entre {window_start.isoformat()} e {window_end.isoformat()}, abaixo do limiar operacional de {threshold:g} m."
        else:
            highest = max(members, key=lambda item: item[1])
            lowest = min(members, key=lambda item: item[1])
            high_excess = highest[1] - self.settings.weather_temperature_high_c
            low_excess = self.settings.weather_temperature_low_c - lowest[1]
            if max(high_excess, low_excess) < 0:
                return None
            if high_excess >= low_excess:
                occurred, value, index = highest
                threshold = self.settings.weather_temperature_high_c
                rule = "acima"
            else:
                occurred, value, index = lowest
                threshold = self.settings.weather_temperature_low_c
                rule = "abaixo"
            event_type = "weather_extreme_temperature_forecast"
            title = f"Temperatura extrema prevista para {location.name_pt}"
            summary = f"O Open-Meteo prevê temperatura de {value:g} °C em {location.name_pt} entre {window_start.isoformat()} e {window_end.isoformat()}, {rule} do limiar operacional de {threshold:g} °C."
        if event_type is None:
            return None
        evidence = {
            "source": "Open-Meteo Weather", "product": "Weather Forecast API",
            "variable": variable, "region": location.id,
            "latitude": location.latitude, "longitude": location.longitude,
            "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
            "value": value, "threshold": threshold,
            "unit": units.get(variable), "occurred_at": occurred.isoformat(),
            "retrieved_at": now.isoformat(), "model": payload.get("model"),
            "surface_pressure": _at(payload.get("hourly") or {}, "surface_pressure", index),
            "wind_speed_10m": _at(payload.get("hourly") or {}, "wind_speed_10m", index),
        }
        concept = {
            "weather_strong_wind_forecast": "strong_wind",
            "weather_heavy_precipitation_forecast": "heavy_precipitation",
            "weather_low_visibility_forecast": "low_visibility",
            "weather_extreme_temperature_forecast": "extreme_temperature",
        }[event_type]
        return _event(
            event_type=event_type, source="Open-Meteo Weather",
            product="weather-forecast", region=location.id,
            window=f"{variable}|{window_start.isoformat()}",
            group=f"openmeteo-weather:{event_type}:{location.id}:{variable}",
            title=title, summary=summary, occurred_at=occurred,
            evidence=evidence, keywords=[concept, "weather_forecast"],
            entities=[{"name": "Open-Meteo", "type": "source"}, {"name": location.name_pt, "type": "location"}],
            scientific_area="climate_science", evidence_text=concept,
            event_status=EventStatus.FORECAST,
        )


class OpenMeteoMarineCollector:
    VARIABLES = (
        "wave_height", "wave_direction", "wave_period", "wind_wave_height",
        "swell_wave_height", "ocean_current_velocity", "sea_surface_temperature",
    )
    RULES = {
        "wave_height": ("marine_high_waves_forecast", "Ondas elevadas previstas para {location}"),
        "swell_wave_height": ("marine_high_swell_forecast", "Ondulação elevada prevista para {location}"),
        "wave_period": ("marine_long_period_swell_forecast", "Ondas de período longo previstas para {location}"),
    }

    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        events = []
        details = []
        received = discarded = failures = 0
        thresholds = {
            "wave_height": self.settings.marine_wave_height_threshold_m,
            "swell_wave_height": self.settings.marine_swell_height_threshold_m,
            "wave_period": self.settings.marine_wave_period_threshold_s,
        }
        for location in self.settings.marine_locations:
            try:
                response = self.client.get(MARINE_URL, params={
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "hourly": ",".join(self.VARIABLES),
                    "forecast_hours": self.settings.marine_forecast_hours,
                    "timezone": "GMT", "cell_selection": "sea",
                })
                response.raise_for_status()
                payload = response.json()
            except Exception:
                failures += 1
                continue
            hourly = payload.get("hourly") or {}
            units = payload.get("hourly_units") or {}
            received += len(hourly.get("time") or [])
            for variable, (event_type, title_template) in self.RULES.items():
                if variable not in hourly:
                    discarded += 1
                    continue
                for window_start, window_end, members in _hourly_groups(payload, variable):
                    occurred, value, index = max(members, key=lambda item: item[1])
                    threshold = thresholds[variable]
                    if value < threshold:
                        discarded += 1
                        continue
                    unit = units.get(variable)
                    label = {
                        "wave_height": "altura de ondas",
                        "swell_wave_height": "altura de ondulação",
                        "wave_period": "período de ondas",
                    }[variable]
                    concept = {
                        "wave_height": "wave_height",
                        "swell_wave_height": "swell",
                        "wave_period": "wave_period",
                    }[variable]
                    summary = f"O Open-Meteo Marine prevê {label} máxima de {value:g} {unit or ''}".rstrip() + f" em {location.name_pt} entre {window_start.isoformat()} e {window_end.isoformat()}, acima do limiar operacional de {threshold:g} {unit or ''}."
                    evidence = {
                        "source": "Open-Meteo Marine", "product": "Marine Forecast API",
                        "variable": variable, "region": location.id,
                        "latitude": location.latitude, "longitude": location.longitude,
                        "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
                        "value": value, "threshold": threshold, "unit": unit,
                        "occurred_at": occurred.isoformat(), "retrieved_at": now.isoformat(),
                        "wave_direction": _at(hourly, "wave_direction", index),
                        "ocean_current_velocity": _at(hourly, "ocean_current_velocity", index),
                        "sea_surface_temperature": _at(hourly, "sea_surface_temperature", index),
                    }
                    events.append(_event(
                        event_type=event_type, source="Open-Meteo Marine",
                        product="marine-forecast", region=location.id,
                        window=f"{variable}|{window_start.isoformat()}",
                        group=f"openmeteo-marine:{event_type}:{location.id}:{variable}",
                        title=title_template.format(location=location.name_pt),
                        summary=summary, occurred_at=occurred, evidence=evidence,
                        keywords=[concept, "marine_forecast"],
                        entities=[{"name": "Open-Meteo Marine", "type": "source"}, {"name": location.name_pt, "type": "location"}],
                        scientific_area="oceanography", evidence_text=concept,
                        event_status=EventStatus.FORECAST,
                    ))
                    details.append({
                        "source": "Open-Meteo Marine", "region": location.id,
                        "variable": variable, "value": value, "unit": unit,
                        "threshold": threshold, "window_start": window_start.isoformat(),
                        "window_end": window_end.isoformat(),
                    })
        notice = f"falhas parciais em {failures} local(is)" if failures else None
        return CollectionResult(
            source="openmeteo_marine", received=received, discarded=discarded,
            events=tuple(events), notice=notice, details=tuple(details),
        )


class DonkiCollector:
    ENDPOINTS = {
        "CME": "coronal_mass_ejection_detected",
        "FLR": "solar_flare_detected",
        "GST": "geomagnetic_storm_detected",
        "SEP": "solar_energetic_particle_event",
        "IPS": "interplanetary_shock_detected",
    }
    IDS = {
        "CME": "activityID", "FLR": "flrID", "GST": "gstID",
        "SEP": "sepID", "IPS": "activityID",
    }
    TIMES = {
        "CME": "startTime", "FLR": "beginTime", "GST": "startTime",
        "SEP": "eventTime", "IPS": "eventTime",
    }

    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        start = (now - timedelta(days=self.settings.donki_lookback_days)).date().isoformat()
        end = now.date().isoformat()
        events = []
        details = []
        received = discarded = duplicates = 0
        failures: list[str] = []
        fallbacks: list[str] = []
        seen = set()
        for endpoint, event_type in self.ENDPOINTS.items():
            try:
                response = self.client.get(
                    f"{DONKI_URL}/{endpoint}",
                    params={"startDate": start, "endDate": end, "api_key": self.settings.donki_api_key},
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 429:
                        raise
                    response = self.client.get(
                        f"{DONKI_CCMC_URL}/{endpoint}",
                        params={"startDate": start, "endDate": end},
                    )
                    response.raise_for_status()
                    fallbacks.append(endpoint)
                rows = response.json()
                if not isinstance(rows, list):
                    raise ValueError("resposta DONKI não é uma lista")
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                detail = f"HTTP {status}" if status is not None else type(exc).__name__
                failures.append(f"{endpoint}={detail}")
                continue
            received += len(rows)
            for row in rows:
                official_id = row.get(self.IDS[endpoint])
                start_time = row.get(self.TIMES[endpoint])
                if not official_id or not start_time:
                    discarded += 1
                    continue
                dedup_key = (endpoint, str(official_id))
                if dedup_key in seen:
                    duplicates += 1
                    continue
                seen.add(dedup_key)
                occurred = _dt(str(start_time))
                analyses = row.get("cmeAnalyses") or []
                analysis = analyses[-1] if analyses else {}
                revision_hash = hashlib.sha256(
                    json.dumps(row, sort_keys=True, ensure_ascii=True).encode()
                ).hexdigest()[:16]
                title, summary = self._texts(endpoint, row, occurred)
                evidence = {
                    "source": "NASA DONKI", "product": endpoint,
                    "activity_id": str(official_id), "start_time": occurred.isoformat(),
                    "source_location": row.get("sourceLocation"),
                    "active_region_num": row.get("activeRegionNum"),
                    "class_type": row.get("classType"),
                    "speed": analysis.get("speed"), "type": analysis.get("type"),
                    "cme_analyses": analyses,
                    "all_kp_index": row.get("allKpIndex") or [],
                    "impact_list": row.get("impactList") or [],
                    "linked_events": row.get("linkedEvents") or [],
                    "instruments": row.get("instruments") or [],
                    "catalog": row.get("catalog"), "note": row.get("note"),
                    "link": row.get("link"), "retrieved_at": now.isoformat(),
                    "revision": revision_hash,
                }
                keyword = {
                    "CME": "cme", "FLR": "solar_flare",
                    "GST": "geomagnetic_storm",
                    "SEP": "solar_energetic_particles",
                    "IPS": "interplanetary_shock",
                }[endpoint]
                events.append(_event(
                    event_type=event_type, source="NASA DONKI", product=endpoint,
                    region=endpoint, window=f"{official_id}|{revision_hash}",
                    group=f"donki:{endpoint}:{official_id}", title=title,
                    summary=summary, occurred_at=occurred, evidence=evidence,
                    keywords=[keyword],
                    entities=[{"name": "NASA DONKI", "type": "source"}],
                    scientific_area="space_weather", evidence_text=keyword,
                    event_status=EventStatus.CATALOG_RECORD,
                ))
                details.append({
                    "source": "NASA DONKI", "region": endpoint,
                    "variable": "activity", "value": str(official_id),
                })
        notices = []
        if failures:
            notices.append("falhas parciais: " + ", ".join(failures))
        if fallbacks:
            notices.append("fallback oficial CCMC: " + ", ".join(fallbacks))
        notice = "; ".join(notices) or None
        return CollectionResult(
            source="donki", received=received, discarded=discarded,
            duplicates=duplicates, events=tuple(events), notice=notice,
            details=tuple(details),
        )

    @staticmethod
    def _texts(endpoint: str, row: dict[str, Any], occurred: datetime) -> tuple[str, str]:
        if endpoint == "CME":
            return (
                "Ejeção de massa coronal registrada pelo NASA DONKI",
                f"O NASA DONKI registrou uma ejeção de massa coronal iniciada em {occurred.isoformat()}. O evento ainda não implica impacto geomagnético na Terra.",
            )
        if endpoint == "FLR":
            class_type = row.get("classType")
            title = f"Explosão solar classe {class_type} registrada" if class_type else "Explosão solar registrada pelo NASA DONKI"
            return title, f"O NASA DONKI registrou uma explosão solar iniciada em {occurred.isoformat()}. O registro não implica, por si só, impacto na Terra."
        if endpoint == "GST":
            return "Tempestade geomagnética registrada pelo NASA DONKI", f"O NASA DONKI registrou uma tempestade geomagnética iniciada em {occurred.isoformat()}, conforme os dados oficiais disponíveis."
        if endpoint == "SEP":
            return "Evento de partículas energéticas solares registrado", f"O NASA DONKI registrou um evento de partículas energéticas solares iniciado em {occurred.isoformat()}."
        return "Choque interplanetário registrado pelo NASA DONKI", f"O NASA DONKI registrou um choque interplanetário iniciado em {occurred.isoformat()}."


__all__ = [
    "DonkiCollector", "OpenMeteoMarineCollector", "OpenMeteoWeatherCollector",
    "UsgsCollector",
]
