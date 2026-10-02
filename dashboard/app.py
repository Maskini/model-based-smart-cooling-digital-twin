"""One API-backed portfolio dashboard for live hardware and isolated visitor simulations."""

from datetime import datetime, timezone
import hashlib
import os
import pandas as pd
import altair as alt
import streamlit as st
from smart_cooling_twin.api_client import APIError, TwinAPIClient
from smart_cooling_twin.config import Settings
from smart_cooling_twin.dashboard_auth import require_dashboard_access

st.set_page_config(
    page_title="Model-Based Smart Cooling Digital Twin", page_icon="❄️", layout="wide"
)
config = Settings.from_env()
api = TwinAPIClient(config.backend_url)
if not config.public_demo:
    if not os.environ.get("DASHBOARD_PASSWORD"):
        st.error("Private dashboard access requires an owner password.")
        st.stop()
    require_dashboard_access()

st.title("❄️ Model-Based Smart Cooling Digital Twin")
st.caption(
    "A physical system, a predictive model, and an autonomous supervisor — connected in real time."
)
st.markdown(
    "**Explore without hardware:** choose Simulation and run the guided scenario. "
    "**Live Hardware:** an ESP32 sends readings over Wi-Fi/HTTPS; the backend returns safety-validated cooling commands."
)
mode = st.radio(
    "Operating mode", ["Simulation", "Live Hardware"], horizontal=True, key="operating_mode"
)


def owner_authenticated() -> bool:
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    return (
        bool(password)
        and st.session_state.get("dashboard_authenticated")
        == hashlib.sha256(password.encode()).hexdigest()
    )


def footer():
    st.divider()
    st.caption("Made by Maskini · © 2026 Maskini")


def request(method: str, path: str, data: dict | None = None, token: str = ""):
    try:
        return api.request(method, path, token=token, data=data)
    except APIError as exc:
        st.error(str(exc))
        if exc.status == 404 and path.startswith("/api/simulations/"):
            st.session_state.pop("simulation_session", None)
            st.info("Your demo session expired. Use “Reconnect / new session” to begin again.")
        return None


if st.button("Reconnect / new session"):
    old = st.session_state.pop("simulation_session", None)
    if old:
        request("DELETE", "/api/simulations/" + old["session_id"], token=old["token"])
    st.rerun()

if mode == "Simulation":
    if "simulation_session" not in st.session_state:
        created = request(
            "POST",
            "/api/simulations",
            token=config.admin_api_token if not config.public_demo else "",
        )
        if created:
            st.session_state.simulation_session = {
                "session_id": created["session_id"],
                "token": created["token"],
            }
    session = st.session_state.get("simulation_session")
    if not session:
        st.info(
            "Start the backend with: python -m uvicorn smart_cooling_twin.api:app --host 127.0.0.1 --port 8000"
        )
        footer()
        st.stop()
    base, token = "/api/simulations/" + session["session_id"], session["token"]
    st.info(
        "SIMULATION · Your own demo session. No ESP32 is required; these controls cannot operate physical hardware."
    )
else:
    base = "/api/live"
    token = config.admin_api_token if owner_authenticated() or not config.public_demo else ""
    st.info(
        "LIVE · Values come from the configured ESP32. The dashboard stays available when the device is offline."
    )

