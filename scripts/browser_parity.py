"""Generate browser parity fixtures directly from the Python domain core."""

import json
from pathlib import Path
from smart_cooling_twin.control import Controller, SafetyLayer, StateMachine
from smart_cooling_twin.models import ControlSettings, SystemState, ThermalParameters
from smart_cooling_twin.thermal import ThermalModel


def main():
    control = []
    for old in SystemState:
        for temperature in (20, 28.9, 29, 29.5, 30, 31, 38.9, 39, 39.5, 40, 42):
            for trend in (-0.1, 0, 0.01, 0.03):
                for healthy, powered in ((True, True), (False, True), (True, False)):
                    machine = StateMachine()
                    machine.state = old
                    state = machine.update(temperature, trend, 30, healthy, powered)
                    for mode, manual in (("AUTO", 0), ("MANUAL", 0), ("MANUAL", 100)):
                        controller = Controller(SafetyLayer())
                        controller.settings = ControlSettings(mode=mode, manual_fan=manual)
                        control.append(
                            {
                                "input": [str(old), temperature, trend, 30, healthy, powered],
                                "mode": mode,
                                "manual": manual,
                                "state": str(state),
                                "fan": controller.command(state, temperature),
                            }
                        )
    thermal = []
    p = ThermalParameters()
    for temperature in (20, 27, 40):
        for fan in (0, 20, 100):
            for dt in (0, 0.5, 1, 2, 30):
                thermal.append(
                    {
                        "input": [temperature, 24, fan, dt, p.model_dump()],
                        "output": ThermalModel(p).predict(temperature, 24, fan, dt),
                    }
                )
    Path("tests/browser/parity.json").write_text(
        json.dumps({"control": control, "thermal": thermal}, separators=(",", ":"))
    )


if __name__ == "__main__":
    main()
