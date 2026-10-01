"""Actual TCP MQTT tests: no mocked client and no external broker required."""

import socket
import subprocess
import sys
import time
from pathlib import Path
import pytest
from smart_cooling_twin.config import Settings
from smart_cooling_twin.__main__ import TwinService
from smart_cooling_twin.models import FanCommand, Telemetry, SystemState
from smart_cooling_twin.mqtt import COMMAND, TELEMETRY, MQTTClient
from smart_cooling_twin.repository import Repository
from simulator.physical_system import PhysicalSystem


def wait_for(predicate, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for MQTT state")


class BrokerProcess:
    def __init__(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.process = None

    def start(self):
        script = Path(__file__).resolve().parents[1] / "scripts/test_broker.py"
        self.process = subprocess.Popen(
            [sys.executable, str(script), str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def ready():
            if self.process.poll() is not None:
                raise AssertionError("Test broker failed to start")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    return True
            except OSError:
                return False

        wait_for(ready)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)


@pytest.fixture
def broker():
    instance = BrokerProcess()
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def test_real_mqtt_closed_loop_validation_and_recovery(broker):
    settings = Settings(mqtt_host="127.0.0.1", mqtt_port=broker.port)
    service = TwinService(settings, Repository(":memory:"))
    device = MQTTClient(settings, "test-device", [COMMAND], device=True)
    sim = PhysicalSystem()
    sim.temperature = 33
    sim.settings.noise = 0
    service.transport.start()
    device.start()
    try:
        wait_for(lambda: service.transport.connected and device.connected)
        time.sleep(0.2)  # Subscription acknowledgments precede publishing test telemetry.
        start = time.time()
        telemetry = sim.step(0, start)
        device.publish(TELEMETRY, telemetry)
        received_commands = []

        def receive_command():
            service.step(time.time())
            for _, payload in device.drain():
                received_commands.append(FanCommand.model_validate_json(payload))
            return any(0 < c.fan_speed < 100 for c in received_commands)

        wait_for(receive_command)
        command = next(c for c in reversed(received_commands) if c.fan_speed < 100)
        assert sim.apply_command(command, time.time())
        cooling = sim.step(2, time.time() + 2)
        assert cooling.temperature < telemetry.temperature
        assert service.repository.recent("telemetry")
        assert service.twin.state.state == SystemState.COOLING
        # Malformed sensor input is rejected before it enters history and activates fallback.
        device.client.publish(TELEMETRY, '{"temperature":NaN}')

        def fault_received():
            service.step(time.time())
            return service.twin.state.state == SystemState.FAULT

        wait_for(fault_received)
        assert len(service.repository.recent("telemetry")) == 1
        assert service.twin.state.fan_command == 100
        broker.stop()
        wait_for(lambda: not device.connected and not service.transport.connected)
        service.step(time.time())
        assert service.twin.state.fan_command == 100
        broker.start()
        wait_for(lambda: device.connected and service.transport.connected, timeout=20)
        time.sleep(0.2)
        now = time.time()
        sample = Telemetry(
            device_id="cooling-01",
            timestamp=now,
            temperature=32.9,
            ambient_temperature=24,
            humidity=47,
            fan_speed=80,
        )
        device.publish(TELEMETRY, sample)

        def recovered():
            service.step(time.time())
            return (
                service.twin.state.device_online and service.twin.state.state == SystemState.COOLING
            )

        wait_for(recovered)
        assert service.twin.state.mqtt_connected
        assert len(service.repository.recent("telemetry")) == 2
    finally:
        service.transport.stop()
        device.stop()
        service.repository.close()


def test_connects_when_broker_starts_late(broker):
    broker.stop()
    transport = MQTTClient(
        Settings(mqtt_host="127.0.0.1", mqtt_port=broker.port), "late-broker-client", [TELEMETRY]
    )
    transport.start()
    try:
        time.sleep(0.2)
        assert not transport.connected
        broker.start()
        wait_for(lambda: transport.connected)
    finally:
        transport.stop()
