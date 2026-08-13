"""NASA FIRMS: anomalias térmicas reais agrupadas espacialmente."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sentinela.core.models import EventStatus

from .collectors import CollectionResult, _event, _six_hour_window, _uuid
from .config import RealSignalSettings
from .volcano_geopolitics import HANS_ELEVATED

FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_PUBLIC_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/"
FIRMS_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT")

DEFAULT_REGIONS: dict[str, tuple[str, tuple[float, float, float, float]]] = {
    "amazon": ("Amazônia", (-74.0, -20.0, -44.0, 6.0)),
    "espirito_santo_southeast": ("Espírito Santo e Sudeste", (-53.0, -25.0, -38.0, -14.0)),
    "namibia": ("Namíbia", (11.0, -29.0, 26.0, -16.0)),
    "angola": ("Angola", (11.0, -19.0, 25.0, -4.0)),
    "israel": ("Israel", (34.0, 29.0, 36.0, 34.0)),
    "lebanon": ("Líbano", (35.0, 33.0, 37.0, 35.0)),
    "syria": ("Síria", (35.0, 32.0, 43.0, 38.0)),
    "iran": ("Irã", (44.0, 25.0, 64.0, 40.0)),
    "indonesia": ("Indonésia", (95.0, -11.0, 141.0, 6.0)),
    "japan": ("Japão", (122.0, 24.0, 146.0, 46.0)),
    "alaska": ("Alasca", (-170.0, 51.0, -130.0, 72.0)),
    "hawaii": ("Havaí", (-161.0, 18.0, -154.0, 23.0)),
    "brazil": ("Brasil", (-74.0, -34.0, -34.0, 6.0)),
}


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class FirmsCollector:
    def __init__(
        self, settings: RealSignalSettings, client: Any | None = None,
        monitored_volcanoes: list[dict[str, Any]] | None = None,
        regions: dict[str, tuple[str, tuple[float, float, float, float]]] | None = None,
    ):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)
        self.monitored_volcanoes = monitored_volcanoes
        self.regions = regions

    def collect(self, now: datetime) -> CollectionResult:
        if not self.settings.firms_map_key:
            return CollectionResult(
                source="firms",
                error="credencial FIRMS ausente: configure SENTINELA_FIRMS_MAP_KEY",
            )
        if not 1 <= self.settings.firms_day_range <= 5:
            return CollectionResult(source="firms", error="SENTINELA_FIRMS_DAY_RANGE deve estar entre 1 e 5")
        if self.settings.firms_volcano_radius_km <= 0:
            return CollectionResult(source="firms", error="raio vulcânico FIRMS deve ser maior que zero")
        if self.settings.firms_occurrence_grid_degrees <= 0:
            return CollectionResult(source="firms", error="grade de ocorrências FIRMS deve ser maior que zero")
        try:
            regions = self._regions()
        except ValueError as exc:
            return CollectionResult(source="firms", error=f"configuração FIRMS inválida: {exc}")

        rows: list[dict[str, Any]] = []
        failures = 0
        for region_id, (region_name, bounds) in regions.items():
            area = ",".join(f"{value:g}" for value in bounds)
            for source in FIRMS_SOURCES:
                url = f"{FIRMS_AREA}/{self.settings.firms_map_key}/{source}/{area}/{self.settings.firms_day_range}"
                try:
                    response = self.client.get(url)
                    response.raise_for_status()
                    for raw in csv.DictReader(io.StringIO(response.text)):
                        raw["region_id"] = region_id
                        raw["region_name"] = region_name
                        raw["firms_source"] = source
                        rows.append(raw)
                except Exception:
                    failures += 1
        if failures == len(regions) * len(FIRMS_SOURCES):
            return CollectionResult(source="firms", error="falha nas consultas NASA FIRMS")

        hotspots = []
        discarded = 0
        seen = set()
        for row in rows:
            hotspot = self._parse(row)
            if hotspot is None:
                discarded += 1
                continue
            dedupe_key = (
                hotspot["source"], hotspot["latitude"], hotspot["longitude"],
                hotspot["acquired_at"], hotspot["satellite"],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            hotspots.append(hotspot)

        volcanoes, volcano_warning = self._volcanoes()
        clusters = self._clusters(hotspots)
        ranked = sorted(
            clusters,
            key=lambda members: (
                bool(self._nearest_volcano(members, volcanoes)),
                len(members), sum(item["frp"] or 0.0 for item in members),
                max(item["acquired_at"] for item in members),
            ),
            reverse=True,
        )
        selected = []
        selected_by_region: dict[str, int] = {}
        for members in ranked:
            region_id = members[0]["region_id"]
            if selected_by_region.get(region_id, 0) >= self.settings.firms_max_clusters_per_region:
                continue
            selected.append(members)
            selected_by_region[region_id] = selected_by_region.get(region_id, 0) + 1
            if len(selected) >= self.settings.firms_max_clusters:
                break

        events = []
        details = []
        volcanic_count = 0
        for members in selected:
            event, volcanic = self._cluster_event(members, volcanoes, now)
            events.append(event)
            volcanic_count += int(volcanic)
            evidence = event.evidence[0]
            details.append({
                "source": "NASA FIRMS", "region": evidence["region"],
                "variable": event.category, "value": evidence["hotspot_count"],
                "unit": ",".join(evidence["sensors"]),
                "window_start": evidence["window_start"],
                "window_end": evidence["window_end"],
            })
        multisensor = sum(len({item["source"] for item in members}) > 1 for members in clusters)
        updates_grouped = sum(
            max(0, len({(item["source"], _six_hour_window(item["acquired_at"])[0]) for item in members}) - 1)
            for members in clusters
        )
        notice = (
            f"hotspots_validos={len(hotspots)}; ocorrencias_termicas={len(clusters)}; "
            f"clusters_selecionados={len(events)}; clusters_vulcanicos={volcanic_count}; "
            f"clusters_nao_vulcanicos={len(events) - volcanic_count}; "
            f"ocorrencias_multissensor={multisensor}; atualizacoes_agrupadas={updates_grouped}"
        )
        if failures:
            notice += f"; consultas_parciais_com_falha={failures}"
        if volcano_warning:
            notice += f"; {volcano_warning}"
        return CollectionResult(
            source="firms", received=len(rows), discarded=discarded,
            duplicates=len(rows) - discarded - len(hotspots),
            events=tuple(events), details=tuple(details), notice=notice,
        )

    def _regions(self) -> dict[str, tuple[str, tuple[float, float, float, float]]]:
        if self.regions is not None:
            regions = dict(self.regions)
        else:
            regions = dict(DEFAULT_REGIONS)
        if not self.settings.firms_region_boxes:
            return regions
        regions = {}
        try:
            custom = json.loads(self.settings.firms_region_boxes)
            for region_id, values in custom.items():
                if not isinstance(values, list) or len(values) != 4:
                    raise ValueError("cada bounding box deve ter quatro coordenadas")
                bounds = tuple(float(value) for value in values)
                west, south, east, north = bounds
                if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                    raise ValueError("bounding box fora dos limites geográficos")
                regions[str(region_id)] = (str(region_id).replace("_", " ").title(), bounds)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("SENTINELA_FIRMS_REGION_BOXES deve ser JSON válido") from exc
        return regions

    @staticmethod
    def _parse(row: dict[str, Any]) -> dict[str, Any] | None:
        latitude = _number(row.get("latitude"))
        longitude = _number(row.get("longitude"))
        date = str(row.get("acq_date") or "")
        time = str(row.get("acq_time") or "").zfill(4)
        if latitude is None or longitude is None or not date or len(time) != 4:
            return None
        try:
            acquired_at = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        source = str(row.get("firms_source") or "")
        brightness = _number(row.get("bright_ti4") if source.startswith("VIIRS") else row.get("brightness"))
        if not source or brightness is None:
            return None
        hotspot_id = str(_uuid(
            f"firms-hotspot|{source}|{latitude:.5f}|{longitude:.5f}|"
            f"{acquired_at.isoformat()}|{row.get('satellite') or ''}"
        ))
        return {
            "id": hotspot_id, "region_id": row["region_id"], "region_name": row["region_name"],
            "source": source, "latitude": latitude, "longitude": longitude,
            "acquired_at": acquired_at, "satellite": str(row.get("satellite") or ""),
            "instrument": str(row.get("instrument") or ""),
            "confidence": str(row.get("confidence") or ""),
            "brightness": brightness, "frp": _number(row.get("frp")),
            "daynight": str(row.get("daynight") or ""),
        }

    def _clusters(self, hotspots: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        grouped: dict[tuple[str, str, int, int], list[dict[str, Any]]] = {}
        grid = self.settings.firms_occurrence_grid_degrees
        for hotspot in hotspots:
            date = hotspot["acquired_at"].date().isoformat()
            lat_cell = math.floor((hotspot["latitude"] + 90.0) / grid)
            lon_cell = math.floor((hotspot["longitude"] + 180.0) / grid)
            grouped.setdefault((hotspot["region_id"], date, lat_cell, lon_cell), []).append(hotspot)
        return [
            sorted(members, key=lambda item: (item["acquired_at"], item["source"], item["id"]))
            for _, members in sorted(grouped.items())
        ]

    def _volcanoes(self) -> tuple[list[dict[str, Any]], str | None]:
        if self.monitored_volcanoes is not None:
            return self.monitored_volcanoes, None
        try:
            response = self.client.get(HANS_ELEVATED)
            response.raise_for_status()
            elevated = response.json()
        except Exception:
            return [], "vulcões elevados USGS indisponíveis para associação"
        cache: dict[str, Any] = {}
        volcanoes = []
        for item in elevated if isinstance(elevated, list) else []:
            url = item.get("notice_data")
            if url and url not in cache:
                try:
                    detail = self.client.get(url)
                    detail.raise_for_status()
                    cache[url] = detail.json()
                except Exception:
                    cache[url] = {}
            section = next(
                (value for value in cache.get(url, {}).get("notice_sections", []) if str(value.get("vnum")) == str(item.get("vnum"))),
                {},
            )
            latitude = _number(section.get("lat"))
            longitude = _number(section.get("lng"))
            if latitude is None or longitude is None:
                continue
            volcanoes.append({
                "volcano_name": item.get("volcano_name") or section.get("vName"),
                "volcano_number": str(item.get("vnum") or section.get("vnum")),
                "latitude": latitude, "longitude": longitude,
                "alert_level": item.get("alert_level"),
                "aviation_color_code": item.get("color_code"),
            })
        return volcanoes, None

    def _nearest_volcano(self, members: list[dict[str, Any]], volcanoes: list[dict[str, Any]]) -> tuple[dict[str, Any], float] | None:
        nearest = None
        for volcano in volcanoes:
            distance = min(
                _distance_km(item["latitude"], item["longitude"], volcano["latitude"], volcano["longitude"])
                for item in members
            )
            if distance <= self.settings.firms_volcano_radius_km and (nearest is None or distance < nearest[1]):
                nearest = (volcano, distance)
        return nearest

    def _cluster_event(self, members: list[dict[str, Any]], volcanoes: list[dict[str, Any]], now: datetime):
        """Identidade térmica: região + data UTC + célula espacial estável.

        Sensor e passagem não compõem a identidade; novas observações na mesma
        ocorrência atualizam a evidência sem clustering transitivo.
        """
        members.sort(key=lambda item: (item["acquired_at"], item["id"]))
        first = members[0]
        occurrence_date = first["acquired_at"].date().isoformat()
        latitude = sum(item["latitude"] for item in members) / len(members)
        longitude = sum(item["longitude"] for item in members) / len(members)
        nearest = self._nearest_volcano(members, volcanoes)
        volcanic = nearest is not None
        if volcanic:
            event_type = "volcanic_thermal_anomaly_candidate"
        elif len(members) > 1:
            event_type = "wildfire_hotspot_cluster"
        else:
            event_type = "thermal_anomaly_detected"
        title = (
            f"Cluster de {len(members)} hotspots detectado em {first['region_name']}"
            if len(members) > 1 else f"Anomalias térmicas detectadas em {first['region_name']}"
        )
        sensors = sorted({item["source"] for item in members})
        summary = (
            f"A NASA FIRMS registrou {len(members)} anomalias térmicas entre "
            f"{members[0]['acquired_at'].isoformat()} e {members[-1]['acquired_at'].isoformat()} "
            f"na região {first['region_name']}, observadas pelos sensores {', '.join(sensors)}. "
            "O sinal não confirma, isoladamente, incêndio ou atividade vulcânica."
        )
        observation_hash = hashlib.sha256("|".join(item["id"] for item in members).encode()).hexdigest()[:16]
        grid = self.settings.firms_occurrence_grid_degrees
        lat_cell = math.floor((first["latitude"] + 90.0) / grid)
        lon_cell = math.floor((first["longitude"] + 180.0) / grid)
        occurrence_id = f"{first['region_id']}:{occurrence_date}:{lat_cell}:{lon_cell}"
        brightness = [item["brightness"] for item in members]
        frp = [item["frp"] for item in members if item["frp"] is not None]
        evidence = {
            "source": "NASA FIRMS", "product": first["source"],
            "region": first["region_name"], "region_id": first["region_id"],
            "sensor": first["source"], "sensors": sensors,
            "member_event_ids": [item["id"] for item in members],
            "hotspot_count": len(members), "centroid_latitude": latitude,
            "centroid_longitude": longitude,
            "bounding_box": [
                min(item["longitude"] for item in members), min(item["latitude"] for item in members),
                max(item["longitude"] for item in members), max(item["latitude"] for item in members),
            ],
            "earliest_acquisition": members[0]["acquired_at"].isoformat(),
            "latest_acquisition": members[-1]["acquired_at"].isoformat(),
            "window_start": members[0]["acquired_at"].isoformat(),
            "window_end": members[-1]["acquired_at"].isoformat(),
            "duration_minutes": (members[-1]["acquired_at"] - members[0]["acquired_at"]).total_seconds() / 60,
            "observation_version": observation_hash,
            "occurrence_id": occurrence_id,
            "satellites": sorted({item["satellite"] for item in members if item["satellite"]}),
            "instruments": sorted({item["instrument"] for item in members if item["instrument"]}),
            "confidence": sorted({item["confidence"] for item in members if item["confidence"]}),
            "brightness_min": min(brightness), "brightness_max": max(brightness),
            "brightness_mean": sum(brightness) / len(brightness),
            "frp_total": sum(frp) if frp else None, "frp_max": max(frp) if frp else None,
            "daynight": sorted({item["daynight"] for item in members if item["daynight"]}),
            "source_url": FIRMS_PUBLIC_URL, "retrieved_at": now.isoformat(),
            "source_observations": [
                {
                    "sensor": source,
                    "window_start": window.isoformat(),
                    "window_end": (window + timedelta(hours=6)).isoformat(),
                    "hotspot_count": len(values),
                    "frp_total": sum(item["frp"] or 0.0 for item in values),
                    "earliest_acquisition": min(item["acquired_at"] for item in values).isoformat(),
                    "latest_acquisition": max(item["acquired_at"] for item in values).isoformat(),
                }
                for (source, window), values in self._source_observations(members)
            ],
        }
        if nearest:
            volcano, distance = nearest
            evidence.update({
                "volcano_name": volcano["volcano_name"],
                "volcano_number": volcano["volcano_number"],
                "distance_to_volcano_km": distance,
                "volcano_alert_level": volcano.get("alert_level"),
                "volcano_aviation_color_code": volcano.get("aviation_color_code"),
            })
        keywords = ["thermal_anomaly", "hotspot"]
        if volcanic:
            keywords.extend(("volcanic_activity", "volcano"))
        elif len(members) > 1:
            keywords.append("wildfire")
        entities = [{"name": "NASA FIRMS", "type": "source"}]
        if nearest:
            entities.append({"name": nearest[0]["volcano_name"], "type": "volcano"})
        event = _event(
            event_type=event_type, source="NASA FIRMS", product="thermal-occurrence",
            region=first["region_id"], window=occurrence_id,
            group=f"firms-occurrence:{occurrence_id}",
            title=title, summary=summary, occurred_at=members[-1]["acquired_at"],
            evidence=evidence, keywords=keywords, entities=entities,
            scientific_area="volcanology" if volcanic else "environmental_monitoring",
            evidence_text="volcanic_activity" if volcanic else "thermal_anomaly",
            event_status=EventStatus.OBSERVED_FACT,
        )
        return event, volcanic

    @staticmethod
    def _source_observations(members: list[dict[str, Any]]):
        grouped: dict[tuple[str, datetime], list[dict[str, Any]]] = {}
        for item in members:
            window_start, _ = _six_hour_window(item["acquired_at"])
            grouped.setdefault((item["source"], window_start), []).append(item)
        return sorted(grouped.items(), key=lambda pair: pair[0])


__all__ = ["FIRMS_SOURCES", "FirmsCollector"]
