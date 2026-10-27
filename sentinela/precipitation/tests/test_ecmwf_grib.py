from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import eccodes
import numpy as np
import pytest

from sentinela.precipitation.ecmwf_grib import (
    ECMWFGRIBContractError,
    decode_ecmwf_probability_grib,
)


def _write_probability_grib(
    path: Path,
    *,
    probability_type: int = 3,
    lower_limit: int = 50,
    start_step: int = 0,
    end_step: int = 24,
    values: np.ndarray | None = None,
) -> None:
    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")

    try:
        setters = {
            "Ni": 5,
            "Nj": 5,
            "latitudeOfFirstGridPointInDegrees": 1.0,
            "latitudeOfLastGridPointInDegrees": 0.0,
            "longitudeOfFirstGridPointInDegrees": 0.0,
            "longitudeOfLastGridPointInDegrees": 1.0,
            "iDirectionIncrementInDegrees": 0.25,
            "jDirectionIncrementInDegrees": 0.25,
            "iScansNegatively": 0,
            "jScansPositively": 0,
            "productDefinitionTemplateNumber": 9,
            "probabilityType": probability_type,
            "scaledValueOfLowerLimit": lower_limit,
            "scaleFactorOfLowerLimit": 0,
            "dataDate": 20261001,
            "dataTime": 0,
            "startStep": start_step,
            "endStep": end_step,
        }

        for key, value in setters.items():
            eccodes.codes_set(gid, key, value)

        if values is None:
            values = np.linspace(
                0.0,
                1.0,
                25,
                dtype=np.float64,
            )

        eccodes.codes_set_values(gid, values)

        path.write_bytes(eccodes.codes_get_message(gid))

    finally:
        eccodes.codes_release(gid)


def _decode(path: Path):
    return decode_ecmwf_probability_grib(
        path,
        model="ecmwf-ens",
        threshold_mm=50,
        source_uri="synthetic://ecmwf-test",
        retrieved_at=datetime(
            2026,
            10,
            2,
            tzinfo=timezone.utc,
        ),
        roi_lat_min=-1.0,
        roi_lat_max=2.0,
        roi_lon_min=-1.0,
        roi_lon_max=2.0,
    )


def test_decodes_canonical_probability_grid(tmp_path: Path) -> None:
    path = tmp_path / "forecast.grib2"
    _write_probability_grib(path)

    decoded = _decode(path)

    assert decoded.threshold_mm == 50
    assert decoded.threshold_operator == ">"
    assert decoded.probability_type == 3
    assert decoded.probability_lower_limit == 50.0
    assert decoded.grid_resolution_deg == 0.25

    assert decoded.probability_field.shape == (5, 5)
    assert np.all(np.diff(decoded.latitudes) > 0)
    assert np.all(np.diff(decoded.longitudes) > 0)

    assert decoded.valid_to - decoded.valid_from == (
        decoded.valid_to - decoded.valid_from
    )
    assert (
        decoded.valid_to - decoded.valid_from
    ).total_seconds() == 24 * 3600

    assert len(decoded.grid_sha256) == 64
    assert len(decoded.forecast_field_sha256) == 64
    assert len(decoded.artifact_sha256) == 64


def test_hashes_are_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "forecast.grib2"
    _write_probability_grib(path)

    first = _decode(path)
    second = _decode(path)

    assert first.grid_sha256 == second.grid_sha256
    assert (
        first.forecast_field_sha256
        == second.forecast_field_sha256
    )
    assert first.artifact_sha256 == second.artifact_sha256


def test_rejects_wrong_probability_type(tmp_path: Path) -> None:
    path = tmp_path / "forecast.grib2"
    _write_probability_grib(
        path,
        probability_type=0,
    )

    with pytest.raises(
        ECMWFGRIBContractError,
        match="probabilityType",
    ):
        _decode(path)


def test_rejects_threshold_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "forecast.grib2"
    _write_probability_grib(
        path,
        lower_limit=25,
    )

    with pytest.raises(
        ECMWFGRIBContractError,
        match="lower probability limit",
    ):
        _decode(path)


def test_rejects_non_24_hour_window(tmp_path: Path) -> None:
    path = tmp_path / "forecast.grib2"
    _write_probability_grib(
        path,
        start_step=0,
        end_step=12,
    )

    with pytest.raises(
        ECMWFGRIBContractError,
        match="exactly 24 hours",
    ):
        _decode(path)


