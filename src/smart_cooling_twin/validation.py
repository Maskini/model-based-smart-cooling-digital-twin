from collections import deque
from statistics import mean
from .models import ValidationMetrics


class ModelValidator:
    def __init__(self, window: int = 30):
        self.residuals: deque[float] = deque(maxlen=window)

    def update(self, measured: float, predicted: float) -> ValidationMetrics:
        error = measured - predicted
        self.residuals.append(error)
        return ValidationMetrics(
            prediction_error=error,
            absolute_error=abs(error),
            rolling_mae=mean(map(abs, self.residuals)),
            residual_bias=mean(self.residuals),
            samples=len(self.residuals),
        )
