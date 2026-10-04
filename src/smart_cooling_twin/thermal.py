import math
from .models import ThermalParameters


class ThermalModel:
    def __init__(self, parameters: ThermalParameters | None = None):
        self.parameters = parameters or ThermalParameters()

    def predict(self, temperature: float, ambient: float, fan: float, dt: float) -> float:
        if not all(math.isfinite(x) for x in (temperature, ambient, fan, dt)):
            raise ValueError("Inputs must be finite")
        if not 0 <= fan <= 100 or not 0 <= dt <= 3600:
            raise ValueError("Invalid fan or integration interval")
        # Euler substeps keep long forecasts stable at the maximum bounded coefficient.
        p = self.parameters
        remaining = dt
        while remaining > 0:
            step = min(1.0, remaining)
            temperature += step * (
                p.k_heat + p.k_ambient * (ambient - temperature) - p.k_fan * fan / 100
            )
            remaining -= step
        return temperature
