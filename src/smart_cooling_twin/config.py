import os
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
