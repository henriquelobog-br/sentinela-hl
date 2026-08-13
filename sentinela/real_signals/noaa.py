"""Observacoes oceanograficas oficiais NOAA CO-OPS e NOAA NDBC."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sentinela.core.models import Event, EventStatus

from .collectors import CollectionResult, _dt, _event, _six_hour_window
from .config import CoopsStation, NdbcStation, RealSignalSettings

COOPS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
NDBC_REALTIME_URL = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"


def _failure(exc: Exception) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status is not None else type(exc).__name__


def _numeric(value: Any) -> float | None:
    if value is None or str(value).strip().upper() in {"", "MM", "N/A"}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class NoaaCoopsCollector:
    OBSERVED_PRODUCTS = frozenset({
        "water_level", "currents", "water_temperature", "air_temperature", "wind",
    })

    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        events: list[Event] = []
        details: list[dict[str, Any]] = []
        failures: list[str] = []
        notices: list[str] = []
        received = discarded = 0
        cutoff = now - timedelta(hours=self.settings.coops_lookback_hours)
        for station in self.settings.coops_stations:
            for product in station.products:
                try:
                    rows, metadata = self._fetch(station, product)
                except Exception as exc:
                    failures.append(f"{station.id}/{product}={_failure(exc)}")
                    continue
                received += len(rows)
                if not rows:
                    continue
                if product == "water_temperature" and station.temperature_baseline_c is None:
                    notices.append(f"temperature_anomaly_skipped={station.id}:baseline_ausente")
                grouped: dict[datetime, list[tuple[datetime, float, dict[str, Any]]]] = {}
                for row in rows:
                    occurred = self._occurred(row)
                    value = self._value(product, row)
                    if occurred is None or value is None or occurred < cutoff or occurred > now + timedelta(minutes=10):
                        discarded += 1
                        continue
                    start, _ = _six_hour_window(occurred)
                    grouped.setdefault(start, []).append((occurred, value, row))
                for window_start, members in sorted(grouped.items()):
                    selected = max(members, key=lambda item: abs(item[1]) if product == "currents" else item[1])
                    event = self._coops_event(
                        now, station, product, metadata, window_start,
                        window_start + timedelta(hours=6), selected,
                    )
                    observed = selected[1]
                    unit = "m/s" if product == "currents" else self._unit(product)
                    threshold = self._threshold(station, product)
                    details.append({
                        "source": "NOAA CO-OPS", "region": station.id,
                        "station": station.name, "variable": product,
                        "value": observed, "unit": unit, "threshold": threshold,
                        "window_start": window_start.isoformat(),
                        "window_end": (window_start + timedelta(hours=6)).isoformat(),
                    })
                    if event is None:
                        discarded += 1
                    else:
                        events.append(event)
        if failures:
            notices.append("falhas parciais: " + ", ".join(failures))
        return CollectionResult(
            source="noaa-coops", received=received, discarded=discarded,
            events=tuple(events), notice="; ".join(dict.fromkeys(notices)) or None,
            details=tuple(details),
        )

    def _fetch(self, station: CoopsStation, product: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if product not in self.OBSERVED_PRODUCTS | {"predictions"}:
            raise ValueError("produto CO-OPS nao permitido")
        params: dict[str, Any] = {
            "product": product, "application": "sentinela-hl", "date": "recent",
            "station": station.id, "time_zone": "gmt", "units": "metric", "format": "json",
        }
        if product in {"water_level", "predictions"}:
            params["datum"] = station.datum
        if product == "currents" and station.current_bin is not None:
            params["bin"] = station.current_bin
        response = self.client.get(COOPS_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("resposta CO-OPS invalida")
        rows = payload.get("predictions") if product == "predictions" else payload.get("data")
        if rows is None:
            return [], payload.get("metadata") or {}
        if not isinstance(rows, list):
            raise ValueError("lote CO-OPS invalido")
        return rows, payload.get("metadata") or {}

    @staticmethod
    def _occurred(row: dict[str, Any]) -> datetime | None:
        try:
            return _dt(str(row["t"]))
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _value(product: str, row: dict[str, Any]) -> float | None:
        value = _numeric(row.get("s") if product in {"currents", "wind"} else row.get("v"))
        return value / 100 if value is not None and product == "currents" else value

    @staticmethod
    def _unit(product: str) -> str | None:
        return {
            "water_level": "m", "predictions": "m", "water_temperature": "degC",
            "air_temperature": "degC", "wind": "m/s", "currents": "m/s",
        }.get(product)

    def _threshold(self, station: CoopsStation, product: str) -> float | None:
        if product == "water_level":
            return self.settings.coops_water_level_threshold_m
        if product == "currents":
            return self.settings.coops_current_threshold_ms
        if product == "water_temperature" and station.temperature_baseline_c is not None:
            return self.settings.coops_temp_anomaly_c
        return None

    def _coops_event(
        self, now: datetime, station: CoopsStation, product: str,
        metadata: dict[str, Any], window_start: datetime, window_end: datetime,
        selected: tuple[datetime, float, dict[str, Any]],
    ) -> Event | None:
        occurred, value, row = selected
        threshold = self._threshold(station, product)
        if product == "water_level":
            if value < self.settings.coops_water_level_threshold_m:
                return None
            event_type, concept = "coastal_water_level_anomaly", "water_level"
            title = f"Nivel d'agua elevado observado em {station.name}"
            summary = f"A NOAA CO-OPS registrou nivel d'agua de {value:g} m em {station.name}, em {occurred.isoformat()}. O valor ultrapassa o limiar operacional configurado de {threshold:g} m, relativo ao datum {station.datum}."
        elif product == "currents":
            if abs(value) < self.settings.coops_current_threshold_ms:
                return None
            event_type, concept = "strong_tidal_current", "ocean_current"
            title = f"Corrente forte observada em {station.name}"
            summary = f"A NOAA CO-OPS registrou corrente de {value:g} m/s em {station.name}, em {occurred.isoformat()}. O valor ultrapassa o limiar operacional configurado de {threshold:g} m/s."
        elif product == "water_temperature" and station.temperature_baseline_c is not None:
            deviation = value - station.temperature_baseline_c
            if abs(deviation) < self.settings.coops_temp_anomaly_c:
                return None
            event_type, concept = "coastal_temperature_anomaly", "sea_surface_temperature"
            title = f"Temperatura costeira fora do baseline em {station.name}"
            summary = f"A NOAA CO-OPS registrou temperatura da agua de {value:g} degC em {station.name}, em {occurred.isoformat()}, desvio de {deviation:+g} degC do baseline explicitamente configurado de {station.temperature_baseline_c:g} degC."
        else:
            return None
        evidence = {
            "source": "NOAA CO-OPS", "product": product,
            "station_id": station.id, "station_name": station.name,
            "latitude": float(metadata.get("lat") or station.latitude),
            "longitude": float(metadata.get("lon") or station.longitude),
            "datum": station.datum if product == "water_level" else None,
            "units": self._unit(product), "timestamp": occurred.isoformat(),
            "observed_value": value, "threshold": threshold,
            "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
            "direction_degrees": _numeric(row.get("d")), "quality_flags": row.get("f"),
            "temperature_baseline_c": station.temperature_baseline_c,
            "retrieved_at": now.isoformat(), "source_metadata": metadata,
        }
        return _event(
            event_type=event_type, source="NOAA CO-OPS", product=product,
            region=station.id, window=f"{product}|{window_start.isoformat()}|{occurred.isoformat()}",
            group=f"noaa-coops:{station.id}:{product}:{event_type}",
            title=title, summary=summary, occurred_at=occurred, evidence=evidence,
            keywords=[concept],
            entities=[{"name": "NOAA CO-OPS", "type": "source"}, {"name": station.name, "type": "location"}],
            scientific_area="oceanography", evidence_text=concept,
            event_status=EventStatus.OBSERVED_FACT,
        )


class NoaaNdbcCollector:
    FIELDS = {
        "WVHT": ("significant_wave_height", "m"),
        "DPD": ("dominant_wave_period", "s"),
        "APD": ("average_wave_period", "s"),
        "MWD": ("wave_direction", "degT"),
        "WSPD": ("wind_speed", "m/s"),
        "GST": ("wind_gust", "m/s"),
        "PRES": ("sea_level_pressure", "hPa"),
        "WTMP": ("water_temperature", "degC"),
    }
    RULES = {
        "WVHT": ("high_wave_observation", "wave_height"),
        "DPD": ("long_period_swell_observation", "wave_period"),
        "WSPD": ("strong_marine_wind_observation", "strong_wind"),
        "GST": ("strong_marine_wind_observation", "strong_wind"),
    }

    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        events: list[Event] = []
        details: list[dict[str, Any]] = []
        failures: list[str] = []
        received = discarded = 0
        cutoff = now - timedelta(hours=self.settings.ndbc_lookback_hours)
        for station in self.settings.ndbc_stations:
            try:
                response = self.client.get(NDBC_REALTIME_URL.format(station=station.id))
                response.raise_for_status()
                rows = self._parse(response.text)
            except Exception as exc:
                failures.append(f"{station.id}={_failure(exc)}")
                continue
            recent = [row for row in rows if cutoff <= row["timestamp"] <= now + timedelta(minutes=10)]
            received += len(recent)
            for field, (variable, unit) in self.FIELDS.items():
                grouped: dict[datetime, list[dict[str, Any]]] = {}
                for row in recent:
                    if row.get(field) is None:
                        discarded += 1
                        continue
                    start, _ = _six_hour_window(row["timestamp"])
                    grouped.setdefault(start, []).append(row)
                for window_start, members in sorted(grouped.items()):
                    selected = max(members, key=lambda row: row[field])
                    threshold = self._threshold(field)
                    details.append({
                        "source": "NOAA NDBC", "region": station.id,
                        "station": station.name, "variable": variable,
                        "value": selected[field], "unit": unit, "threshold": threshold,
                        "window_start": window_start.isoformat(),
                        "window_end": (window_start + timedelta(hours=6)).isoformat(),
                    })
                    event = self._ndbc_event(now, station, field, variable, unit, threshold, window_start, selected)
                    if event is None:
                        discarded += 1
                    else:
                        events.append(event)
        notice = "falhas parciais: " + ", ".join(failures) if failures else None
        return CollectionResult(
            source="noaa-ndbc", received=received, discarded=discarded,
            events=tuple(events), notice=notice, details=tuple(details),
        )

    @classmethod
    def _parse(cls, text: str) -> list[dict[str, Any]]:
        lines = [line.split() for line in text.splitlines() if line.strip()]
        header = next((line for line in lines if line[0] == "#YY"), None)
        if header is None:
            raise ValueError("cabecalho NDBC ausente")
        names = [name.lstrip("#") for name in header]
        rows = []
        for values in lines:
            if values[0].startswith("#") or len(values) < len(names):
                continue
            raw = dict(zip(names, values))
            try:
                timestamp = datetime(
                    int(raw["YY"]), int(raw["MM"]), int(raw["DD"]),
                    int(raw["hh"]), int(raw.get("mm", 0)), tzinfo=timezone.utc,
                )
            except (KeyError, TypeError, ValueError):
                continue
            row: dict[str, Any] = {"timestamp": timestamp}
            row.update({field: _numeric(raw.get(field)) for field in cls.FIELDS})
            rows.append(row)
        return rows

    def _threshold(self, field: str) -> float | None:
        if field == "WVHT":
            return self.settings.ndbc_wave_height_threshold_m
        if field == "DPD":
            return self.settings.ndbc_swell_period_threshold_s
        if field in {"WSPD", "GST"}:
            return self.settings.ndbc_wind_threshold_ms
        return None

    def _ndbc_event(
        self, now: datetime, station: NdbcStation, field: str, variable: str,
        unit: str, threshold: float | None, window_start: datetime,
        selected: dict[str, Any],
    ) -> Event | None:
        if field not in self.RULES or threshold is None or selected[field] < threshold:
            return None
        event_type, concept = self.RULES[field]
        value = selected[field]
        occurred = selected["timestamp"]
        if field == "WVHT":
            title = f"Ondas elevadas observadas na estacao {station.name}"
            summary = f"A NOAA NDBC registrou altura significativa de onda de {value:g} m na estacao {station.name}, em {occurred.isoformat()}. O valor ultrapassa o limiar operacional configurado de {threshold:g} m."
        elif field == "DPD":
            title = f"Periodo dominante longo observado na estacao {station.name}"
            summary = f"A NOAA NDBC registrou periodo dominante de onda de {value:g} s na estacao {station.name}, em {occurred.isoformat()}. O valor ultrapassa o limiar operacional configurado de {threshold:g} s; a observacao nao afirma ressaca automaticamente."
        else:
            title = f"Vento marinho forte observado na estacao {station.name}"
            summary = f"A NOAA NDBC registrou {variable.replace('_', ' ')} de {value:g} m/s na estacao {station.name}, em {occurred.isoformat()}. O valor ultrapassa o limiar operacional configurado de {threshold:g} m/s e nao implica inferencia automatica de risco a navegacao."
        evidence = {
            "source": "NOAA NDBC", "product": "realtime2 standard meteorological data",
            "station_id": station.id, "station_name": station.name,
            "latitude": station.latitude, "longitude": station.longitude,
            "variable": variable, "source_field": field, "units": unit,
            "timestamp": occurred.isoformat(), "observed_value": value,
            "threshold": threshold, "window_start": window_start.isoformat(),
            "window_end": (window_start + timedelta(hours=6)).isoformat(),
            "significant_wave_height": selected.get("WVHT"),
            "dominant_wave_period": selected.get("DPD"),
            "average_wave_period": selected.get("APD"),
            "wave_direction": selected.get("MWD"), "wind_speed": selected.get("WSPD"),
            "wind_gust": selected.get("GST"), "sea_level_pressure": selected.get("PRES"),
            "water_temperature": selected.get("WTMP"), "retrieved_at": now.isoformat(),
        }
        return _event(
            event_type=event_type, source="NOAA NDBC", product="realtime2",
            region=station.id, window=f"{variable}|{window_start.isoformat()}",
            group=f"noaa-ndbc:{station.id}:{variable}:{event_type}",
            title=title, summary=summary, occurred_at=occurred, evidence=evidence,
            keywords=[concept],
            entities=[{"name": "NOAA NDBC", "type": "source"}, {"name": station.name, "type": "location"}],
            scientific_area="oceanography", evidence_text=concept,
            event_status=EventStatus.OBSERVED_FACT,
        )


def possible_forecast_observation_matches(
    ndbc_events: tuple[Event, ...], marine_events: tuple[Event, ...],
    *, maximum_distance_km: float = 150.0, maximum_time_hours: float = 6.0,
) -> tuple[dict[str, Any], ...]:
    compatible = {
        "high_wave_observation": {"marine_high_waves_forecast"},
        "long_period_swell_observation": {"marine_long_period_swell_forecast"},
    }
    matches = []
    for observed in ndbc_events:
        oe = observed.evidence[0]
        forecast_categories = compatible.get(observed.category)
        if forecast_categories is None:
            continue
        for forecast in marine_events:
            fe = forecast.evidence[0]
            if forecast.category not in forecast_categories:
                continue
            if not observed.occurred_at or not forecast.occurred_at:
                continue
            if abs((observed.occurred_at - forecast.occurred_at).total_seconds()) > maximum_time_hours * 3600:
                continue
            distance = _haversine_km(
                float(oe["latitude"]), float(oe["longitude"]),
                float(fe["latitude"]), float(fe["longitude"]),
            )
            if distance <= maximum_distance_km:
                matches.append({
                    "kind": "possible_forecast_observation_match",
                    "ndbc_event_id": str(observed.id),
                    "openmeteo_marine_event_id": str(forecast.id),
                    "distance_km": round(distance, 3),
                })
    return tuple(matches)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


__all__ = [
    "COOPS_URL", "NDBC_REALTIME_URL", "NoaaCoopsCollector", "NoaaNdbcCollector",
    "possible_forecast_observation_matches",
]
