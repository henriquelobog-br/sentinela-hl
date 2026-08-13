"""Conectores HTTP independentes para CAMS, NASA CMR e MERRA-2."""

from __future__ import annotations

import hashlib
import itertools
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

import httpx
import requests
import xarray as xr

from sentinela.core.models import EpistemicStatus, Event, EventStatus

from .config import MonitoredRegion, RealSignalSettings

_UUID_NAMESPACE = UUID("7fcf4d50-1634-4ed3-a510-fb6119d37c01")


def _uuid(identity: str) -> UUID:
    digest = hashlib.sha256((_UUID_NAMESPACE.hex + identity).encode()).digest()
    return UUID(bytes=digest[:16], version=4)


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _window(now: datetime, hours: int) -> tuple[datetime, datetime]:
    end = now.astimezone(timezone.utc)
    return end - timedelta(hours=hours), end


def _six_hour_window(value: datetime) -> tuple[datetime, datetime]:
    start = value.replace(hour=(value.hour // 6) * 6, minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=6)


def _selected_regions(
    regions: tuple[MonitoredRegion, ...], selected: tuple[str, ...]
) -> tuple[MonitoredRegion, ...]:
    if not selected or "all" in selected:
        return regions
    allowed = set(selected)
    result = tuple(region for region in regions if region.id in allowed)
    unknown = allowed - {region.id for region in result}
    if unknown:
        raise ValueError(f"regiões desconhecidas: {', '.join(sorted(unknown))}")
    return result


def _regional_mean(data: Any, region: MonitoredRegion) -> float | None:
    latitude = "latitude" if "latitude" in data.coords else "lat"
    longitude = "longitude" if "longitude" in data.coords else "lon"
    west, south, east, north = region.bbox
    lat_values = data[latitude]
    lon_values = data[longitude]
    lat_start = float(lat_values.isel({latitude: 0}).values)
    lat_end = float(lat_values.isel({latitude: -1}).values)
    lon_start = float(lon_values.isel({longitude: 0}).values)
    lon_end = float(lon_values.isel({longitude: -1}).values)
    lat_slice = slice(north, south) if lat_start > lat_end else slice(south, north)
    lon_slice = slice(east, west) if lon_start > lon_end else slice(west, east)
    subset = data.sel({latitude: lat_slice, longitude: lon_slice})
    if subset.size == 0:
        return None
    value = subset.mean(skipna=True).values
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _datetime_coord(data: Any, fallback: datetime) -> datetime:
    for name in ("valid_time", "time"):
        coordinate = data.coords.get(name)
        if coordinate is not None and coordinate.size == 1:
            return _dt(str(coordinate.values).strip("[]'"))
    return fallback


def _event(
    *, event_type: str, source: str, product: str, region: str,
    window: str, title: str, summary: str, occurred_at: datetime,
    evidence: dict[str, Any], keywords: list[str], entities: list[dict[str, Any]],
    group: str | None = None, scientific_area: str = "atmospheric_science",
    evidence_text: str | None = None, event_status: EventStatus = EventStatus.OBSERVED_FACT,
) -> Event:
    observation = "|".join((source, event_type, product, window, region))
    phenomenon = group or "|".join((source, event_type, product, region))
    return Event(
        id=_uuid("event|" + observation),
        primary_claim_id=_uuid("phenomenon|" + phenomenon),
        title=title,
        summary=summary,
        epistemic_status=EpistemicStatus.CONFIRMED_FACT,
        event_status=event_status,
        category=event_type,
        source=source,
        scientific_area=scientific_area,
        entities=entities,
        keywords=keywords,
        evidence=[{"text": evidence_text or ("mineral_dust" if event_type not in {"new_calipso_granule", "new_modis_aerosol_granule"} else "satellite_observation"), **evidence}],
        occurred_at=occurred_at,
        validated_at=occurred_at,
    )


@dataclass(frozen=True)
class CollectionResult:
    source: str
    received: int = 0
    discarded: int = 0
    duplicates: int = 0
    events: tuple[Event, ...] = ()
    error: str | None = None
    notice: str | None = None
    details: tuple[dict[str, Any], ...] = ()


class CamsCollector:
    def __init__(
        self,
        settings: RealSignalSettings,
        client: Any | None = None,
        records_loader: Any | None = None,
        credentials_path: Path | None = None,
    ):
        self.settings = settings
        self.client = client
        self.records_loader = records_loader
        self.credentials_path = credentials_path or Path.home() / ".cdsapirc"

    def collect(self, now: datetime) -> CollectionResult:
        regions_tuple = _selected_regions(
            self.settings.regions, self.settings.cams_region_ids
        )
        if self.records_loader is None and not self.credentials_path.is_file():
            return CollectionResult(
                source="cams",
                error="credencial ADS ausente em ~/.cdsapirc",
            )
        try:
            rows = (
                self.records_loader(now, regions_tuple)
                if self.records_loader is not None
                else self._official_records(now, regions_tuple)
            )
        except Exception as exc:
            return CollectionResult(
                source="cams",
                error=f"{type(exc).__name__}: falha na autenticação ou consulta ADS",
            )
        regions = {r.id: r for r in regions_tuple}
        events: list[Event] = []
        above_by_window: dict[str, list[tuple[MonitoredRegion, dict[str, Any]]]] = {}
        details: list[dict[str, Any]] = []
        discarded = 0
        seen: set[str] = set()
        duplicates = 0
        for row in rows:
            region = regions.get(str(row.get("region")))
            value = float(row["value"])
            valid_time = _dt(row["valid_time"])
            product = str(row.get("product") or self.settings.cams_variable)
            window_id = str(row.get("window") or valid_time.isoformat())
            key = "|".join((product, window_id, region.id if region else "unknown"))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            details.append({
                "source": "CAMS",
                "region": region.id if region else str(row.get("region")),
                "variable": row.get("variable", self.settings.cams_variable),
                "value": value,
                "unit": row.get("unit"),
                "threshold": self.settings.cams_threshold,
                "window_start": row.get("window_start", valid_time.isoformat()),
                "window_end": row.get("window_end", valid_time.isoformat()),
            })
            if region is None or value < self.settings.cams_threshold:
                discarded += 1
                continue
            above_by_window.setdefault(window_id, []).append((region, row))
            event_type = "brazil_coast_approach" if region.brazil_coast else "dust_transport_forecast"
            title = ("Poeira prevista acima do limiar na costa do Brasil" if region.brazil_coast else f"Aumento de poeira previsto em {region.name_pt}")
            summary = (
                f"O CAMS indica valor agregado de {value:g} {row.get('unit', '')}".rstrip()
                + f", acima do limiar {self.settings.cams_threshold:g}, em {region.name_pt} para a janela de {row.get('window_start', valid_time.isoformat())}. A previsão será reavaliada nas próximas execuções."
            )
            events.append(_event(
                event_type=event_type, source="CAMS", product=product,
                region=region.id, window=f"{self.settings.cams_variable}|{window_id}", title=title, summary=summary,
                occurred_at=valid_time,
                evidence={"source": "CAMS", "product": product, "variable": row.get("variable", self.settings.cams_variable), "region": region.id, "bbox": region.bbox, "window_start": row.get("window_start", valid_time.isoformat()), "window_end": row.get("window_end", valid_time.isoformat()), "value": value, "unit": row.get("unit"), "threshold": self.settings.cams_threshold, "occurred_at": valid_time.isoformat(), "retrieved_at": row.get("retrieved_at", now.isoformat()), "analysis_time": row.get("analysis_time")},
                keywords=["mineral_dust", "atmospheric_transport", "south_atlantic", region.id],
                entities=[{"name": "CAMS", "type": "source"}, {"name": region.name_pt, "type": "region"}],
                event_status=EventStatus.FORECAST,
            ))
        for window_id, values in above_by_window.items():
            ordered = sorted(values, key=lambda item: item[0].order)
            for left, right in zip(ordered, ordered[1:]):
                if right[0].order != left[0].order + 1:
                    continue
                occurred = max(_dt(left[1]["valid_time"]), _dt(right[1]["valid_time"]))
                product = str(right[1].get("product") or self.settings.cams_variable)
                events.append(_event(
                    event_type="dust_corridor_progression", source="CAMS", product=product,
                    region=f"{left[0].id}>{right[0].id}", window=f"{self.settings.cams_variable}|{window_id}",
                    title="Poeira prevista acima do limiar em regioes sucessivas do corredor",
                    summary=f"O CAMS apresenta valores acima do limiar em {left[0].name_pt} e {right[0].name_pt} na janela {window_id}.",
                    occurred_at=occurred,
                    evidence={"source": "CAMS", "product": product, "variable": self.settings.cams_variable, "region": f"{left[0].id}>{right[0].id}", "regions": [left[0].id, right[0].id], "window_start": left[1].get("window_start", window_id), "window_end": right[1].get("window_end", window_id), "value": min(float(left[1]["value"]), float(right[1]["value"])), "values": [left[1]["value"], right[1]["value"]], "threshold": self.settings.cams_threshold, "unit": right[1].get("unit"), "occurred_at": occurred.isoformat(), "retrieved_at": right[1].get("retrieved_at", now.isoformat())},
                    keywords=["mineral_dust", "atmospheric_transport", "south_atlantic"],
                    entities=[{"name": "CAMS", "type": "source"}],
                    event_status=EventStatus.FORECAST,
                ))
                break
        return CollectionResult(source="cams", received=len(rows), discarded=discarded, duplicates=duplicates, events=tuple(events), details=tuple(details))

    def _official_records(
        self, now: datetime, regions: tuple[MonitoredRegion, ...]
    ) -> list[dict[str, Any]]:
        import cdsapi

        available = now - timedelta(hours=6)
        cycle_hour = 12 if available.hour >= 12 else 0
        reference = available.replace(
            hour=cycle_hour, minute=0, second=0, microsecond=0
        )
        north = max(region.bbox[3] for region in regions)
        west = min(region.bbox[0] for region in regions)
        south = min(region.bbox[1] for region in regions)
        east = max(region.bbox[2] for region in regions)
        request = {
            "variable": [self.settings.cams_variable],
            "date": [reference.strftime("%Y-%m-%d")],
            "time": [reference.strftime("%H:%M")],
            "leadtime_hour": [str(value) for value in self.settings.cams_forecast_hours],
            "type": ["forecast"],
            "data_format": "netcdf_zip",
            "area": [north, west, south, east],
        }
        client = self.client or cdsapi.Client()
        records: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="sentinela-cams-") as directory:
            archive = Path(directory) / "cams.zip"
            client.retrieve(self.settings.cams_dataset, request, str(archive))
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(directory)
            for path in sorted(Path(directory).rglob("*.nc*")):
                with xr.open_dataset(path) as dataset:
                    records.extend(
                        self._dataset_records(dataset, reference, now, regions)
                    )
        return records

    def _dataset_records(
        self,
        dataset: Any,
        reference: datetime,
        retrieved_at: datetime,
        regions: tuple[MonitoredRegion, ...],
    ) -> list[dict[str, Any]]:
        if self.settings.cams_variable in dataset.data_vars:
            data = dataset[self.settings.cams_variable]
        elif len(dataset.data_vars) == 1:
            data = next(iter(dataset.data_vars.values()))
        else:
            raise ValueError("variável CAMS ausente no arquivo retornado")
        latitude = "latitude" if "latitude" in data.coords else "lat"
        longitude = "longitude" if "longitude" in data.coords else "lon"
        varying = [dim for dim in data.dims if dim not in {latitude, longitude}]
        combinations = itertools.product(
            *(range(data.sizes[dim]) for dim in varying)
        ) if varying else [()]
        records: list[dict[str, Any]] = []
        for indexes in combinations:
            piece = data.isel(dict(zip(varying, indexes)))
            fallback_index = indexes[-1] if indexes else 0
            fallback_hour = self.settings.cams_forecast_hours[min(fallback_index, len(self.settings.cams_forecast_hours) - 1)]
            valid_time = _datetime_coord(
                piece, reference + timedelta(hours=fallback_hour)
            )
            for region in regions:
                value = _regional_mean(piece, region)
                if value is None:
                    continue
                records.append({
                    "region": region.id,
                    "value": value,
                    "unit": data.attrs.get("units", "1"),
                    "valid_time": valid_time.isoformat(),
                    "window": valid_time.isoformat(),
                    "window_start": valid_time.isoformat(),
                    "window_end": (valid_time + timedelta(hours=1)).isoformat(),
                    "analysis_time": reference.isoformat(),
                    "retrieved_at": retrieved_at.isoformat(),
                    "product": self.settings.cams_dataset,
                    "variable": self.settings.cams_variable,
                })
        return records


class CmrCollector:
    def __init__(self, settings: RealSignalSettings, client: Any | None = None, processed_ids: Iterable[str] = ()):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)
        self.processed_ids = set(processed_ids)

    def collect(self, now: datetime) -> CollectionResult:
        start, end = _window(now, self.settings.window_hours)
        received = discarded = duplicates = 0
        collections = (("calipso", self.settings.cmr_calipso_collection_ids), ("modis", self.settings.cmr_modis_collection_ids))
        bbox = (-55, -40, 22, 5)
        granules: dict[tuple[str, str, str], dict[str, Any]] = {}
        for kind, ids in collections:
            for collection_id in ids:
                response = self.client.get(
                    f"{self.settings.cmr_api_url.rstrip('/')}/granules.json",
                    params={"collection_concept_id": collection_id, "updated_since": start.isoformat(), "bounding_box": ",".join(str(v) for v in bbox), "page_size": self.settings.cmr_page_size, "sort_key": "-revision_date"},
                    headers={"client-id": "sentinela-hl"},
                )
                response.raise_for_status()
                rows = response.json().get("feed", {}).get("entry", [])
                received += len(rows)
                for row in rows:
                    granule_id = str(row.get("id") or row.get("producer_granule_id") or row.get("title"))
                    granule_ur = str(row.get("producer_granule_id") or row.get("title") or granule_id)
                    revision = str(row.get("updated") or row.get("revision_date") or row.get("time_start"))
                    identity = f"{collection_id}|{granule_id}|{revision}"
                    if identity in self.processed_ids:
                        duplicates += 1
                        continue
                    occurred = _dt(row.get("time_start") or row.get("updated"))
                    region = str(row.get("region") or "south_atlantic")
                    key = (collection_id, region, granule_id)
                    current = granules.get(key)
                    if current is not None:
                        duplicates += 1
                        if _dt(current["revision"]) >= _dt(revision):
                            continue
                    granules[key] = {
                        "kind": kind,
                        "collection_id": collection_id,
                        "region": region,
                        "granule_id": granule_id,
                        "granule_ur": granule_ur,
                        "revision": revision,
                        "occurred_at": occurred,
                        "time_start": row.get("time_start"),
                        "time_end": row.get("time_end"),
                    }

        grouped: dict[tuple[str, str, datetime], list[dict[str, Any]]] = {}
        for granule in granules.values():
            window_start, _ = _six_hour_window(granule["occurred_at"])
            grouped.setdefault(
                (granule["collection_id"], granule["region"], window_start), []
            ).append(granule)

        events: list[Event] = []
        for (collection_id, region, window_start), members in sorted(grouped.items()):
            members.sort(key=lambda item: (item["occurred_at"], item["granule_id"]))
            window_end = window_start + timedelta(hours=6)
            earliest = members[0]["occurred_at"]
            latest = members[-1]["occurred_at"]
            kind = members[0]["kind"]
            instrument = "CALIPSO/CALIOP" if kind == "calipso" else "MODIS"
            event_type = "new_calipso_granule" if kind == "calipso" else "new_modis_aerosol_granule"
            count = len(members)
            noun = "produto" if count == 1 else "produtos"
            adjective = "Novo" if count == 1 else "Novos"
            availability = "disponível" if count == 1 else "disponíveis"
            region_name = "Atlântico Sul" if region == "south_atlantic" else region
            article = "o " if region == "south_atlantic" else ""
            title = f"{adjective} {noun} {instrument} {availability} para {article}{region_name}"
            reference = "desse produto" if count == 1 else "desses produtos"
            summary = (
                f"O NASA CMR registrou {count} {noun} da coleção {collection_id} "
                f"entre {window_start:%H:%M} e {window_end:%H:%M} UTC na região "
                f"monitorada ({region_name}). "
                f"A disponibilidade {reference} não confirma "
                "presença de poeira."
            )
            member_event_ids = [
                str(_uuid(f"cmr-granule|{collection_id}|{region}|{item['granule_id']}"))
                for item in members
            ]
            granule_evidence = [
                {
                    "event_id": event_id,
                    "granule_concept_id": item["granule_id"],
                    "granule_ur": item["granule_ur"],
                    "revision": item["revision"],
                    "time_start": item["time_start"],
                    "time_end": item["time_end"],
                }
                for event_id, item in zip(member_event_ids, members)
            ]
            window_id = window_start.isoformat()
            representative_event_id = str(_uuid(
                "event|" + "|".join((
                    "NASA CMR", event_type, collection_id, window_id, region
                ))
            ))
            events.append(_event(
                event_type=event_type,
                source="NASA CMR",
                product=collection_id,
                region=region,
                window=window_id,
                title=title,
                summary=summary,
                occurred_at=latest,
                group=f"cmr:{collection_id}:{region}:{window_id}",
                evidence={
                    "source": "NASA CMR",
                    "collection_concept_id": collection_id,
                    "region": region,
                    "bbox": bbox,
                    "window_start_utc": window_start.isoformat(),
                    "window_end_utc": window_end.isoformat(),
                    "earliest_occurred_at": earliest.isoformat(),
                    "latest_occurred_at": latest.isoformat(),
                    "granule_count": count,
                    "representative_event_id": representative_event_id,
                    "member_event_ids": member_event_ids,
                    "granules": granule_evidence,
                    "evidence_type": "new_products_available",
                },
                keywords=["aerosols", "satellite_observation", "satellite_instruments", "south_atlantic"],
                entities=[{"name": instrument, "type": "instrument"}, {"name": "NASA CMR", "type": "source"}],
                event_status=EventStatus.CATALOG_RECORD,
            ))
        return CollectionResult(source="cmr", received=received, discarded=discarded, duplicates=duplicates, events=tuple(events))


