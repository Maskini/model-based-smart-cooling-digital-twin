import logging
import time
from pydantic import ValidationError
from .config import Settings
from .models import ControlSettings, DeviceStatus, Telemetry
from .mqtt import AGENT, COMMAND, STATUS, TELEMETRY, MQTTClient
from .repository import Repository
from .twin import DigitalTwin

log = logging.getLogger(__name__)


class TwinService:
    def __init__(self, settings: Settings, repository: Repository | None = None):
        self.settings = settings
        self.repository = repository or Repository(settings.database_path)
        self.twin = DigitalTwin(
            self.repository, settings.device_id, settings.telemetry_timeout, settings.agent_enabled
        )
        self.transport = MQTTClient(settings, f"twin-{settings.device_id}", [TELEMETRY, STATUS])
        self.last_command = 0.0
        self.last_event = 0.0

    def step(self, now: float):
        twin = self.twin
        twin.state.mqtt_connected = self.transport.connected
        control = self.repository.get("control")
        if control:
            try:
                twin.controller.settings = ControlSettings.model_validate(control)
            except ValidationError:
                log.warning("invalid_control_settings")
        for topic, payload in self.transport.drain():
            try:
                if topic == TELEMETRY:
                    command = twin.receive(Telemetry.model_validate_json(payload), now)
                    if command:
                        self.transport.publish(COMMAND, command)
                        self.last_command = now
                elif topic == STATUS:
                    status = DeviceStatus.model_validate_json(payload)
                    if status.device_id == self.settings.device_id and (
                        not status.online or not status.sensor_ok
                    ):
                        self.transport.publish(
                            COMMAND,
                            twin.fault(now, "DEVICE_OFFLINE", "Device offline or sensor fault"),
                        )
                    elif status.device_id == self.settings.device_id:
                        self.repository.resolve_alert("DEVICE_OFFLINE")
            except ValidationError:
                log.warning("invalid_mqtt_message topic=%s", topic)
                if topic == TELEMETRY:
                    self.transport.publish(
                        COMMAND,
                        twin.fault(now, "INVALID_TELEMETRY", "Rejected malformed telemetry"),
                    )
        command = twin.tick(now)
        if now - self.last_command >= 1:
            self.transport.publish(COMMAND, command)
            self.last_command = now
        events = self.repository.recent("agent_events", 1)
        if events and events[0]["timestamp"] > self.last_event:
            from .models import AgentDecision

            self.transport.publish(AGENT, AgentDecision.model_validate(events[0]))
            self.last_event = events[0]["timestamp"]

    def run(self):
        self.transport.start()
        try:
            while True:
                self.step(time.time())
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.transport.stop()
            self.repository.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    TwinService(Settings.from_env()).run()


if __name__ == "__main__":
    main()