def test_rejects_probability_outside_unit_interval(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forecast.grib2"

    values = np.linspace(
        0.0,
        1.0,
        25,
        dtype=np.float64,
    )
    values[-1] = 100.5

    _write_probability_grib(
        path,
        values=values,
    )

    with pytest.raises(
        ECMWFGRIBContractError,
        match=r"\[0, 100\]",
    ):
        _decode(path)


def test_missing_bitmap_becomes_nan(tmp_path: Path) -> None:
    path = tmp_path / "forecast.grib2"

    gid = eccodes.codes_grib_new_from_samples(
        "regular_ll_sfc_grib2"
    )

    try:
        setters = {
            "Ni": 2,
            "Nj": 2,
            "latitudeOfFirstGridPointInDegrees": 0.25,
            "latitudeOfLastGridPointInDegrees": 0.0,
            "longitudeOfFirstGridPointInDegrees": 0.0,
            "longitudeOfLastGridPointInDegrees": 0.25,
            "iDirectionIncrementInDegrees": 0.25,
            "jDirectionIncrementInDegrees": 0.25,
            "iScansNegatively": 0,
            "jScansPositively": 0,
            "productDefinitionTemplateNumber": 9,
            "probabilityType": 3,
            "scaledValueOfLowerLimit": 50,
            "scaleFactorOfLowerLimit": 0,
            "dataDate": 20261001,
            "dataTime": 0,
            "startStep": 0,
            "endStep": 24,
            "bitmapPresent": 1,
        }

        for key, value in setters.items():
            eccodes.codes_set(gid, key, value)

        missing = float(
            eccodes.codes_get(gid, "missingValue")
        )

        eccodes.codes_set_values(
            gid,
            np.array(
                [25.0, missing, 75.0, 100.0],
                dtype=np.float64,
            ),
        )

        path.write_bytes(
            eccodes.codes_get_message(gid)
        )

    finally:
        eccodes.codes_release(gid)

    decoded = _decode(path)

    assert int(
        np.isnan(decoded.probability_field).sum()
    ) == 1

    finite = decoded.probability_field[
        np.isfinite(decoded.probability_field)
    ]

    assert np.allclose(
        np.sort(finite),
        np.array([0.25, 0.75, 1.0]),
    )


def test_real_ecmwf_percent_encoding_is_normalized(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forecast-percent.grib2"

    values = np.linspace(
        0.0,
        100.0,
        25,
        dtype=np.float64,
    )

    _write_probability_grib(
        path,
        values=values,
    )

    decoded = _decode(path)

    assert np.isclose(
        np.nanmin(decoded.probability_field),
        0.0,
    )
    assert np.isclose(
        np.nanmax(decoded.probability_field),
        1.0,
    )


def test_roi_keeps_only_complete_cells(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forecast-roi.grib2"
    _write_probability_grib(path)

    decoded = decode_ecmwf_probability_grib(
        path,
        model="ecmwf-ens",
        threshold_mm=50,
        source_uri="synthetic://ecmwf-roi",
        retrieved_at=datetime(
            2026,
            10,
            2,
            tzinfo=timezone.utc,
        ),
        roi_lat_min=0.0,
        roi_lat_max=1.0,
        roi_lon_min=0.0,
        roi_lon_max=1.0,
    )

    assert np.all(decoded.latitudes > 0.0)
    assert np.all(decoded.latitudes < 1.0)
    assert np.all(decoded.longitudes > 0.0)
    assert np.all(decoded.longitudes < 1.0)


def test_rejects_roi_crossing_antimeridian(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forecast-roi-invalid.grib2"
    _write_probability_grib(path)

    with pytest.raises(
        ECMWFGRIBContractError,
        match="ROI longitude bounds",
    ):
        decode_ecmwf_probability_grib(
            path,
            model="ecmwf-ens",
            threshold_mm=50,
            source_uri="synthetic://ecmwf-roi",
            retrieved_at=datetime(
                2026,
                10,
                2,
                tzinfo=timezone.utc,
            ),
            roi_lat_min=-1.0,
            roi_lat_max=2.0,
            roi_lon_min=170.0,
            roi_lon_max=-170.0,
        )
