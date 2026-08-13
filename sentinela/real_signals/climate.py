"""Projeções climáticas Open-Meteo comparadas a baseline explícito."""

from __future__ import annotations

import calendar
import time as time_module
from collections import defaultdict
from datetime import date, datetime, time, timezone
from statistics import mean
from typing import Any

import httpx

from sentinela.core.models import EventStatus

from .collectors import CollectionResult, _event
from .config import ForecastLocation, RealSignalSettings

CLIMATE_URL = "https://climate-api.open-meteo.com/v1/climate"
CLIMATE_MODELS = frozenset({
    "CMCC_CM2_VHR4", "FGOALS_f3_H", "HiRAM_SIT_HR",
    "MRI_AGCM3_2_S", "EC_Earth3P_HR", "MPI_ESM1_2_XR", "NICAM16_8S",
})
VARIABLES = ("temperature_2m_mean", "precipitation_sum")
MONTH_NAMES_PT = (
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def _period(value: str) -> date:
    return date.fromisoformat(value)


def _complete_months(
    times: list[Any], values: list[Any], start: date, end: date,
) -> dict[tuple[int, int], list[float]]:
    months: dict[tuple[int, int], list[float]] = defaultdict(list)
    for raw_time, raw_value in zip(times, values):
        if raw_value is None:
            continue
        try:
            day = date.fromisoformat(str(raw_time))
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if start <= day <= end:
            months[(day.year, day.month)].append(value)
    return {
        key: members for key, members in months.items()
        if len(members) == calendar.monthrange(*key)[1]
    }


def _monthly_climatology(
    times: list[Any], values: list[Any], start: date, end: date, *, total: bool,
) -> dict[int, float]:
    complete = _complete_months(times, values, start, end)
    by_month: dict[int, list[float]] = defaultdict(list)
    for (_, month), members in complete.items():
        by_month[month].append(sum(members) if total else mean(members))
    return {month: mean(members) for month, members in by_month.items() if members}


class OpenMeteoClimateCollector:
    def __init__(
        self, settings: RealSignalSettings, client: Any | None = None,
        sleeper: Any | None = None,
    ):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)
        self.sleeper = sleeper or time_module.sleep

    def collect(self, now: datetime) -> CollectionResult:
        try:
            baseline_start = _period(self.settings.climate_baseline_start)
            baseline_end = _period(self.settings.climate_baseline_end)
            target_start = _period(self.settings.climate_target_start)
            target_end = _period(self.settings.climate_target_end)
            self._validate_periods(baseline_start, baseline_end, target_start, target_end)
        except ValueError as exc:
            return CollectionResult(source="openmeteo_climate", error=str(exc))

        events = []
        details = []
        received = discarded = incomplete = 0
        failures = []
        for index, location in enumerate(self.settings.climate_locations):
            if index and index % 3 == 0:
                self.sleeper(61)
            try:
                baseline_payload = self._request(location, baseline_start, baseline_end)
                target_payload = self._request(location, target_start, target_end)
            except httpx.HTTPStatusError as exc:
                failures.append(location.id)
                if exc.response.status_code == 429:
                    failures.extend(item.id for item in self.settings.climate_locations[index + 1:])
                    break
                continue
            except Exception:
                failures.append(location.id)
                continue
            baseline_daily = baseline_payload.get("daily") or {}
            target_daily = target_payload.get("daily") or {}
            times = (baseline_daily.get("time") or []) + (target_daily.get("time") or [])
            received += len(times)
            for variable in VARIABLES:
                values = self._values(baseline_daily, variable) + self._values(target_daily, variable)
                if not times or not values:
                    incomplete += 1
                    continue
                baseline = _monthly_climatology(
                    times, values, baseline_start, baseline_end,
                    total=variable == "precipitation_sum",
                )
                target = _monthly_climatology(
                    times, values, target_start, target_end,
                    total=variable == "precipitation_sum",
                )
                if not baseline or not target:
                    incomplete += 1
                    continue
                for month in range(1, 13):
                    if month not in baseline or month not in target:
                        discarded += 1
                        continue
                    event = self._climate_event(
                        now, location, variable, month, baseline[month], target[month],
                        baseline_start, baseline_end, target_start, target_end,
                    )
                    if event is None:
                        discarded += 1
                        continue
                    events.append(event)
                    evidence = event.evidence[0]
                    details.append({
                        "source": "Open-Meteo Climate", "region": location.id,
                        "variable": variable, "value": evidence["anomaly"],
                        "unit": evidence["unit"], "threshold": evidence["threshold"],
                        "window_start": target_start.isoformat(),
                        "window_end": target_end.isoformat(),
                    })
        notices = []
        if failures:
            notices.append("falhas parciais: " + ", ".join(failures))
        if incomplete:
            notices.append(f"series_sem_baseline_ou_modelo={incomplete}")
        return CollectionResult(
            source="openmeteo_climate", received=received, discarded=discarded,
            events=tuple(events), details=tuple(details),
            notice="; ".join(notices) or None,
        )

    def _request(self, location: ForecastLocation, start: date, end: date) -> dict[str, Any]:
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "models": self.settings.climate_model,
            "daily": ",".join(VARIABLES),
            "timezone": "GMT",
            "temperature_unit": "celsius",
            "precipitation_unit": "mm",
            "cell_selection": "land",
        }
        for attempt in range(2):
            response = self.client.get(CLIMATE_URL, params=params)
            if response.status_code == 429 and attempt == 0:
                self.sleeper(61)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("retry climático esgotado")

    def _validate_periods(
        self, baseline_start: date, baseline_end: date,
        target_start: date, target_end: date,
    ) -> None:
        if not self.settings.climate_model:
            raise ValueError("modelo climático ausente")
        if self.settings.climate_model not in CLIMATE_MODELS:
            raise ValueError("modelo climático não suportado")
        if not (date(1950, 1, 1) <= baseline_start <= baseline_end <= date(2049, 12, 31)):
            raise ValueError("período climatológico fora da cobertura 1950-2049")
        if not (date(1950, 1, 1) <= target_start <= target_end <= date(2049, 12, 31)):
            raise ValueError("período alvo fora da cobertura 1950-2049")
        if baseline_end >= target_start:
            raise ValueError("baseline e período alvo são incompatíveis ou sobrepostos")
        if (baseline_start.month, baseline_start.day) != (1, 1) or (baseline_end.month, baseline_end.day) != (12, 31):
            raise ValueError("baseline deve abranger anos civis completos")
        if (target_start.month, target_start.day) != (1, 1) or (target_end.month, target_end.day) != (12, 31):
            raise ValueError("período alvo deve abranger anos civis completos")

    def _values(self, daily: dict[str, Any], variable: str) -> list[Any]:
        values = daily.get(variable)
        if isinstance(values, list):
            return values
        suffixed = daily.get(f"{variable}_{self.settings.climate_model}")
        return suffixed if isinstance(suffixed, list) else []

    def _climate_event(
        self, now: datetime, location: ForecastLocation, variable: str, month: int,
        baseline_mean: float, target_mean: float, baseline_start: date,
        baseline_end: date, target_start: date, target_end: date,
    ):
        anomaly = target_mean - baseline_mean
        month_name = MONTH_NAMES_PT[month]
        if variable == "temperature_2m_mean":
            threshold = self.settings.climate_temperature_anomaly_threshold_c
            if abs(anomaly) < threshold:
                return None
            event_type = "climate_temperature_anomaly"
            concept = "temperature_anomaly"
            unit = "°C"
            direction = "acima" if anomaly > 0 else "abaixo"
            title = f"Temperatura modelada {direction} da média climatológica em {location.name_pt}"
            comparison = f"{target_mean:.2f} °C ante {baseline_mean:.2f} °C"
        else:
            if baseline_mean < self.settings.climate_precipitation_min_baseline_mm:
                return None
            relative = anomaly / baseline_mean
            threshold = self.settings.climate_precipitation_anomaly_threshold_fraction
            if (
                abs(relative) < threshold
                or abs(anomaly) < self.settings.climate_precipitation_anomaly_threshold_mm
            ):
                return None
            event_type = "climate_precipitation_anomaly"
            concept = "precipitation_anomaly"
            unit = "mm/mês"
            direction = "acima" if anomaly > 0 else "abaixo"
            title = f"Precipitação modelada {direction} da média climatológica em {location.name_pt}"
            comparison = f"{target_mean:.2f} mm/mês ante {baseline_mean:.2f} mm/mês"
        relative_anomaly = anomaly / baseline_mean if baseline_mean else None
        summary = (
            f"A projeção climática {self.settings.climate_model} disponibilizada pelo "
            f"Open-Meteo estima para {month_name} em {location.name_pt} {comparison}, "
            f"comparando {target_start.year}-{target_end.year} com o baseline "
            f"{baseline_start.year}-{baseline_end.year}. Trata-se de simulação climática "
            "CMIP6 HighResMIP corrigida com ERA5-Land, não de observação meteorológica."
        )
        evidence = {
            "source": "Open-Meteo Climate", "product": "Climate API CMIP6 HighResMIP",
            "region": location.id, "latitude": location.latitude,
            "longitude": location.longitude, "variable": variable,
            "calendar_month": month, "baseline_start": baseline_start.isoformat(),
            "baseline_end": baseline_end.isoformat(),
            "target_period": f"{target_start.isoformat()}/{target_end.isoformat()}",
            "target_start": target_start.isoformat(), "target_end": target_end.isoformat(),
            "climatology_mean": baseline_mean, "projected_mean": target_mean,
            "anomaly": anomaly, "relative_anomaly": relative_anomaly,
            "unit": unit, "threshold": threshold,
            "model": self.settings.climate_model, "source_semantics": "climate_model_projection_not_observation",
            "classification": "climate_projection", "operational_feed": False,
            "aggregation": "calendar_month_climatology", "retrieved_at": now.isoformat(),
        }
        revision = f"{baseline_mean:.4f}|{target_mean:.4f}"
        return _event(
            event_type=event_type, source="Open-Meteo Climate", product="climate-projection",
            region=location.id,
            window=f"{variable}|month={month}|{baseline_start}|{baseline_end}|{target_start}|{target_end}|{self.settings.climate_model}|{revision}",
            group=f"openmeteo-climate:{location.id}:{variable}:{baseline_start}:{baseline_end}:{target_start}:{target_end}:{self.settings.climate_model}",
            title=title, summary=summary,
            occurred_at=datetime.combine(target_end, time.min, tzinfo=timezone.utc),
            evidence=evidence, keywords=["climate_anomaly", concept],
            entities=[{"name": "Open-Meteo Climate", "type": "source"}, {"name": location.name_pt, "type": "location"}],
            scientific_area="climate_science", evidence_text="climate_anomaly",
            event_status=EventStatus.MODEL_PROJECTION,
        )


__all__ = ["CLIMATE_MODELS", "CLIMATE_URL", "OpenMeteoClimateCollector"]
