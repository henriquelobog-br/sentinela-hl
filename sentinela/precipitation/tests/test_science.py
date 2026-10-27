from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from sentinela.precipitation.accumulation import accumulate_imerg_30_minute
from sentinela.precipitation.aggregation import aggregate_roi_verification
from sentinela.precipitation.grid import RectilinearGrid
from sentinela.precipitation.models import ImergInterval, VerificationClass
from sentinela.precipitation.regrid import build_conservative_weights
from sentinela.precipitation.verification import (
    classify_verification,
    forecast_decision,
)


UTC = timezone.utc
START = datetime(2026, 10, 1, tzinfo=UTC)


def grid(step: float = 0.1) -> RectilinearGrid:
    count = round(1 / step)
    edges = [index * step for index in range(count + 1)]
    return RectilinearGrid(edges, edges)


def intervals(source: RectilinearGrid, value: float = 2.0) -> list[ImergInterval]:
    return [
        ImergInterval(
            START + timedelta(minutes=30 * index),
            START + timedelta(minutes=30 * (index + 1)),
            np.full(source.shape, value),
            source.identity,
        )
        for index in range(48)
    ]


def test_threshold_and_decision_semantics_are_different():
    decisions = forecast_decision(np.array([25 / 50, 24 / 50]))
    assert decisions.tolist() == ["YES", "NO"]
    classifications = classify_verification(
        np.array([0.5, 0.5]), np.array([25.0, 25.0001]), threshold_mm=25
    )
    assert classifications.tolist() == [
        VerificationClass.FALSE_ALARM.value,
        VerificationClass.HIT.value,
    ]


def test_imerg_30_minute_rates_accumulate_to_24_hours():
    source = grid()
    result = accumulate_imerg_30_minute(
        intervals(source), valid_from=START, valid_to=START + timedelta(hours=24), grid=source
    )
    np.testing.assert_allclose(result.accumulation_mm, 48.0)
    np.testing.assert_allclose(result.temporal_coverage, 1.0)


def test_missing_imerg_is_not_treated_as_zero():
    source = grid()
    data = intervals(source)
    missing = np.full(source.shape, 2.0)
    missing[0, 0] = np.nan
    data[0] = ImergInterval(data[0].start, data[0].end, missing, source.identity)
    result = accumulate_imerg_30_minute(
        data, valid_from=START, valid_to=START + timedelta(hours=24), grid=source
    )
    assert result.accumulation_mm[0, 0] == 47.0
    assert result.temporal_coverage[0, 0] == pytest.approx(47 / 48)
    assert result.accumulation_mm[0, 1] == 48.0


def test_constant_field_regrid_and_weight_sums():
    source = grid(0.1)
    target = grid(0.25)
    weights = build_conservative_weights(source, target)
    result = weights.apply(np.full(source.shape, 7.0), source_grid=source, target_grid=target)
    np.testing.assert_allclose(result.values, 7.0, atol=1e-12)
    np.testing.assert_allclose(result.valid_area_fraction, 1.0, atol=1e-12)
    np.testing.assert_allclose(weights.target_weight_sums(), 1.0, atol=1e-12)


def test_gradient_regrid_matches_symmetric_area_average():
    source = RectilinearGrid([0, 0.25, 0.5], [0, 0.25, 0.5])
    target = RectilinearGrid([0, 0.5], [0, 0.5])
    field = np.array([[1.0, 3.0], [1.0, 3.0]])
    result = build_conservative_weights(source, target).apply(
        field, source_grid=source, target_grid=target
    )
    assert result.values[0, 0] == pytest.approx(2.0)


def test_localized_precipitation_regrid_is_conservative():
    source = grid(0.1)
    target = grid(0.25)
    field = np.zeros(source.shape)
    field[4:6, 4:6] = 100.0
    result = build_conservative_weights(source, target).apply(
        field, source_grid=source, target_grid=target
    )
    source_total = float(np.sum(field * source.cell_areas_km2()))
    target_total = float(np.sum(result.values * target.cell_areas_km2()))
    assert target_total == pytest.approx(source_total, rel=1e-12)
    assert np.count_nonzero(result.values) < result.values.size


