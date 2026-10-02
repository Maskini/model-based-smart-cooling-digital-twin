"""REST API shared by the portfolio dashboard and authenticated ESP32 hardware."""

import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import time
from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException, Request
from .config import Settings
from .models import ControlSettings, SimulationAction, SimulationControls, Telemetry
from .runtime import TwinRuntime
from .sources import Esp32SensorSource, MqttSensorSource


def matches_token(authorization: str | None, expected: str) -> bool:
    if not expected or not authorization or not authorization.startswith("Bearer "):
        return False
    return hmac.compare_digest(authorization[7:].encode(), expected.encode())


def create_app(settings: Settings | None = None, clock: Callable[[], float] = time.time) -> FastAPI:
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = TwinRuntime(config)
        app.state.runtime = runtime

        async def update():
            while True:
                runtime.tick(clock())
                await asyncio.sleep(0.2)

        task = asyncio.create_task(update())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            runtime.close()

    app = FastAPI(
        title="Model-Based Smart Cooling Digital Twin",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def limited_body(request: Request, call_next):
        # Bound payload buffering before FastAPI parses JSON, including chunked requests.
        if request.method in ("POST", "PUT", "PATCH"):
            payload = bytearray()
            async for chunk in request.stream():
                payload.extend(chunk)
                if len(payload) > 16384:
                    from fastapi.responses import JSONResponse

                    return JSONResponse({"detail": "Request body exceeds 16 KiB"}, status_code=413)
            request._body = bytes(payload)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def owner(authorization: str | None) -> None:
        if not matches_token(authorization, config.admin_api_token):
            raise HTTPException(401, "Owner authentication required")

    def device(device_id: str, authorization: str | None):
        if config.hardware_transport != "REST":
            raise HTTPException(409, "REST hardware ingress is disabled in MQTT mode")
        if not matches_token(authorization, config.hardware_api_token):
            raise HTTPException(401, "Device authentication required")
        if device_id != config.device_id:
            raise HTTPException(404, "Unknown device")
        return app.state.runtime.live

    def session(session_id: str, authorization: str | None):
        runtime = app.state.runtime
        runtime.expire_sessions(clock())
        context = runtime.sessions.get(session_id)
        if context is None:
            raise HTTPException(404, "Simulation session expired; create a new session")
        if not matches_token(authorization, context.token):
            raise HTTPException(401, "Simulation session authentication required")
        context.last_seen = clock()
        return context

    @app.get("/api/health")
    async def health():
        runtime = app.state.runtime
        if runtime.last_tick and clock() - runtime.last_tick > 5:
            raise HTTPException(503, "Core update loop is not responding")
        return {
            "status": "ok",
            "hardware_online": runtime.live.twin.state.device_online,
            "simulation_sessions": len(runtime.sessions),
        }

    @app.get("/api/info")
    async def info():
        return {
            "device_id": config.device_id,
            "hardware_transport": config.hardware_transport,
            "hardware_configured": bool(config.hardware_api_token)
            or config.hardware_transport == "MQTT",
            "public_demo": config.public_demo,
            "overheating_threshold": 40,
            "llm_configured": bool(
                config.llm_enabled and config.llm_api_url and config.llm_api_key
            ),
        }

    @app.get("/api/live/state")
    async def live_state(authorization: str | None = Header(default=None)):
        if not config.public_demo:
            owner(authorization)
        return app.state.runtime.live.snapshot(clock())

    @app.put("/api/live/control")
    async def live_control(
        control: ControlSettings, authorization: str | None = Header(default=None)
    ):
        owner(authorization)
        context = app.state.runtime.live
        context.step(clock(), force=True)  # Freshness must be checked before every manual request.
        context.set_control(control, clock())
        return context.snapshot(clock())

    @app.post("/api/devices/{device_id}/telemetry")
    async def telemetry(
        device_id: str, record: Telemetry, authorization: str | None = Header(default=None)
    ):
        context = device(device_id, authorization)
        now = clock()
        if record.device_id != device_id:
            raise HTTPException(422, "Payload device ID does not match URL")
        if abs(record.timestamp - now) > config.telemetry_timeout:
            raise HTTPException(409, "Telemetry timestamp is stale or in the future")
        previous = context.twin.state.telemetry
        if previous and record.timestamp <= previous.timestamp:
            raise HTTPException(409, "Duplicate or out-of-order telemetry")
        source = context.source
        assert isinstance(source, Esp32SensorSource) and not isinstance(source, MqttSensorSource)
        source.ingest(record, now)
        context.step(now, force=True)
        return {
            "accepted": True,
            "received_at": now,
            "state": context.twin.state.state,
            "command": source.latest_command.model_dump(mode="json"),
        }

    @app.get("/api/devices/{device_id}/command")
    async def command(device_id: str, authorization: str | None = Header(default=None)):
        context = device(device_id, authorization)
        context.step(clock(), force=True)
        return context.source.latest_command

    @app.post("/api/simulations", status_code=201)
    async def create_simulation(authorization: str | None = Header(default=None)):
        if not config.public_demo:
            owner(authorization)
        try:
            session_id, context = app.state.runtime.create_session(clock())
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {
            "session_id": session_id,
            "token": context.token,
            "snapshot": context.snapshot(clock()),
        }

    @app.get("/api/simulations/{session_id}/state")
    async def simulation_state(session_id: str, authorization: str | None = Header(default=None)):
        return session(session_id, authorization).snapshot(clock())

    @app.post("/api/simulations/{session_id}/actions")
    async def simulation_action(
        session_id: str, action: SimulationAction, authorization: str | None = Header(default=None)
    ):
        context = session(session_id, authorization)
        app.state.runtime.simulation_action(context, action.action, clock())
        return context.snapshot(clock())

    @app.put("/api/simulations/{session_id}/settings")
    async def simulation_settings(
        session_id: str,
        controls: SimulationControls,
        authorization: str | None = Header(default=None),
    ):
        context = session(session_id, authorization)
        app.state.runtime.simulation_controls(context, controls, clock())
        return context.snapshot(clock())

    @app.put("/api/simulations/{session_id}/control")
    async def simulation_control(
        session_id: str, control: ControlSettings, authorization: str | None = Header(default=None)
    ):
        context = session(session_id, authorization)
        context.set_control(control, clock())
        return context.snapshot(clock())

    last_diagnostic = [-1e12]

    async def diagnose(context):
        if not (config.llm_enabled and config.llm_api_url and config.llm_api_key):
            raise HTTPException(409, "Optional diagnostic provider is not configured")
        if clock() - last_diagnostic[0] < 60:
            raise HTTPException(
                429, "AI diagnostics are limited to one request per minute across the deployment"
            )
        last_diagnostic[0] = clock()
        from .llm import HTTPDiagnosticProvider, LLMReasoner

        reasoner = LLMReasoner(
            HTTPDiagnosticProvider(config.llm_api_url, config.llm_api_key, config.llm_model),
            enabled=True,
        )
        observation = context.twin.agent.observe(clock())
        result = await asyncio.to_thread(reasoner.explain, observation)
        if result is None:
            raise HTTPException(
                502, "AI diagnostics unavailable; deterministic supervision continues"
            )
        context.diagnostic = {"timestamp": clock(), **result.model_dump()}
        return context.diagnostic

    @app.post("/api/live/analysis")
    async def live_analysis(authorization: str | None = Header(default=None)):
        owner(authorization)
        return await diagnose(app.state.runtime.live)

    @app.post("/api/simulations/{session_id}/analysis")
    async def simulation_analysis(
        session_id: str, authorization: str | None = Header(default=None)
    ):
        return await diagnose(session(session_id, authorization))

    @app.delete("/api/simulations/{session_id}", status_code=204)
    async def remove_simulation(session_id: str, authorization: str | None = Header(default=None)):
        context = session(session_id, authorization)
        context.close()
        del app.state.runtime.sessions[session_id]

    return app


app = create_app()
