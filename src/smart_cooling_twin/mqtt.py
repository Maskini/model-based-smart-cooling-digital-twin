"""Transport only: callbacks enqueue bounded raw events, services validate them."""

import logging
from queue import Queue, Empty, Full
import paho.mqtt.client as mqtt
from .config import Settings
from .models import DeviceStatus, Record

TELEMETRY = "smartcooling/telemetry"
COMMAND = "smartcooling/command"
STATUS = "smartcooling/status"
AGENT = "smartcooling/agent"
log = logging.getLogger(__name__)


class MQTTClient:
    def __init__(self, settings: Settings, client_id: str, topics: list[str], device: bool = False):
        self.settings, self.topics, self.device = settings, topics, device
        self.connected = False
        self.dropped = 0
        self.events: Queue[tuple[str, bytes]] = Queue(maxsize=1000)
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
            reconnect_on_failure=True,
        )
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.client.max_queued_messages_set(20)
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set()
        if device:
            self.client.will_set(
                STATUS,
                DeviceStatus(device_id=settings.device_id, online=False).model_dump_json(),
                qos=1,
                retain=True,
            )
        self.client.on_connect = self._connect
        self.client.on_disconnect = self._disconnect
        self.client.on_message = self._message

    def _connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            for topic in self.topics:
                client.subscribe(topic, qos=1)
            if self.device:
                self.publish(
                    STATUS,
                    DeviceStatus(device_id=self.settings.device_id, online=True),
                    retain=True,
                )
        log.info("mqtt_connection connected=%s", self.connected)

    def _disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        log.warning("mqtt_disconnected reason=%s", reason_code)

    def _message(self, client, userdata, message):
        if len(message.payload) > 16384:
            self.dropped += 1
            return
        try:
            self.events.put_nowait((message.topic, bytes(message.payload)))
        except Full:
            self.dropped += 1

    def drain(self):
        # Bound work per service tick even under a continuous incoming stream.
        for _ in range(1000):
            try:
                yield self.events.get_nowait()
            except Empty:
                return

    def start(self):
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=10)
        self.client.loop_start()

    def publish(self, topic: str, record: Record, retain: bool = False) -> bool:
        if not self.connected:
            return False
        # Commands deliberately use QoS 0: stale commands must never accumulate offline.
        info = self.client.publish(
            topic, record.model_dump_json(), qos=0 if topic == COMMAND else 1, retain=retain
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def stop(self):
        if self.device and self.connected:
            self.publish(
                STATUS, DeviceStatus(device_id=self.settings.device_id, online=False), retain=True
            )
        self.client.disconnect()
        self.client.loop_stop()
        self.connected = False