def test_missing_data_regrid_preserves_missing_coverage():
    source = RectilinearGrid([0, 0.25, 0.5], [0, 0.25, 0.5])
    target = RectilinearGrid([0, 0.5], [0, 0.5])
    field = np.array([[4.0, np.nan], [4.0, 4.0]])
    result = build_conservative_weights(source, target).apply(
        field, source_grid=source, target_grid=target
    )
    assert result.values[0, 0] == pytest.approx(4.0)
    assert 0.74 < result.valid_area_fraction[0, 0] < 0.76


def test_roi_edge_uses_fractional_spherical_area():
    comparison = RectilinearGrid([0, 0.25], [0, 0.25, 0.5])
    summary = aggregate_roi_verification(
        np.array([[0.5, 0.4]]),
        np.array([[30.0, 0.0]]),
        threshold_mm=25,
        grid=comparison,
        roi_fraction=np.array([[1.0, 0.5]]),
        temporal_coverage=1.0,
    )
    assert summary.hit.cell_count == 1
    assert summary.correct_negative.cell_count == 1
    assert summary.hit.area_fraction == pytest.approx(2 / 3, rel=1e-5)
    assert summary.correct_negative.area_fraction == pytest.approx(1 / 3, rel=1e-5)


@pytest.mark.parametrize("edges", ([-60, -59.75], [59.75, 60]))
def test_supported_latitude_boundaries(edges):
    boundary = RectilinearGrid(edges, [0, 0.25])
    assert boundary.cell_areas_km2()[0, 0] > 0


def test_weights_and_hash_are_deterministic():
    source = grid(0.1)
    target = grid(0.25)
    first = build_conservative_weights(source, target)
    second = build_conservative_weights(source, target)
    assert first.sha256 == second.sha256
    np.testing.assert_array_equal(first.target_indices, second.target_indices)
    np.testing.assert_array_equal(first.source_indices, second.source_indices)
    np.testing.assert_array_equal(first.weights, second.weights)


def test_grid_identity_mismatch_is_rejected():
    source = grid(0.1)
    other = RectilinearGrid([0, 0.2, 0.4, 0.6, 0.8, 1.0], [0, 0.2, 0.4, 0.6, 0.8, 1.0])
    target = grid(0.25)
    weights = build_conservative_weights(source, target)
    with pytest.raises(ValueError, match="grid identity mismatch"):
        weights.apply(np.ones(other.shape), source_grid=other, target_grid=target)


def test_all_four_verification_classes():
    result = classify_verification(
        np.array([[0.5, 0.4], [0.5, 0.4]]),
        np.array([[26.0, 26.0], [25.0, 25.0]]),
        threshold_mm=25,
    )
    assert result.tolist() == [
        ["HIT", "MISS"],
        ["FALSE_ALARM", "CORRECT_NEGATIVE"],
    ]


def test_roi_area_fractions_sum_to_one():
    comparison = RectilinearGrid([0, 0.25, 0.5], [0, 0.25, 0.5])
    summary = aggregate_roi_verification(
        np.array([[0.5, 0.4], [0.5, 0.4]]),
        np.array([[26.0, 26.0], [25.0, 25.0]]),
        threshold_mm=25,
        grid=comparison,
        roi_fraction=np.ones(comparison.shape),
        temporal_coverage=1.0,
    )
    fractions = (
        summary.hit.area_fraction
        + summary.miss.area_fraction
        + summary.false_alarm.area_fraction
        + summary.correct_negative.area_fraction
    )
    assert fractions == pytest.approx(1.0)


def test_insufficient_temporal_coverage_is_rejected():
    comparison = RectilinearGrid([0, 0.25], [0, 0.25])
    with pytest.raises(ValueError, match="temporal"):
        aggregate_roi_verification(
            np.array([[0.5]]),
            np.array([[30.0]]),
            threshold_mm=25,
            grid=comparison,
            roi_fraction=np.ones(comparison.shape),
            temporal_coverage=0.89,
        )


def test_insufficient_spatial_coverage_is_rejected():
    comparison = RectilinearGrid([0, 0.25], [0, 0.25])
    with pytest.raises(ValueError, match="spatial"):
        aggregate_roi_verification(
            np.array([[0.5]]),
            np.array([[30.0]]),
            threshold_mm=25,
            grid=comparison,
            roi_fraction=np.ones(comparison.shape),
            temporal_coverage=1.0,
            spatial_coverage=0.89,
        )
