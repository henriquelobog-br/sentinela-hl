from __future__ import annotations

import numpy as np

from sentinela.precipitation.constants import FORECAST_DECISION_PROBABILITY
from sentinela.precipitation.models import (
    ForecastDecision,
    VerificationClass,
)


def forecast_decision(
    probability: np.ndarray | float,
    *,
    decision_probability: float = FORECAST_DECISION_PROBABILITY,
) -> np.ndarray:
    values = np.asarray(probability, dtype=np.float64)
    if np.any(np.isfinite(values) & ((values < 0) | (values > 1))):
        raise ValueError("forecast probabilities must be within [0, 1]")
    return np.where(
        np.isfinite(values) & (values >= decision_probability),
        ForecastDecision.YES.value,
        ForecastDecision.NO.value,
    )


def classify_verification(
    forecast_probability: np.ndarray,
    observed_mm: np.ndarray,
    *,
    threshold_mm: float,
    decision_probability: float = FORECAST_DECISION_PROBABILITY,
) -> np.ndarray:
    forecast = np.asarray(forecast_probability, dtype=np.float64)
    observed = np.asarray(observed_mm, dtype=np.float64)
    if forecast.shape != observed.shape:
        raise ValueError("forecast and observation shapes differ")
    if threshold_mm not in {1, 5, 10, 20, 25, 50, 100}:
        raise ValueError("unsupported precipitation threshold")
    valid = np.isfinite(forecast) & np.isfinite(observed)
    forecast_yes = forecast >= decision_probability
    observed_yes = observed > threshold_mm
    result = np.full(forecast.shape, None, dtype=object)
    result[valid & forecast_yes & observed_yes] = VerificationClass.HIT.value
    result[valid & ~forecast_yes & observed_yes] = VerificationClass.MISS.value
    result[valid & forecast_yes & ~observed_yes] = VerificationClass.FALSE_ALARM.value
    result[valid & ~forecast_yes & ~observed_yes] = VerificationClass.CORRECT_NEGATIVE.value
    return result
