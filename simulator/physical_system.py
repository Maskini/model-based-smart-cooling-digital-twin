"""Hardware substitute using exactly the device telemetry and command contracts."""

import argparse
import logging
import math
import random
import time
from pydantic import ValidationError
from smart_cooling_twin.config import Settings
from smart_cooling_twin.models import FanCommand, SimulatorSettings, Telemetry, ThermalParameters
from smart_cooling_twin.mqtt import COMMAND, TELEMETRY, MQTTClient
from smart_cooling_twin.repository import Repository
from smart_cooling_twin.thermal import ThermalModel


class PhysicalSystem:
    def __init__(self, device_id: str = "cooling-01", seed: int = 7):
        self.device_id = device_id
        self.settings = SimulatorSettings()
        self.temperature = 27.0
        self.fan_speed = 100.0
        self.random = random.Random(seed)
        self.command_deadline = 0.0
        self.last_command_timestamp = -1.0

    def increase_heat_load(self, amount: float = 0.05):
        self.settings.heat_load += amount

    def change_ambient_temperature(self, value: float):
        self.settings.ambient_temperature = value

    def change_fan_effectiveness(self, value: float):
        self.settings.fan_effectiveness = value

    def inject_sensor_noise(self, value: float):
        self.settings.noise = value

    def simulate_sensor_failure(self, enabled: bool = True):
        self.settings.sensor_failure = enabled

    def apply_command(self, command: FanCommand, now: float) -> bool:
        if (
            command.device_id != self.device_id
            or command.timestamp <= self.last_command_timestamp
            or command.timestamp > now + 1
            or not now < command.expires_at <= now + 10
            or command.expires_at <= command.timestamp
        ):
            return False
        self.fan_speed = command.fan_speed
        self.command_deadline = min(command.expires_at, now + 5)
        self.last_command_timestamp = command.timestamp
        return True

    def step(self, dt: float, now: float) -> Telemetry:
        s = self.settings
        if now >= self.command_deadline or s.sensor_failure or self.temperature >= 40:
            self.fan_speed = 100
        # Simulator permits a completely failed fan, while calibrated models have a positive bound.
        model = ThermalModel(
            ThermalParameters(k_heat=s.heat_load, k_fan=max(0.001, s.fan_effectiveness))
        )
        effective_fan = self.fan_speed if s.fan_effectiveness > 0 else 0
        self.temperature = model.predict(self.temperature, s.ambient_temperature, effective_fan, dt)
        measurement = min(125, max(-40, self.temperature + self.random.gauss(0, s.noise)))
        return Telemetry(
            device_id=self.device_id,
            timestamp=now,
            temperature=measurement,
            ambient_temperature=s.ambient_temperature,
            humidity=47,
            fan_speed=self.fan_speed,
            sensor_ok=not s.sensor_failure,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Introduce heat and fan degradation")
    args = parser.parse_args()
    config = Settings.from_env()
    if not config.simulation_mode:
        raise SystemExit("SIMULATION_MODE must be true to launch the simulator")
    repo = Repository(config.database_path)
    system = PhysicalSystem(config.device_id)
    transport = MQTTClient(config, f"simulator-{config.device_id}", [COMMAND], device=True)
    transport.start()
    start = previous = last_sample = time.time()
    applied_settings = None
    try:
        while True:
            now = time.time()
            for _, payload in transport.drain():
                try:
                    system.apply_command(FanCommand.model_validate_json(payload), now)
                except ValidationError:
                    logging.warning("invalid_fan_command")
            saved = repo.get("simulator")
            if saved and saved != applied_settings:
                system.settings = SimulatorSettings.model_validate(saved)
                applied_settings = saved
            if args.demo:
                elapsed = now - start
                # Repeating ambient/heat changes provide safe natural parameter excitation.
                system.settings.heat_load = 0.12 if elapsed < 90 else 0.16
                system.settings.ambient_temperature = 24 + 2 * math.sin(elapsed / 34)
                system.settings.fan_effectiveness = 0.25 if elapsed < 180 else 0.10
            sample = system.step(min(now - previous, 1), now)
            previous = now
            if now - last_sample >= 2:
                transport.publish(TELEMETRY, sample)
                last_sample = now
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        transport.stop()
        repo.close()


if __name__ == "__main__":
    main()
