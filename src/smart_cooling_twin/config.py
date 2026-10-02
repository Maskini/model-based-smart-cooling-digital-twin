import os
from typing import Literal
from dotenv import load_dotenv
from pydantic import Field
from .models import Record


class Settings(Record):
    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_tls: bool = False
    device_id: str = "cooling-01"
    database_path: str = "data/twin.sqlite"
    simulation_mode: bool = True
    agent_enabled: bool = True
    llm_enabled: bool = False
    backend_url: str = "http://127.0.0.1:8000"
    hardware_api_token: str = ""
    admin_api_token: str = ""
    hardware_transport: Literal["REST", "MQTT"] = "REST"
    public_demo: bool = True
    cors_origins: str = "https://maskini.github.io"
    simulation_start_temperature: float = Field(default=27, ge=-40, le=60)
    simulation_humidity: float = Field(default=47, ge=0, le=100)
    simulation_heat_load: float = Field(default=0.12, ge=0, le=2)
    simulation_max_sessions: int = Field(default=16, ge=1, le=100)
    simulation_session_ttl: int = Field(default=900, ge=60, le=86400)
    llm_api_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    telemetry_timeout: float = Field(default=10, ge=5, le=120, allow_inf_nan=False)

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls.model_validate(
            {
                name: os.environ[name.upper()]
                for name in cls.model_fields
                if name.upper() in os.environ
            }
        )
