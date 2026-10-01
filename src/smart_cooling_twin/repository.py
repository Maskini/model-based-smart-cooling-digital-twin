"""SQLite boundary shared by runtime and UI; JSON records retain domain schemas."""

import json
import sqlite3
from pathlib import Path
from typing import Any
from .models import Record

TABLES = {"telemetry", "predictions", "agent_events", "calibrations", "alerts"}


class Repository:
    def __init__(self, path: str = "data/twin.sqlite"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        for table in TABLES:
            self.db.execute(
                f"CREATE TABLE IF NOT EXISTS {table} "
                "(id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, payload TEXT NOT NULL)"
            )
        self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, payload TEXT)")
        self.db.commit()

    def append(self, table: str, record: Record) -> int:
        if table not in TABLES:
            raise ValueError("Unknown record table")
        payload = record.model_dump(mode="json")
        with self.db:
            cursor = self.db.execute(
                f"INSERT INTO {table}(timestamp,payload) VALUES (?,?)",
                (payload["timestamp"], json.dumps(payload, allow_nan=False)),
            )
        return int(cursor.lastrowid)

    def recent(self, table: str, limit: int = 100) -> list[dict[str, Any]]:
        if table not in TABLES or not 1 <= limit <= 10000:
            raise ValueError("Invalid history query")
        rows = self.db.execute(f"SELECT payload FROM {table} ORDER BY id DESC LIMIT ?", (limit,))
        return [json.loads(row[0]) for row in rows][::-1]

    def set(self, key: str, value: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE "
                "SET payload=excluded.payload",
                (key, json.dumps(value, allow_nan=False)),
            )

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT payload FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def create_alert(self, alert: Record) -> bool:
        current = self.get("active_alerts") or {}
        if alert.code in current:
            return False
        self.append("alerts", alert)
        current[alert.code] = alert.model_dump(mode="json")
        self.set("active_alerts", current)
        return True

    def resolve_alert(self, code: str) -> None:
        current = self.get("active_alerts") or {}
        if code in current:
            del current[code]
            self.set("active_alerts", current)

    def close(self) -> None:
        self.db.close()
