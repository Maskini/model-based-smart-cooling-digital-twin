"""One shared core and controller, with isolated source contexts for hardware and visitors."""

import secrets
from pathlib import Path
from typing import Literal
from .config import Settings
from .explanations import explain_state
from .models import ControlSettings, SimulationControls, SystemState, Telemetry
from .repository import Repository
from .sources import SensorSource, Esp32SensorSource, SimulationSensorSource, MqttSensorSource
from .twin import DigitalTwin


class TwinContext:
    def __init__(
        self,
        settings: Settings,
        source: SensorSource,
        repository: Repository,
        mode: Literal["LIVE", "SIMULATION"],
    ):
        self.settings = settings
        self.received_samples = 0
        self.source, self.repository = source, repository
        self.twin = DigitalTwin(
            repository, settings.device_id, settings.telemetry_timeout, settings.agent_enabled
        )
        self.twin.state.operating_mode = mode
        self.twin.state.source_connected = False
        self.last_step = -1e12
        saved_control = repository.get("control")
        if saved_control:
            self.twin.controller.settings = ControlSettings.model_validate(saved_control)
        saved = repository.get("snapshot")
        if saved and saved["state"].get("telemetry"):
            self.twin.state.telemetry = Telemetry.model_validate(saved["state"]["telemetry"])
        self.last_seen = 0.0
        self.token = secrets.token_urlsafe(32)
        self.last_prune = 0.0

    def step(self, now: float, force: bool = False) -> None:
        if (
            isinstance(self.source, SimulationSensorSource)
            and not self.source.running
            and self.source.last_sample is not None
            and not force
        ):
            return  # Pause physics, telemetry timestamps and history together.
        if not force and now - self.last_step < 1:
            return
        self.last_step = now
        self.twin.state.source_connected = self.source.connected(now)
        try:
            records = self.source.poll(now)
        except ValueError:
            self.twin.fault(now, "INVALID_TELEMETRY", "Rejected malformed device telemetry")
            records = []
        for record in records:
            previous_telemetry = self.twin.state.telemetry
            command = self.twin.receive(record, now)
            if self.twin.state.telemetry is not previous_telemetry:
                self.received_samples += 1
            if command:
                self.source.send_command(command, now)
        command = self.twin.tick(now)
        self.source.send_command(command, now)
        if self.twin.state.operating_mode == "SIMULATION" and now - self.last_prune >= 60:
            self.repository.prune()
            self.last_prune = now

    def set_control(self, control: ControlSettings, now: float) -> None:
        if isinstance(self.source, SimulationSensorSource):
            self.source.phase = "IDLE"
        self.twin.controller.settings = control
        self.repository.set("control", control.model_dump())
        # Re-evaluate safe settings against current telemetry, without fabricating a new reading.
        t = self.twin.state.telemetry
        if t and self.twin.state.device_online and self.twin.state.state != SystemState.FAULT:
            state = self.twin.machine.update(t.temperature, 0, control.setpoint, powered=t.powered)
            self.twin.set_state(state, now, "Owner or simulation control settings changed")
        self.source.send_command(self.twin.command(now), now)
        self.twin.persist(now)

    def rebase_simulation(self) -> None:
        """An explicit visitor temperature edit starts a new measurement segment."""
        self.twin.state.telemetry = None
        self.twin.history.clear()
        self.twin.clear_predictions()
        self.source.last_sample = None

    def calibrate(self, now: float) -> dict:
        if isinstance(self.source, SimulationSensorSource) and not self.source.running:
            raise ValueError("Start Simulation before requesting calibration")
        self.step(now, force=True)
        result = self.twin.agent.run_calibration(now)
        self.twin.persist(now)
        return result

    def connection(self, now: float) -> dict:
        sim = isinstance(self.source, SimulationSensorSource)
        transport = (
            "SIMULATION" if sim else "MQTT" if isinstance(self.source, MqttSensorSource) else "REST"
        )
        received = self.twin.last_received
        age = max(0, now - received) if received is not None else None
        connected = self.source.connected(now)
        if sim and not self.source.running:
            activity = "PAUSED"
        elif age is None:
            activity = "WAITING"
        elif not connected or age > self.settings.telemetry_timeout:
            activity = "OFFLINE"
        elif age > min(5, self.settings.telemetry_timeout):
            activity = "DELAYED"
        else:
            activity = "RECEIVING"
        return {
            "transport": transport,
            "connected": connected,
            "activity": activity,
            "last_received": received,
            "age_seconds": age,
            "received_samples": self.received_samples,
            "device_id": self.settings.device_id,
            "expected_interval_seconds": 2,
            "timeout_seconds": self.settings.telemetry_timeout,
            "endpoint": "Local physics model"
            if sim
            else "Configured MQTT broker"
            if transport == "MQTT"
            else "/api/devices/{device_id}/telemetry",
        }

    def snapshot(self, now: float) -> dict:
        self.step(now)
        analysis = explain_state(self.twin)
        t = self.twin.state.telemetry
        sim = self.source if isinstance(self.source, SimulationSensorSource) else None
        connection = self.connection(now)
        return {
            "timestamp": now,
            "connection": connection,
            "operating_mode": self.twin.state.operating_mode,
            "state": self.twin.state.model_dump(mode="json"),
            "last_update": t.timestamp if t else None,
            "last_received": self.twin.last_received,
            "device_status": "Online"
            if connection["activity"] in ("RECEIVING", "DELAYED")
            else "Offline",
            "parameters": self.twin.model.parameters.model_dump(),
            "control": self.twin.controller.settings.model_dump(),
            "analysis": analysis,
            "agent_enabled": self.twin.agent.enabled,
            "history": self.repository.recent("telemetry", 180),
            "predictions": self.repository.recent("predictions", 180),
            "transitions": self.repository.recent("transitions", 60),
            "agent_events": self.repository.recent("agent_events", 30),
            "calibrations": self.repository.recent("calibrations", 3),
            "simulation": (
                {
                    "running": sim.running,
                    "phase": sim.phase,
                    "scenario_events": sim.scenario_events,
                    "settings": sim.system.settings.model_dump(),
                }
                if sim
                else None
            ),
        }

    def close(self) -> None:
        self.source.close()
        self.repository.close()


class TwinRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        path = Path(settings.database_path)
        live_path = str(path.with_name(path.stem + ".live" + path.suffix))
        source = (
            MqttSensorSource(settings)
            if settings.hardware_transport == "MQTT"
            else Esp32SensorSource(settings.device_id, settings.telemetry_timeout)
        )
        self.live = TwinContext(settings, source, Repository(live_path), "LIVE")
        self.sessions: dict[str, TwinContext] = {}
        self.last_tick = 0.0

    def create_session(self, now: float) -> tuple[str, TwinContext]:
        self.expire_sessions(now)
        if len(self.sessions) >= self.settings.simulation_max_sessions:
            raise ValueError("All demo sessions are busy. Please try again later.")
        session_id = secrets.token_urlsafe(18)
        context = TwinContext(
            self.settings,
            SimulationSensorSource(self.settings),
            Repository(":memory:"),
            "SIMULATION",
        )
        context.last_seen = now
        self.sessions[session_id] = context
        context.step(now)
        return session_id, context

    def expire_sessions(self, now: float) -> None:
        for key, context in list(self.sessions.items()):
            if now - context.last_seen > self.settings.simulation_session_ttl:
                context.close()
                del self.sessions[key]

    def tick(self, now: float) -> None:
        self.last_tick = now
        self.live.step(now)
        self.expire_sessions(now)
        for context in self.sessions.values():
            context.step(now)

    def simulation_action(self, context: TwinContext, action: str, now: float) -> None:
        source = context.source
        if not isinstance(source, SimulationSensorSource):
            raise ValueError("Simulation actions cannot target hardware")
        if action in ("RESET", "DEMO"):
            source.close()
            context.repository.close()
            # Keep only this visitor's capability and activity metadata.
            token, last_seen = context.token, context.last_seen
            context.__init__(
                self.settings,
                SimulationSensorSource(self.settings),
                Repository(":memory:"),
                "SIMULATION",
            )
            context.token, context.last_seen = token, last_seen
            source = context.source
        if action == "DEMO":
            source.start_demo(now)
        elif action == "START":
            source.running = True
            source.last_sample = None
        elif action == "STOP":
            source.running = False
            source.phase = "IDLE"
            source.system.fan_speed = 0
            source.last_sample = None
            context.twin.controller.settings.mode = "AUTO"
        elif action in ("INCREASE", "OVERHEAT"):
            source.phase = "IDLE"
            source.system.temperature = (
                42 if action == "OVERHEAT" else min(60, source.system.temperature + 5)
            )
            source.running = True
            context.rebase_simulation()
        context.step(now, force=True)

    def simulation_controls(
        self, context: TwinContext, control: SimulationControls, now: float
    ) -> None:
        source = context.source
        if not isinstance(source, SimulationSensorSource):
            raise ValueError("Simulation settings cannot target hardware")
        source.phase = "IDLE"
        if control.temperature is not None:
            source.system.temperature = control.temperature
            context.rebase_simulation()
        if control.humidity is not None:
            source.system.humidity = control.humidity
        for name in (
            "heat_load",
            "ambient_temperature",
            "fan_effectiveness",
            "noise",
            "sensor_failure",
        ):
            value = getattr(control, name)
            if value is not None:
                setattr(source.system.settings, name, value)
        if control.target_temperature is not None:
            old = context.twin.controller.settings
            context.set_control(
                ControlSettings(
                    mode=old.mode, manual_fan=old.manual_fan, setpoint=control.target_temperature
                ),
                now,
            )
        source.last_sample = None
        context.step(now, force=True)

    def close(self) -> None:
        self.live.close()
        for context in self.sessions.values():
            context.close()