snapshot = request("GET", base + "/state", token=token)
if snapshot:
    control = snapshot["control"]
    if mode == "Simulation":
        columns = st.columns(3)
        actions = [
            ("Start Simulation", "START"),
            ("Stop Simulation", "STOP"),
            ("Reset", "RESET"),
            ("Increase Temperature", "INCREASE"),
            ("Simulate Overheating", "OVERHEAT"),
            ("Run Demo Scenario", "DEMO"),
        ]
        for index, (label, action) in enumerate(actions):
            if columns[index % 3].button(
                label, type="primary" if action == "DEMO" else "secondary", width="stretch"
            ):
                result = request("POST", base + "/actions", {"action": action}, token)
                if result:
                    # Refresh editable defaults after a reset rather than retaining prior widget values.
                    for key in list(st.session_state):
                        if key.startswith("sim_edit_"):
                            del st.session_state[key]
                    st.rerun()
        telemetry = snapshot["state"]["telemetry"] or {}
        settings = snapshot["simulation"]["settings"]
        with st.sidebar.form("simulation_settings"):
            st.subheader("Simulation controls")
            temperature = st.number_input(
                "Temperature °C",
                -40.0,
                60.0,
                float(telemetry.get("temperature", config.simulation_start_temperature)),
                key="sim_edit_temperature",
            )
            humidity = st.slider(
                "Humidity %",
                0.0,
                100.0,
                float(telemetry.get("humidity", 47)),
                key="sim_edit_humidity",
            )
            heat = st.slider(
                "Heat load °C/s", 0.0, 2.0, float(settings["heat_load"]), 0.01, key="sim_edit_heat"
            )
            target = st.slider(
                "Target temperature °C",
                20.0,
                35.0,
                float(control["setpoint"]),
                key="sim_edit_target",
            )
            with st.expander("Advanced disturbances"):
                ambient = st.slider(
                    "Ambient °C", -10.0, 50.0, float(settings["ambient_temperature"])
                )
                effectiveness = st.slider(
                    "Fan effectiveness °C/s", 0.0, 3.0, float(settings["fan_effectiveness"]), 0.01
                )
                noise = st.slider("Sensor noise σ °C", 0.0, 1.0, float(settings["noise"]), 0.01)
                fault = st.checkbox("Sensor failure", settings["sensor_failure"])
            st.caption(
                "Applying settings ends the guided scenario and starts a new measurement segment."
            )
            if st.form_submit_button("Apply simulation settings"):
                result = request(
                    "PUT",
                    base + "/settings",
                    {
                        "temperature": temperature,
                        "humidity": humidity,
                        "heat_load": heat,
                        "target_temperature": target,
                        "ambient_temperature": ambient,
                        "fan_effectiveness": effectiveness,
                        "noise": noise,
                        "sensor_failure": fault,
                    },
                    token,
                )
                if result:
                    st.rerun()
    allow_controls = mode == "Simulation" or owner_authenticated()
    if mode == "Live Hardware" and not allow_controls:
        with st.sidebar:
            st.caption("Live hardware controls are reserved for the owner.")
            if st.checkbox("Unlock owner controls"):
                if not os.environ.get("DASHBOARD_PASSWORD") or not config.admin_api_token:
                    st.warning("Owner control credentials have not been configured.")
                else:
                    require_dashboard_access()
                    st.rerun()
    if allow_controls:
        with st.sidebar.form("controller"):
            st.subheader("Deterministic controller")
            automatic = st.selectbox(
                "Control mode", ["AUTO", "MANUAL"], index=0 if control["mode"] == "AUTO" else 1
            )
            manual = st.slider("Manual fan %", 0, 100, int(control["manual_fan"]))
            setpoint = st.slider("Controller target °C", 20.0, 35.0, float(control["setpoint"]))
            st.caption("The fixed 40 °C safety limit overrides manual demand.")
            if st.form_submit_button("Apply controller settings"):
                if request(
                    "PUT",
                    base + "/control",
                    {"mode": automatic, "manual_fan": manual, "setpoint": setpoint},
                    token,
                ):
                    st.rerun()


def utc_time(value):
    return (
        datetime.fromtimestamp(value, timezone.utc).strftime("%H:%M:%S UTC")
        if value
        else "No readings yet"
    )


