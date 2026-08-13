"""Configuracao ambiental das fontes de sinais reais."""

from __future__ import annotations

import json
from dataclasses import dataclass
from os import environ


@dataclass(frozen=True)
class MonitoredRegion:
    id: str
    name_pt: str
    bbox: tuple[float, float, float, float]
    order: int
    brazil_coast: bool = False


@dataclass(frozen=True)
class ForecastLocation:
    id: str
    name_pt: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class CoopsStation:
    id: str
    name: str
    latitude: float
    longitude: float
    products: tuple[str, ...]
    datum: str = "MLLW"
    current_bin: int | None = None
    temperature_baseline_c: float | None = None


@dataclass(frozen=True)
class NdbcStation:
    id: str
    name: str
    latitude: float
    longitude: float


DEFAULT_REGIONS = (
    MonitoredRegion("southern_africa", "Namibia e Angola", (8, -30, 22, -10), 0),
    MonitoredRegion("east_south_atlantic", "Atlantico Sul oriental", (-5, -35, 10, -10), 1),
    MonitoredRegion("central_south_atlantic", "Atlantico Sul central", (-25, -35, -5, -10), 2),
    MonitoredRegion("brazil_coast", "costa sudeste do Brasil", (-45, -30, -30, -15), 3, True),
    MonitoredRegion("southeast_brazil", "Espirito Santo e Sudeste", (-43, -25, -38, -17), 4, True),
)

_LOCATION_NAMES = {
    "vitoria_es": "Vitória",
    "south_atlantic": "Atlântico Sul central",
    "namibia_coast": "costa da Namíbia",
    "israel": "Israel",
    "espirito_santo_coast": "costa do Espírito Santo",
    "eastern_mediterranean": "Mediterrâneo oriental",
    "southeast_brazil": "Espírito Santo e Sudeste",
    "amazon_basin": "Amazônia",
    "namibia": "Namíbia",
    "angola": "Angola",
}

DEFAULT_WEATHER_LOCATIONS = (
    ForecastLocation("vitoria_es", "Vitória", -20.3155, -40.3128),
    ForecastLocation("south_atlantic", "Atlântico Sul central", -25.0, -20.0),
    ForecastLocation("namibia_coast", "costa da Namíbia", -23.0, 14.5),
    ForecastLocation("israel", "Israel", 31.5, 34.8),
)

DEFAULT_MARINE_LOCATIONS = (
    ForecastLocation("espirito_santo_coast", "costa do Espírito Santo", -20.5, -39.5),
    ForecastLocation("south_atlantic", "Atlântico Sul central", -25.0, -20.0),
    ForecastLocation("namibia_coast", "costa da Namíbia", -23.0, 13.5),
    ForecastLocation("eastern_mediterranean", "Mediterrâneo oriental", 32.0, 34.5),
)

DEFAULT_CLIMATE_LOCATIONS = (
    ForecastLocation("southeast_brazil", "Espírito Santo e Sudeste", -20.3155, -40.3128),
    ForecastLocation("amazon_basin", "Amazônia", -3.1190, -60.0217),
    ForecastLocation("namibia", "Namíbia", -22.5609, 17.0658),
    ForecastLocation("angola", "Angola", -8.8390, 13.2894),
    ForecastLocation("israel", "Israel", 31.5, 34.8),
    ForecastLocation("eastern_mediterranean", "Mediterrâneo oriental", 34.9, 33.0),
)

DEFAULT_COOPS_STATIONS = (
    CoopsStation(
        "8724580", "Key West, FL", 24.5557, -81.8079,
        ("water_level", "predictions", "water_temperature", "air_temperature", "wind"),
    ),
    CoopsStation(
        "9755371", "San Juan, La Puntilla, PR", 18.458944, -66.11642,
        ("water_level", "predictions", "water_temperature", "air_temperature", "wind"),
    ),
    CoopsStation(
        "cb1401", "Newport News Shipbuilding, VA", 36.983799, -76.443604,
        ("currents",), current_bin=30,
    ),
)

