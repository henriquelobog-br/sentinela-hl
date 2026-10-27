from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import eccodes
import numpy as np

from .grid import RectilinearGrid


SUPPORTED_THRESHOLDS_MM = frozenset({1, 5, 10, 20, 25, 50, 100})
EXPECTED_GRID_RESOLUTION_DEG = 0.25
MAX_LEAD_HOURS = 240
SUPPORTED_LATITUDE_MIN = -60.0
SUPPORTED_LATITUDE_MAX = 60.0
EXPECTED_PROBABILITY_TYPE = 3
EXPECTED_THRESHOLD_OPERATOR = ">"


class ECMWFGRIBContractError(ValueError):
    pass


@dataclass(frozen=True)
class DecodedECMWFForecastField:
    model: str
    run_time: datetime
    valid_from: datetime
    valid_to: datetime
    lead_hours: int
    threshold_mm: int
    threshold_operator: str
    probability_type: int
    probability_lower_limit: float
    latitudes: np.ndarray
    longitudes: np.ndarray
    probability_field: np.ndarray
    grid_resolution_deg: float
    grid_sha256: str
    forecast_field_sha256: str
    artifact_sha256: str
    source_uri: str
    retrieved_at: datetime
    raw_grib_metadata: dict[str, Any]


def _get(gid: Any, key: str) -> Any:
    try:
        return eccodes.codes_get(gid, key)
    except Exception as exc:
        raise ECMWFGRIBContractError(
            f"required GRIB key unavailable: {key}"
        ) from exc


def _utc_from_date_time(date_value: int, time_value: int) -> datetime:
    text = f"{int(date_value):08d}{int(time_value):04d}"
    try:
        parsed = datetime.strptime(text, "%Y%m%d%H%M")
    except ValueError as exc:
        raise ECMWFGRIBContractError(
            f"invalid GRIB date/time: {text}"
        ) from exc
    return parsed.replace(tzinfo=timezone.utc)


def _field_sha256(field: np.ndarray) -> str:
    canonical = np.asarray(field, dtype="<f8", order="C").copy()
    canonical[np.isnan(canonical)] = np.nan
    return sha256(canonical.tobytes(order="C")).hexdigest()


def _decode_missing(gid: Any, values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64).copy()
    bitmap_present = int(_get(gid, "bitmapPresent"))

    if bitmap_present == 0:
        return result

    bitmap = np.asarray(
        eccodes.codes_get_array(gid, "bitmap"),
        dtype=np.int64,
    )

    if bitmap.shape != result.shape:
        raise ECMWFGRIBContractError(
            "bitmap/value cardinality mismatch"
        )

    result[bitmap == 0] = np.nan

    number_missing = int(_get(gid, "numberOfMissing"))
    recovered_missing = int(np.isnan(result).sum())

    if recovered_missing != number_missing:
        raise ECMWFGRIBContractError(
            "GRIB missing count does not match bitmap"
        )

    return result