@st.fragment(run_every=2)
def live_view():
    current = request("GET", base + "/state", token=token)
    if not current:
        return
    state, telemetry = current["state"], current["state"]["telemetry"] or {}
    simulation = current["simulation"]
    cooling = state["fan_command"] > 0
    paused = simulation is not None and not simulation["running"]
    offline = simulation is None and current["device_status"] == "Offline"
    cooling_label = f"{'ON' if cooling else 'OFF'} · {state['fan_command']:.0f}%"
    if paused:
        cooling_label = "PAUSED"
    elif offline:
        cooling_label = "UNKNOWN · Offline"
    cols = st.columns(3) + st.columns(3)
    values = [
        ("Temperature", f"{telemetry['temperature']:.2f} °C" if telemetry else "—"),
        ("Humidity", f"{telemetry['humidity']:.1f} %" if telemetry else "—"),
        (
            "Cooling",
            cooling_label,
        ),
        (
            "Device status",
            ("Running" if simulation["running"] else "Stopped")
            if simulation
            else current["device_status"],
        ),
        ("Digital Twin status", state["state"]),
        ("Current mode", current["operating_mode"]),
    ]
    for column, (label, value) in zip(cols, values):
        column.metric(label, value)
    reported_fan = f"{telemetry['fan_speed']:.0f}%" if telemetry else "No readings yet"
    st.caption(
        f"Last update: {utc_time(current['last_update'])} · Target: {current['control']['setpoint']:.1f} °C · "
        f"Last reported fan PWM: {reported_fan} · Control: {state['mode']}"
    )
    if telemetry.get("servo_angle") is not None:
        st.caption(f"Reported servo angle: {telemetry['servo_angle']:.0f}°")
    else:
        st.caption(
            "Actuator: PWM cooling fan. Servo position is shown when supplied by the hardware."
        )
    if not simulation and current["device_status"] == "Offline":
        st.warning(
            "ESP32 offline. Actual cooling cannot be confirmed. Any readings shown are historical; "
            "the backend requests safe fallback and the device firmware has a local watchdog. "
            "You can use Simulation immediately."
        )
    if (
        config.llm_enabled
        and config.llm_api_url
        and config.llm_api_key
        and (mode == "Simulation" or owner_authenticated())
    ):
        if st.button("Request optional AI explanation"):
            request("POST", base + "/analysis", token=token)
    if current["analysis"].get("llm"):
        diagnostic = current["analysis"]["llm"]
        st.info(
            "AI diagnostic (" + utc_time(diagnostic["timestamp"]) + "): " + diagnostic["summary"]
        )
        st.caption("Optional provider output; it has no actuator authority.")
    st.subheader("Agent analysis")
    st.write(current["analysis"]["summary"])
    st.caption(
        "Deterministic supervisor · Safety decisions use application rules; an LLM cannot set actuator commands."
    )
    for advice in current["analysis"]["recommendations"]:
        st.markdown("• " + advice)
    if simulation and simulation["phase"] != "IDLE":
        st.subheader("Guided demo · " + simulation["phase"].replace("_", " ").title())
        if simulation["phase"] == "COMPLETE":
            st.success(
                "Demo complete: overheating detected, cooling activated, temperature recovered, cooling switched off."
            )
        for event in simulation["scenario_events"]:
            st.write(f"{utc_time(event['timestamp'])} · {event['description']}")
    overview, model_tab, agent_tab = st.tabs(
        ["Temperature & transitions", "Model & validation", "Supervisor history"]
    )
    with overview:
        history = current["history"]
        if history:
            frame = pd.DataFrame(history)
            frame["time"] = pd.to_datetime(frame.timestamp, unit="s", utc=True)
            chart = (
                alt.Chart(frame)
                .mark_line(color="#43d9c0")
                .encode(
                    x=alt.X("time:T", title="Time (UTC)"),
                    y=alt.Y("temperature:Q", title="Temperature (°C)", scale=alt.Scale(zero=False)),
                    tooltip=[
                        "time:T",
                        alt.Tooltip("temperature:Q", format=".2f"),
                        "humidity:Q",
                        "fan_speed:Q",
                    ],
                )
            )
            thresholds = pd.DataFrame(
                {
                    "level": [current["control"]["setpoint"], 40],
                    "Threshold": ["Target", "Overheating"],
                }
            )
            rules = (
                alt.Chart(thresholds)
                .mark_rule(strokeDash=[5, 5])
                .encode(
                    y="level:Q",
                    color=alt.Color("Threshold:N", scale=alt.Scale(range=["#4b91ff", "#ff6565"])),
                )
            )
            st.altair_chart((chart + rules).properties(height=300), width="stretch")
            st.download_button(
                "Download recent telemetry", frame.to_csv(index=False), "telemetry.csv", "text/csv"
            )
        st.subheader("State transitions")
        if current["transitions"]:
            transitions = pd.DataFrame(current["transitions"])
            transitions["timestamp"] = transitions.timestamp.map(utc_time)
            st.dataframe(transitions, hide_index=True, width="stretch")
        else:
            st.caption("State transitions will appear when data arrives.")
    with model_tab:
        metrics = state["metrics"]
        cols = st.columns(3)
        prediction = state.get("prediction")
        cols[0].metric(
            "Predicted in 2 seconds",
            f"{prediction['predicted_temperature']:.3f} °C" if prediction else "—",
        )
        cols[1].metric(
            "Rolling MAE",
            f"{metrics['rolling_mae']:.3f} °C" if metrics["rolling_mae"] is not None else "—",
        )
        cols[2].metric("Model health", state["model_health"])
        if current["predictions"]:
            frame = pd.DataFrame(current["predictions"])
            frame["time"] = pd.to_datetime(frame.target_timestamp, unit="s", utc=True)
            st.line_chart(
                frame.set_index("time")[["measured_temperature", "predicted_temperature"]],
                height=220,
            )
            st.line_chart(frame.set_index("time")[["prediction_error", "rolling_mae"]], height=180)
        st.json(current["parameters"])
        st.caption(
            "First-order thermal approximation. Predictions assume constant ambient temperature and applied cooling over the forecast interval."
        )
    with agent_tab:
        st.write("Autonomous supervisor enabled:", current["agent_enabled"])
        events = current["agent_events"]
        if events:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            k: e[k]
                            for k in (
                                "timestamp",
                                "decision",
                                "reason",
                                "actual_outcome",
                                "verification_status",
                            )
                        }
                        for e in events
                    ]
                ),
                hide_index=True,
            )
        st.subheader("Active alerts")
        st.json(current["analysis"]["alerts"])
        st.subheader("Recent calibrations")
        st.json(current["calibrations"])


live_view()
footer()