DEFAULT_NDBC_STATIONS = (
    NdbcStation("41013", "Frying Pan Shoals, NC", 33.436, -77.764),
    NdbcStation("41043", "NE Puerto Rico", 21.09, -64.864),
    NdbcStation("41121", "Arecibo, Puerto Rico", 18.491, -66.701),
)


def _float(name: str, default: float) -> float:
    return float(environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(environ.get(name, default))


def _regions() -> tuple[MonitoredRegion, ...]:
    raw = environ.get("SENTINELA_SIGNAL_REGIONS_JSON")
    if not raw:
        return DEFAULT_REGIONS
    values = json.loads(raw)
    return tuple(
        MonitoredRegion(
            id=item["id"],
            name_pt=item["name_pt"],
            bbox=tuple(float(value) for value in item["bbox"]),
            order=int(item["order"]),
            brazil_coast=bool(item.get("brazil_coast", False)),
        )
        for item in values
    )


def _locations(name: str, default: tuple[ForecastLocation, ...]) -> tuple[ForecastLocation, ...]:
    raw = environ.get(name)
    if not raw:
        return default
    locations = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        identifier, coordinates = entry.split(":", 1)
        latitude, longitude = coordinates.split(",", 1)
        identifier = identifier.strip()
        locations.append(ForecastLocation(
            id=identifier,
            name_pt=_LOCATION_NAMES.get(identifier, identifier.replace("_", " ")),
            latitude=float(latitude),
            longitude=float(longitude),
        ))
    return tuple(locations)


def _coops_stations() -> tuple[CoopsStation, ...]:
    raw = environ.get("SENTINELA_COOPS_STATIONS_JSON")
    if not raw:
        return DEFAULT_COOPS_STATIONS
    return tuple(CoopsStation(
        id=str(item["id"]), name=str(item["name"]),
        latitude=float(item["latitude"]), longitude=float(item["longitude"]),
        products=tuple(str(value) for value in item["products"]),
        datum=str(item.get("datum", "MLLW")),
        current_bin=int(item["current_bin"]) if item.get("current_bin") is not None else None,
        temperature_baseline_c=float(item["temperature_baseline_c"]) if item.get("temperature_baseline_c") is not None else None,
    ) for item in json.loads(raw))


def _ndbc_stations() -> tuple[NdbcStation, ...]:
    raw = environ.get("SENTINELA_NDBC_STATIONS_JSON")
    if not raw:
        return DEFAULT_NDBC_STATIONS
    return tuple(NdbcStation(
        id=str(item["id"]), name=str(item["name"]),
        latitude=float(item["latitude"]), longitude=float(item["longitude"]),
    ) for item in json.loads(raw))


@dataclass(frozen=True)
class RealSignalSettings:
    interval_hours: int
    window_hours: int
    timeout_seconds: float
    researcher_id: str
    regions: tuple[MonitoredRegion, ...]
    cams_dataset: str
    cams_threshold: float
    cams_variable: str
    cams_forecast_hours: tuple[int, ...]
    cams_region_ids: tuple[str, ...]
    cmr_api_url: str
    cmr_page_size: int
    cmr_calipso_collection_ids: tuple[str, ...]
    cmr_modis_collection_ids: tuple[str, ...]
    merra2_collection: str
    merra2_variable: str
    merra2_region_ids: tuple[str, ...]
    merra2_threshold: float
    merra2_max_latency_hours: int
    usgs_min_magnitude: float
    usgs_lookback_hours: int
    usgs_limit: int
    weather_locations: tuple[ForecastLocation, ...]
    weather_forecast_hours: int
    weather_wind_gust_threshold_kmh: float
    weather_precipitation_threshold_mm_h: float
    weather_visibility_threshold_m: float
    weather_temperature_high_c: float
    weather_temperature_low_c: float
    marine_locations: tuple[ForecastLocation, ...]
    marine_forecast_hours: int
    marine_wave_height_threshold_m: float
    marine_swell_height_threshold_m: float
    marine_wave_period_threshold_s: float
    climate_locations: tuple[ForecastLocation, ...]
    climate_model: str
    climate_baseline_start: str
    climate_baseline_end: str
    climate_target_start: str
    climate_target_end: str
    climate_temperature_anomaly_threshold_c: float
    climate_precipitation_anomaly_threshold_fraction: float
    climate_precipitation_anomaly_threshold_mm: float
    climate_precipitation_min_baseline_mm: float
    coops_stations: tuple[CoopsStation, ...]
    coops_lookback_hours: int
    coops_water_level_threshold_m: float
    coops_current_threshold_ms: float
    coops_temp_anomaly_c: float
    ndbc_stations: tuple[NdbcStation, ...]
    ndbc_lookback_hours: int
    ndbc_wave_height_threshold_m: float
    ndbc_swell_period_threshold_s: float
    ndbc_wind_threshold_ms: float
    nws_user_agent: str
    donki_api_key: str
    donki_lookback_days: int
    volcano_lookback_hours: int
    gvp_feature_count: int
    gdelt_min_sources: int
    gdelt_min_mentions: int
    gdelt_lookback_minutes: int
    gdelt_max_groups: int
    acled_username: str
    acled_password: str
    acled_lookback_days: int
    acled_limit: int
    firms_map_key: str
    firms_day_range: int
    firms_volcano_radius_km: float
    firms_region_boxes: str
    firms_max_clusters: int
    firms_occurrence_grid_degrees: float
    firms_max_clusters_per_region: int

    @classmethod
    def from_env(cls) -> "RealSignalSettings":
        interval = _int("SENTINELA_SIGNAL_INTERVAL_HOURS", 6)
        if interval < 1:
            raise ValueError("SENTINELA_SIGNAL_INTERVAL_HOURS deve ser >= 1")
        acled_lookback_days = _int("SENTINELA_ACLED_LOOKBACK_DAYS", 3)
        acled_limit = _int("SENTINELA_ACLED_LIMIT", 5000)
        if acled_lookback_days < 1:
            raise ValueError("SENTINELA_ACLED_LOOKBACK_DAYS deve ser >= 1")
        if not 1 <= acled_limit <= 5000:
            raise ValueError("SENTINELA_ACLED_LIMIT deve estar entre 1 e 5000")
        return cls(
            interval_hours=interval,
            window_hours=_int("SENTINELA_SIGNAL_WINDOW_HOURS", 24),
            timeout_seconds=_float("SENTINELA_SIGNAL_TIMEOUT_SECONDS", 30.0),
            researcher_id=environ.get("SENTINELA_RESEARCHER_ID", "hl"),
            regions=_regions(),
            cams_dataset=environ.get("SENTINELA_CAMS_DATASET", "cams-global-atmospheric-composition-forecasts"),
            cams_threshold=_float("SENTINELA_CAMS_THRESHOLD", 0.2),
            cams_variable=environ.get("SENTINELA_CAMS_VARIABLE", "dust_aerosol_optical_depth_550nm"),
            cams_forecast_hours=tuple(int(value) for value in environ.get("SENTINELA_CAMS_FORECAST_HOURS", "0,6,12,18,24").split(",") if value.strip()),
            cams_region_ids=tuple(value.strip() for value in environ.get("SENTINELA_CAMS_REGION", "all").split(",") if value.strip()),
            cmr_api_url=environ.get("NASA_CMR_API_URL", "https://cmr.earthdata.nasa.gov/search"),
            cmr_page_size=_int("SENTINELA_CMR_PAGE_SIZE", 20),
            cmr_calipso_collection_ids=tuple(filter(None, environ.get("SENTINELA_CMR_CALIPSO_COLLECTION_IDS", "C3551627908-LARC_CLOUD").split(","))),
            cmr_modis_collection_ids=tuple(filter(None, environ.get("SENTINELA_CMR_MODIS_COLLECTION_IDS", "C1443533440-LAADS").split(","))),
            merra2_collection=environ.get("SENTINELA_MERRA2_COLLECTION", "C1276812830-GES_DISC"),
            merra2_variable=environ.get("SENTINELA_MERRA2_VARIABLE", "DUEXTTAU"),
            merra2_region_ids=tuple(value.strip() for value in environ.get("SENTINELA_MERRA2_REGION", "all").split(",") if value.strip()),
            merra2_threshold=_float("SENTINELA_MERRA2_THRESHOLD", 0.2),
            merra2_max_latency_hours=_int("SENTINELA_MERRA2_MAX_LATENCY_HOURS", 1080),
            usgs_min_magnitude=_float("SENTINELA_USGS_MIN_MAGNITUDE", 4.5),
            usgs_lookback_hours=_int("SENTINELA_USGS_LOOKBACK_HOURS", 24),
            usgs_limit=_int("SENTINELA_USGS_LIMIT", 200),
            weather_locations=_locations("SENTINELA_WEATHER_LOCATIONS", DEFAULT_WEATHER_LOCATIONS),
            weather_forecast_hours=_int("SENTINELA_WEATHER_FORECAST_HOURS", 48),
            weather_wind_gust_threshold_kmh=_float("SENTINELA_WEATHER_WIND_GUST_THRESHOLD_KMH", 70),
            weather_precipitation_threshold_mm_h=_float("SENTINELA_WEATHER_PRECIPITATION_THRESHOLD_MM_H", 30),
            weather_visibility_threshold_m=_float("SENTINELA_WEATHER_VISIBILITY_THRESHOLD_M", 3000),
            weather_temperature_high_c=_float("SENTINELA_WEATHER_TEMPERATURE_HIGH_C", 40),
            weather_temperature_low_c=_float("SENTINELA_WEATHER_TEMPERATURE_LOW_C", 0),
            marine_locations=_locations("SENTINELA_MARINE_LOCATIONS", DEFAULT_MARINE_LOCATIONS),
            marine_forecast_hours=_int("SENTINELA_MARINE_FORECAST_HOURS", 48),
            marine_wave_height_threshold_m=_float("SENTINELA_MARINE_WAVE_HEIGHT_THRESHOLD_M", 3.0),
            marine_swell_height_threshold_m=_float("SENTINELA_MARINE_SWELL_HEIGHT_THRESHOLD_M", 2.5),
            marine_wave_period_threshold_s=_float("SENTINELA_MARINE_WAVE_PERIOD_THRESHOLD_S", 14),
            climate_locations=_locations("SENTINELA_CLIMATE_LOCATIONS", DEFAULT_CLIMATE_LOCATIONS),
            climate_model=environ.get("SENTINELA_CLIMATE_MODEL", "EC_Earth3P_HR").strip(),
            climate_baseline_start=environ.get("SENTINELA_CLIMATE_BASELINE_START", "1991-01-01"),
            climate_baseline_end=environ.get("SENTINELA_CLIMATE_BASELINE_END", "2020-12-31"),
            climate_target_start=environ.get("SENTINELA_CLIMATE_TARGET_START", "2040-01-01"),
            climate_target_end=environ.get("SENTINELA_CLIMATE_TARGET_END", "2049-12-31"),
            climate_temperature_anomaly_threshold_c=_float("SENTINELA_CLIMATE_TEMPERATURE_ANOMALY_THRESHOLD_C", 2.0),
            climate_precipitation_anomaly_threshold_fraction=_float("SENTINELA_CLIMATE_PRECIPITATION_ANOMALY_THRESHOLD_FRACTION", 0.25),
            climate_precipitation_anomaly_threshold_mm=_float("SENTINELA_CLIMATE_PRECIPITATION_ANOMALY_THRESHOLD_MM", 20.0),
            climate_precipitation_min_baseline_mm=_float("SENTINELA_CLIMATE_PRECIPITATION_MIN_BASELINE_MM", 20.0),
            coops_stations=_coops_stations(),
            coops_lookback_hours=_int("SENTINELA_COOPS_LOOKBACK_HOURS", 24),
            coops_water_level_threshold_m=_float("SENTINELA_COOPS_WATER_LEVEL_THRESHOLD_M", 1.0),
            coops_current_threshold_ms=_float("SENTINELA_COOPS_CURRENT_THRESHOLD_MS", 1.0),
            coops_temp_anomaly_c=_float("SENTINELA_COOPS_TEMP_ANOMALY_C", 3.0),
            ndbc_stations=_ndbc_stations(),
            ndbc_lookback_hours=_int("SENTINELA_NDBC_LOOKBACK_HOURS", 24),
            ndbc_wave_height_threshold_m=_float("SENTINELA_NDBC_WAVE_HEIGHT_THRESHOLD_M", 3.0),
            ndbc_swell_period_threshold_s=_float("SENTINELA_NDBC_SWELL_PERIOD_THRESHOLD_S", 14.0),
            ndbc_wind_threshold_ms=_float("SENTINELA_NDBC_WIND_THRESHOLD_MS", 17.2),
            nws_user_agent=environ.get(
                "SENTINELA_NWS_USER_AGENT",
                "(sentinela-hl, https://github.com/henriquelobog-br/sentinela-hl)",
            ).strip(),
            donki_api_key=environ.get("NASA_API_KEY", "DEMO_KEY"),
            donki_lookback_days=_int("SENTINELA_DONKI_LOOKBACK_DAYS", 3),
            volcano_lookback_hours=_int("SENTINELA_VOLCANO_LOOKBACK_HOURS", 72),
            gvp_feature_count=_int("SENTINELA_GVP_FEATURE_COUNT", 2000),
            gdelt_min_sources=_int("SENTINELA_GDELT_MIN_SOURCES", 2),
            gdelt_min_mentions=_int("SENTINELA_GDELT_MIN_MENTIONS", 3),
            gdelt_lookback_minutes=_int("SENTINELA_GDELT_LOOKBACK_MINUTES", 60),
            gdelt_max_groups=_int("SENTINELA_GDELT_MAX_GROUPS", 12),
            acled_username=environ.get("SENTINELA_ACLED_USERNAME", "").strip(),
            acled_password=environ.get("SENTINELA_ACLED_PASSWORD", ""),
            acled_lookback_days=acled_lookback_days,
            acled_limit=acled_limit,
            firms_map_key=environ.get("SENTINELA_FIRMS_MAP_KEY", "").strip(),
            firms_day_range=_int("SENTINELA_FIRMS_DAY_RANGE", 1),
            firms_volcano_radius_km=_float("SENTINELA_FIRMS_VOLCANO_RADIUS_KM", 25.0),
            firms_region_boxes=environ.get("SENTINELA_FIRMS_REGION_BOXES", "").strip(),
            firms_max_clusters=_int("SENTINELA_FIRMS_MAX_CLUSTERS", 50),
            firms_occurrence_grid_degrees=_float("SENTINELA_FIRMS_OCCURRENCE_GRID_DEGREES", 0.15),
            firms_max_clusters_per_region=_int("SENTINELA_FIRMS_MAX_CLUSTERS_PER_REGION", 10),
        )


__all__ = [
    "CoopsStation", "DEFAULT_CLIMATE_LOCATIONS", "DEFAULT_COOPS_STATIONS", "DEFAULT_MARINE_LOCATIONS",
    "DEFAULT_NDBC_STATIONS", "DEFAULT_REGIONS", "DEFAULT_WEATHER_LOCATIONS",
    "ForecastLocation", "MonitoredRegion", "NdbcStation", "RealSignalSettings",
]