def _canonical_grid_and_field(
    gid: Any,
    *,
    roi_lat_min: float,
    roi_lat_max: float,
    roi_lon_min: float,
    roi_lon_max: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if int(_get(gid, "edition")) != 2:
        raise ECMWFGRIBContractError("GRIB edition must be 2")

    if str(_get(gid, "gridType")) != "regular_ll":
        raise ECMWFGRIBContractError(
            "ECMWF probability grid must be regular_ll"
        )

    ni = int(_get(gid, "Ni"))
    nj = int(_get(gid, "Nj"))

    if ni <= 0 or nj <= 0:
        raise ECMWFGRIBContractError("invalid grid dimensions")

    di = float(_get(gid, "iDirectionIncrementInDegrees"))
    dj = float(_get(gid, "jDirectionIncrementInDegrees"))

    if not np.isclose(di, EXPECTED_GRID_RESOLUTION_DEG):
        raise ECMWFGRIBContractError(
            f"unexpected longitude resolution: {di}"
        )

    if not np.isclose(dj, EXPECTED_GRID_RESOLUTION_DEG):
        raise ECMWFGRIBContractError(
            f"unexpected latitude resolution: {dj}"
        )

    i_negative = int(_get(gid, "iScansNegatively"))
    j_positive = int(_get(gid, "jScansPositively"))

    if i_negative not in (0, 1) or j_positive not in (0, 1):
        raise ECMWFGRIBContractError(
            "ambiguous GRIB scanning orientation"
        )

    if not (
        SUPPORTED_LATITUDE_MIN <= roi_lat_min < roi_lat_max
        <= SUPPORTED_LATITUDE_MAX
    ):
        raise ECMWFGRIBContractError(
            "ROI latitude bounds must be ordered within supported range"
        )

    if not (-180.0 <= roi_lon_min < roi_lon_max <= 180.0):
        raise ECMWFGRIBContractError(
            "ROI longitude bounds must be ordered within [-180, 180]"
        )

    latitudes = np.asarray(
        eccodes.codes_get_array(gid, "latitudes"),
        dtype=np.float64,
    )
    longitudes = np.asarray(
        eccodes.codes_get_array(gid, "longitudes"),
        dtype=np.float64,
    )
    values = np.asarray(
        eccodes.codes_get_values(gid),
        dtype=np.float64,
    )

    expected_size = ni * nj

    if (
        values.size != expected_size
        or latitudes.size != expected_size
        or longitudes.size != expected_size
    ):
        raise ECMWFGRIBContractError(
            "GRIB coordinate/value count does not match grid dimensions"
        )

    values = _decode_missing(gid, values).reshape(nj, ni)
    latitude_field = latitudes.reshape(nj, ni)
    longitude_field = longitudes.reshape(nj, ni)

    row_latitudes = latitude_field[:, 0].copy()
    column_longitudes = longitude_field[0, :].copy()

    if not np.allclose(
        latitude_field,
        row_latitudes[:, None],
        rtol=0.0,
        atol=1e-12,
    ):
        raise ECMWFGRIBContractError(
            "latitude coordinates are not rectilinear"
        )

    wrapped_longitudes = (
        (column_longitudes + 180.0) % 360.0
    ) - 180.0

    expected_longitude_field = np.broadcast_to(
        column_longitudes,
        longitude_field.shape,
    )

    if not np.allclose(
        longitude_field,
        expected_longitude_field,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ECMWFGRIBContractError(
            "longitude coordinates are not rectilinear"
        )

    if row_latitudes[0] > row_latitudes[-1]:
        row_latitudes = row_latitudes[::-1].copy()
        values = values[::-1, :].copy()

    longitude_order = np.argsort(wrapped_longitudes)
    wrapped_longitudes = wrapped_longitudes[longitude_order]
    values = values[:, longitude_order].copy()

    if row_latitudes.size > 1 and not np.allclose(
        np.diff(row_latitudes),
        EXPECTED_GRID_RESOLUTION_DEG,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ECMWFGRIBContractError(
            "canonical latitude spacing is not 0.25 degrees"
        )

    if wrapped_longitudes.size > 1 and not np.allclose(
        np.diff(wrapped_longitudes),
        EXPECTED_GRID_RESOLUTION_DEG,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ECMWFGRIBContractError(
            "canonical longitude spacing is not 0.25 degrees"
        )

    half_resolution = EXPECTED_GRID_RESOLUTION_DEG / 2.0

    latitude_mask = (
        (row_latitudes - half_resolution >= roi_lat_min)
        & (row_latitudes + half_resolution <= roi_lat_max)
        & (
            row_latitudes - half_resolution
            >= SUPPORTED_LATITUDE_MIN
        )
        & (
            row_latitudes + half_resolution
            <= SUPPORTED_LATITUDE_MAX
        )
    )

    longitude_mask = (
        (
            wrapped_longitudes - half_resolution
            >= roi_lon_min
        )
        & (
            wrapped_longitudes + half_resolution
            <= roi_lon_max
        )
    )

    if not np.any(latitude_mask):
        raise ECMWFGRIBContractError(
            "ROI contains no complete latitude cells"
        )

    if not np.any(longitude_mask):
        raise ECMWFGRIBContractError(
            "ROI contains no complete longitude cells"
        )

    canonical_latitudes = row_latitudes[latitude_mask].copy()
    canonical_longitudes = wrapped_longitudes[
        longitude_mask
    ].copy()
    field = values[np.ix_(
        latitude_mask,
        longitude_mask,
    )].copy()

    finite = field[np.isfinite(field)]

    if finite.size:
        if np.any(finite < 0.0) or np.any(finite > 100.0):
            raise ECMWFGRIBContractError(
                "ECMWF probability percent values must be within [0, 100]"
            )

        field[np.isfinite(field)] /= 100.0

    return canonical_latitudes, canonical_longitudes, field


def decode_ecmwf_probability_grib(
    path: str | Path,
    *,
    model: str,
    threshold_mm: int,
    source_uri: str,
    retrieved_at: datetime,
    roi_lat_min: float,
    roi_lat_max: float,
    roi_lon_min: float,
    roi_lon_max: float,
) -> DecodedECMWFForecastField:
    threshold_mm = int(threshold_mm)

    if threshold_mm not in SUPPORTED_THRESHOLDS_MM:
        raise ECMWFGRIBContractError(
            f"unsupported precipitation threshold: {threshold_mm}"
        )

    if retrieved_at.tzinfo is None:
        raise ECMWFGRIBContractError(
            "retrieved_at must be timezone-aware"
        )

    artifact_path = Path(path)
    artifact_bytes = artifact_path.read_bytes()
    artifact_hash = sha256(artifact_bytes).hexdigest()

    with artifact_path.open("rb") as stream:
        gid = eccodes.codes_grib_new_from_file(stream)

        if gid is None:
            raise ECMWFGRIBContractError(
                "GRIB artifact contains no message"
            )

        try:
            probability_type = int(_get(gid, "probabilityType"))
            lower_limit = float(_get(gid, "lowerLimit"))

            if probability_type != EXPECTED_PROBABILITY_TYPE:
                raise ECMWFGRIBContractError(
                    f"unexpected probabilityType: {probability_type}"
                )

            if not np.isclose(lower_limit, float(threshold_mm)):
                raise ECMWFGRIBContractError(
                    "GRIB lower probability limit does not match threshold"
                )

            run_time = _utc_from_date_time(
                int(_get(gid, "dataDate")),
                int(_get(gid, "dataTime")),
            )

            valid_to = _utc_from_date_time(
                int(_get(gid, "validityDate")),
                int(_get(gid, "validityTime")),
            )

            end_step = int(_get(gid, "endStep"))
            start_step = int(_get(gid, "startStep"))

            if end_step < 0 or end_step > MAX_LEAD_HOURS:
                raise ECMWFGRIBContractError(
                    f"lead exceeds supported range: {end_step}"
                )

            if end_step - start_step != 24:
                raise ECMWFGRIBContractError(
                    "forecast accumulation window must be exactly 24 hours"
                )

            valid_from = valid_to - timedelta(hours=24)

            latitudes, longitudes, field = _canonical_grid_and_field(
                gid,
                roi_lat_min=roi_lat_min,
                roi_lat_max=roi_lat_max,
                roi_lon_min=roi_lon_min,
                roi_lon_max=roi_lon_max,
            )

            half_resolution = EXPECTED_GRID_RESOLUTION_DEG / 2.0

            lat_edges = np.concatenate(
                (
                    [latitudes[0] - half_resolution],
                    latitudes + half_resolution,
                )
            )
            lon_edges = np.concatenate(
                (
                    [longitudes[0] - half_resolution],
                    longitudes + half_resolution,
                )
            )

            if (
                lat_edges[0] < SUPPORTED_LATITUDE_MIN
                or lat_edges[-1] > SUPPORTED_LATITUDE_MAX
            ):
                raise ECMWFGRIBContractError(
                    "canonical grid cell edges exceed supported latitude range"
                )

            if lon_edges[0] < -180.0 or lon_edges[-1] > 180.0:
                raise ECMWFGRIBContractError(
                    "canonical grid cell edges exceed longitude range"
                )

            grid = RectilinearGrid(
                lat_edges=lat_edges,
                lon_edges=lon_edges,
            )

            grid.validate_field(field)

            metadata = {
                "edition": int(_get(gid, "edition")),
                "gridType": str(_get(gid, "gridType")),
                "Ni": int(_get(gid, "Ni")),
                "Nj": int(_get(gid, "Nj")),
                "probabilityType": probability_type,
                "lowerLimit": lower_limit,
                "dataDate": int(_get(gid, "dataDate")),
                "dataTime": int(_get(gid, "dataTime")),
                "startStep": start_step,
                "endStep": end_step,
                "validityDate": int(_get(gid, "validityDate")),
                "validityTime": int(_get(gid, "validityTime")),
                "bitmapPresent": int(_get(gid, "bitmapPresent")),
            }

        finally:
            eccodes.codes_release(gid)

    return DecodedECMWFForecastField(
        model=model,
        run_time=run_time,
        valid_from=valid_from,
        valid_to=valid_to,
        lead_hours=end_step,
        threshold_mm=threshold_mm,
        threshold_operator=EXPECTED_THRESHOLD_OPERATOR,
        probability_type=probability_type,
        probability_lower_limit=lower_limit,
        latitudes=latitudes,
        longitudes=longitudes,
        probability_field=field,
        grid_resolution_deg=EXPECTED_GRID_RESOLUTION_DEG,
        grid_sha256=grid.identity.sha256,
        forecast_field_sha256=_field_sha256(field),
        artifact_sha256=artifact_hash,
        source_uri=source_uri,
        retrieved_at=retrieved_at.astimezone(timezone.utc),
        raw_grib_metadata=metadata,
    )
