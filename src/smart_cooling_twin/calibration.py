"""Chronological holdout estimation with excitation, bounds and improvement gates."""

import numpy as np
from .models import CalibrationResult, Telemetry, ThermalParameters


def calibration_rows(history: list[Telemetry]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features, targets, intervals = [], [], []
    for a, b in zip(history, history[1:]):
        dt = b.timestamp - a.timestamp
        if (
            0.2 <= dt <= 3
            and a.sensor_ok
            and b.sensor_ok
            and a.powered
            and b.powered
            and a.device_id == b.device_id
        ):
            # b reports the actuator applied during the interval ending at b.
            features.append([1, a.ambient_temperature - a.temperature, -b.fan_speed / 100])
            targets.append((b.temperature - a.temperature) / dt)
            intervals.append(dt)
    return np.asarray(features), np.asarray(targets), np.asarray(intervals)


class Calibrator:
    def __init__(self, min_samples: int = 60, improvement: float = 0.15):
        self.min_samples, self.improvement = min_samples, improvement

    def fit(
        self, history: list[Telemetry], previous: ThermalParameters, now: float
    ) -> CalibrationResult:
        result = CalibrationResult(timestamp=now, previous=previous, reason="Insufficient data")
        x, y, dt = calibration_rows(history)
        if len(y) < self.min_samples:
            return result
        split = int(len(y) * 0.7)
        train, valid = x[:split], x[split:]
        if np.ptp(train[:, 2]) < 0.15:
            result.reason = "Insufficient fan excitation"
            return result
        # Ambient coefficient is only estimated when its independent variation is observable.
        fit_ambient = np.linalg.matrix_rank(train) == 3 and np.linalg.cond(train) < 1000
        if fit_ambient:
            coefficients, *_ = np.linalg.lstsq(train, y[:split], rcond=None)
        else:
            reduced = train[:, [0, 2]]
            if np.linalg.matrix_rank(reduced) < 2:
                result.reason = "Rank deficient observations"
                return result
            hf, *_ = np.linalg.lstsq(
                reduced, y[:split] - train[:, 1] * previous.k_ambient, rcond=None
            )
            coefficients = np.array([hf[0], previous.k_ambient, hf[1]])
        low, high = np.array([0, 0.0001, 0.001]), np.array([2, 0.2, 3])
        if (
            not np.all(np.isfinite(coefficients))
            or np.any(coefficients < low)
            or np.any(coefficients > high)
        ):
            result.reason = "Unconstrained fit outside physical bounds; candidate rejected"
            return result
        candidate = ThermalParameters(
            k_heat=coefficients[0], k_ambient=coefficients[1], k_fan=coefficients[2]
        )
        old = np.array([previous.k_heat, previous.k_ambient, previous.k_fan])
        old_mae = float(np.mean(np.abs((valid @ old - y[split:]) * dt[split:])))
        new_mae = float(np.mean(np.abs((valid @ coefficients - y[split:]) * dt[split:])))
        accepted = old_mae > 0.005 and new_mae <= old_mae * (1 - self.improvement)
        return CalibrationResult(
            timestamp=now,
            previous=previous,
            candidate=candidate,
            previous_mae=old_mae,
            candidate_mae=new_mae,
            accepted=accepted,
            reason="Holdout improvement passed" if accepted else "Insufficient holdout improvement",
        )