class Merra2Collector:
    def __init__(
        self,
        settings: RealSignalSettings,
        client: Any | None = None,
        dataset_opener: Any | None = None,
        credentials_path: Path | None = None,
    ):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)
        self.dataset_opener = dataset_opener
        self.credentials_path = credentials_path or Path.home() / ".netrc"

    def collect(self, now: datetime) -> CollectionResult:
        regions = _selected_regions(
            self.settings.regions, self.settings.merra2_region_ids
        )
        try:
            response = self.client.get(
                f"{self.settings.cmr_api_url.rstrip('/')}/granules.json",
                params={
                    "collection_concept_id": self.settings.merra2_collection,
                    "sort_key": "-start_date",
                    "page_size": 1,
                },
                headers={"client-id": "sentinela-hl"},
            )
            response.raise_for_status()
            granules = response.json().get("feed", {}).get("entry", [])
        except Exception as exc:
            return CollectionResult(
                source="merra2",
                error=f"{type(exc).__name__}: falha na consulta ao catálogo GES DISC",
            )
        if not granules:
            return CollectionResult(
                source="merra2",
                notice="produto MERRA-2 ainda não disponível",
            )
        granule_metadata = granules[0]
        granule_end = _dt(
            granule_metadata.get("time_end")
            or granule_metadata.get("time_start")
        )
        latency_hours = (now - granule_end).total_seconds() / 3600
        if latency_hours > self.settings.merra2_max_latency_hours:
            return CollectionResult(
                source="merra2",
                received=1,
                discarded=1,
                notice=(
                    "produto MERRA-2 disponível, mas fora da latência máxima "
                    "configurada"
                ),
                details=({
                    "source": "MERRA-2",
                    "collection": self.settings.merra2_collection,
                    "variable": self.settings.merra2_variable,
                    "latency_hours": latency_hours,
                    "max_latency_hours": self.settings.merra2_max_latency_hours,
                },),
            )
        opendap_url = next(
            (
                link.get("href")
                for link in granule_metadata.get("links", [])
                if "OPENDAP" in str(link.get("title", "")).upper()
                or "opendap.earthdata.nasa.gov" in str(link.get("href", ""))
            ),
            None,
        )
        if not opendap_url:
            return CollectionResult(
                source="merra2",
                received=1,
                notice="granule MERRA-2 sem URL OPeNDAP oficial",
            )
        if self.dataset_opener is None and not self.credentials_path.is_file():
            return CollectionResult(
                source="merra2",
                received=1,
                error="credencial Earthdata ausente em ~/.netrc",
            )
        try:
            dataset = (
                self.dataset_opener(opendap_url)
                if self.dataset_opener is not None
                else self._open_official_dataset(opendap_url)
            )
            with dataset:
                if self.settings.merra2_variable not in dataset.data_vars:
                    return CollectionResult(
                        source="merra2",
                        received=1,
                        notice=(
                            f"variável {self.settings.merra2_variable} ausente "
                            "no produto MERRA-2"
                        ),
                    )
                data = dataset[self.settings.merra2_variable]
                time_dimension = "time" if "time" in data.dims else None
                piece = data.isel({time_dimension: -1}) if time_dimension else data
                observed = _datetime_coord(piece, granule_end)
                unit = data.attrs.get("units", "1")
                rows = []
                for region in regions:
                    value = _regional_mean(piece, region)
                    if value is not None:
                        rows.append({
                            "region": region.id,
                            "value": value,
                            "unit": unit,
                            "observed_at": observed.isoformat(),
                        })
        except Exception as exc:
            return CollectionResult(
                source="merra2",
                received=1,
                error=f"{type(exc).__name__}: falha na autenticação ou leitura OPeNDAP",
            )
        events: list[Event] = []
        details: list[dict[str, Any]] = []
        discarded = 0
        for row in rows:
            observed = _dt(row["observed_at"])
            region = next(
                (item for item in regions if item.id == str(row.get("region"))),
                None,
            )
            value = float(row["value"])
            details.append({
                "source": "MERRA-2",
                "collection": self.settings.merra2_collection,
                "variable": self.settings.merra2_variable,
                "region": region.id if region else str(row.get("region")),
                "value": value,
                "unit": row.get("unit"),
                "threshold": self.settings.merra2_threshold,
                "latency_hours": latency_hours,
            })
            if region is None or value < self.settings.merra2_threshold:
                discarded += 1
                continue
            product = self.settings.merra2_collection
            variable = self.settings.merra2_variable
            granule = str(
                granule_metadata.get("producer_granule_id")
                or granule_metadata.get("id")
            )
            window_start = observed.replace(minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(hours=1)
            events.append(_event(
                event_type="merra2_dust_confirmation", source="MERRA-2", product=product,
                region=region.id, window=f"{variable}|{window_start.isoformat()}",
                group=f"merra2:{product}:{variable}:{region.id}",
                title="Carga de poeira elevada confirmada pelo MERRA-2",
                summary=f"O produto {product} registra valor agregado de {variable} igual a {value:g} {row.get('unit', '')}".rstrip() + f", acima do limiar {self.settings.merra2_threshold:g}, em {region.name_pt} para {window_start.isoformat()}.",
                occurred_at=observed,
                evidence={"source": "MERRA-2", "product": product, "collection": product, "granule_id": granule, "variable": variable, "region": region.id, "bbox": region.bbox, "window_start": window_start.isoformat(), "window_end": window_end.isoformat(), "value": value, "threshold": self.settings.merra2_threshold, "unit": row.get("unit"), "occurred_at": observed.isoformat(), "retrieved_at": now.isoformat(), "latency_hours": latency_hours},
                keywords=["mineral_dust", "aerosol_optical_depth", "reanalysis", "south_atlantic", region.id],
                entities=[{"name": "MERRA-2", "type": "source"}, {"name": region.name_pt, "type": "region"}],
                event_status=EventStatus.OBSERVED_FACT,
            ))
        return CollectionResult(source="merra2", received=len(rows), discarded=discarded, events=tuple(events), details=tuple(details))

    @staticmethod
    def _open_official_dataset(url: str) -> Any:
        session = requests.Session()
        session.trust_env = True
        return xr.open_dataset(
            url,
            engine="pydap",
            backend_kwargs={"session": session},
        )


__all__ = ["CamsCollector", "CmrCollector", "CollectionResult", "Merra2Collector"]
