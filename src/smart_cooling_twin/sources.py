"""Interchangeable sensor/actuator adapters; all emit the same Telemetry model."""

from collections import deque
from typing import Protocol

from simulator.physical_system import PhysicalSystem
from .config import Settings
from .models import FanCommand, SimulatorSettings, Telemetry


class SensorSource(Protocol):
    def poll(self, now: float) -> list[Telemetry]: ...
    def send_command(self, command: FanCommand, now: float) -> None: ...
    def connected(self, now: float) -> bool: ...
    def close(self) -> None: ...


class Esp32SensorSource:
    """REST ingress and command mailbox. An HTTP exchange never runs hardware code."""

    def __init__(self, device_id: str, timeout: float = 10):
        self.device_id, self.timeout = device_id, timeout
        self.pending: deque[Telemetry] = deque(maxlen=100)
        self.last_received: float | None = None
        self.latest_command: FanCommand | None = None

    def ingest(self, telemetry: Telemetry, now: float) -> None:
        if telemetry.device_id != self.device_id:
            raise ValueError("Device ID does not match the configured device")
        if len(self.pending) >= self.pending.maxlen:
            raise ValueError("Device telemetry queue is full")
        self.pending.append(telemetry)
        self.last_received = now

    def poll(self, now: float) -> list[Telemetry]:
        records = list(self.pending)
        self.pending.clear()
        return records

    def send_command(self, command: FanCommand, now: float) -> None:
        if command.device_id != self.device_id:
            raise ValueError("Cannot route commands to another device")
        self.latest_command = command

    def connected(self, now: float) -> bool:
        return self.last_received is not None and now - self.last_received <= self.timeout

    def close(self) -> None:
        self.pending.clear()


class SimulationSensorSource:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.system = PhysicalSystem(settings.device_id)
        self.system.temperature = settings.simulation_start_temperature
        self.system.humidity = settings.simulation_humidity
        self.system.settings.heat_load = settings.simulation_heat_load
        self.system.fan_speed = 0
        self.running = False
        self.last_sample: float | None = None
        self.phase = "IDLE"
        self.phase_since = 0.0
        self.scenario_events: list[dict] = []

    def connected(self, now: float) -> bool:
        return True  # The software source remains available while its physics is paused.

    def _phase(self, name: str, now: float, description: str) -> None:
        self.phase, self.phase_since = name, now
        self.scenario_events.append({"timestamp": now, "phase": name, "description": description})
        self.scenario_events = self.scenario_events[-20:]

    def start_demo(self, now: float) -> None:
        self.system = PhysicalSystem(self.settings.device_id)
        self.system.settings = SimulatorSettings(heat_load=0, noise=0.005)
        self.system.humidity = self.settings.simulation_humidity
        self.system.fan_speed = 0
        self.system.command_deadline = now + 5
        self.last_sample = None
        self.running = True
        self.scenario_events = []
        self._phase("NORMAL", now, "Normal temperature: the system is stable and cooling is off.")

    def _advance_demo(self, now: float) -> None:
        if self.phase == "NORMAL" and now - self.phase_since >= 4:
            self.system.settings.heat_load = 1.2
            self._phase(
                "HEATING",
                now,
                "A sustained heat load increases temperature; normal cooling reacts.",
            )
        elif self.phase == "HEATING" and self.system.temperature >= 40:
            self._phase(
                "OVERHEATING",
                now,
                "The 40 °C safety threshold was crossed; maximum cooling is mandatory.",
            )
        elif self.phase == "OVERHEATING" and now - self.phase_since >= 2:
            self.system.settings.heat_load = 0
            self.system.settings.fan_effectiveness = 1
            self._phase(
                "RECOVERING",
                now,
                "Heat load removed: the controller cools the system toward its target.",
            )
        elif self.phase == "RECOVERING" and self.system.fan_speed == 0:
            self.system.settings.heat_load = 0.02
            self._phase(
                "COMPLETE",
                now,
                "Temperature is below the cooling exit threshold; cooling has switched off.",
            )

    def poll(self, now: float) -> list[Telemetry]:
        if self.last_sample is not None and now - self.last_sample < 2:
            return []
        dt = 0 if self.last_sample is None else min(now - self.last_sample, 2.5)
        self.last_sample = now
        if self.running:
            self._advance_demo(now)
            return [self.system.step(dt, now)]
        return [
            Telemetry(
                device_id=self.system.device_id,
                timestamp=now,
                temperature=self.system.temperature,
                humidity=self.system.humidity,
                ambient_temperature=self.system.settings.ambient_temperature,
                fan_speed=0,
                powered=False,
                sensor_ok=True,
            )
        ]

    def send_command(self, command: FanCommand, now: float) -> None:
        if self.running:
            self.system.apply_command(command, now)

    def close(self) -> None:
        self.running = False


class MqttSensorSource(Esp32SensorSource):
    """Optional LAN compatibility for the original MQTT firmware and simulator."""

    def __init__(self, settings: Settings):
        from .mqtt import MQTTClient, TELEMETRY, STATUS

        super().__init__(settings.device_id, settings.telemetry_timeout)
        self.transport = MQTTClient(settings, f"api-{settings.device_id}", [TELEMETRY, STATUS])
        self.transport.start()

    def connected(self, now: float) -> bool:
        return self.transport.connected

    def poll(self, now: float) -> list[Telemetry]:
        from pydantic import ValidationError
        from .mqtt import TELEMETRY, STATUS
        from .models import DeviceStatus

        for topic, payload in self.transport.drain():
            if topic == TELEMETRY:
                try:
                    record = Telemetry.model_validate_json(payload)
                    if record.device_id == self.device_id:
                        self.ingest(record, now)
                except ValidationError as exc:
                    raise ValueError("Malformed MQTT telemetry") from exc
            elif topic == STATUS:
                try:
                    status = DeviceStatus.model_validate_json(payload)
                    if status.device_id == self.device_id and not status.online:
                        raise ValueError("Device reported offline")
                except ValidationError:
                    continue
        return super().poll(now)

    def send_command(self, command: FanCommand, now: float) -> None:
        from .mqtt import COMMAND

        super().send_command(command, now)
        self.transport.publish(COMMAND, command)

    def close(self) -> None:
        self.transport.stop()
        super().close()
