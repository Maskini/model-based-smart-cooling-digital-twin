"""Presentation only. Runtime owns control; the UI submits validated settings."""

import time
import pandas as pd
import altair as alt
import streamlit as st
from smart_cooling_twin.config import Settings
from smart_cooling_twin.dashboard_auth import require_dashboard_access
from smart_cooling_twin.models import ControlSettings, SimulatorSettings
from smart_cooling_twin.repository import Repository

st.set_page_config(page_title="Smart Cooling Digital Twin", page_icon="❄️", layout="wide")
config = Settings.from_env()
require_dashboard_access()
st.title("❄️ Model-Based Digital Twin")
st.caption("Smart cooling · Physical state, predictive model and autonomous supervision")


@st.fragment(run_every=2)
def live_view():
    repo = Repository(config.database_path)
    try:
        snapshot = repo.get("snapshot")
        if not snapshot:
            st.info("Waiting for the twin runtime. Start python -m smart_cooling_twin.")
            return
        state = snapshot["state"]
        t = state["telemetry"] or {}
        stale = time.time() - snapshot["timestamp"] > 5
        if stale:
            st.error("Runtime heartbeat is stale. Displayed values are historical.")
        columns = st.columns(3) + st.columns(3)
        for column, label, value in zip(
            columns,
            [
                "Temperature",
                "Humidity",
                "Fan measured / command",
                "Twin state",
                "Mode",
                "MQTT / Device",
            ],
            [
                f"{t['temperature']:.2f} °C" if t else "—",
                f"{t['humidity']:.1f} %" if t else "—",
                f"{t.get('fan_speed', 0):.0f} / {state['fan_command']:.0f} %",
                state["state"],
                state["mode"],
                f"{'Online' if state['mqtt_connected'] and not stale else 'Offline'} / "
                f"{'Online' if state['device_online'] and not stale else 'Offline'}",
            ],
        ):
            column.metric(label, value)
        twin_tab, agent_tab, history_tab = st.tabs(["Digital Twin", "Agent", "History"])
        with twin_tab:
            metrics = state["metrics"]
            cols = st.columns(4)
            prediction = state.get("prediction")
            cols[0].metric(
                "Predicted in 2 seconds",
                f"{prediction['predicted_temperature']:.3f} °C" if prediction else "—",
            )
            cols[1].metric(
                "Prediction error",
                f"{metrics['prediction_error']:.3f} °C"
                if metrics["prediction_error"] is not None
                else "—",
            )
            cols[2].metric(
                "Rolling MAE",
                f"{metrics['rolling_mae']:.3f} °C" if metrics["rolling_mae"] is not None else "—",
            )
            cols[3].metric("Model health", state["model_health"])
            predictions = repo.recent("predictions", 300)
            if predictions:
                frame = pd.DataFrame(predictions)
                frame["time"] = pd.to_datetime(frame.target_timestamp, unit="s", utc=True)
                temperatures = frame.rename(
                    columns={
                        "measured_temperature": "Measured",
                        "predicted_temperature": "Predicted",
                    }
                ).melt(
                    id_vars="time",
                    value_vars=["Measured", "Predicted"],
                    var_name="Series",
                    value_name="Temperature",
                )
                chart = (
                    alt.Chart(temperatures)
                    .mark_line()
                    .encode(
                        x=alt.X("time:T", title="Time (UTC)"),
                        y=alt.Y(
                            "Temperature:Q", title="Temperature (°C)", scale=alt.Scale(zero=False)
                        ),
                        color=alt.Color("Series:N", scale=alt.Scale(range=["#43d9c0", "#4b91ff"])),
                        tooltip=["time:T", "Series:N", alt.Tooltip("Temperature:Q", format=".3f")],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart, use_container_width=True)
                st.line_chart(
                    frame.set_index("time")[["prediction_error", "rolling_mae"]], height=200
                )
            st.subheader("Model parameters")
            st.json(snapshot["parameters"])
        with agent_tab:
            st.write(
                "Agent enabled:", snapshot["agent_enabled"], "· Status:", state["model_health"]
            )
            events = repo.recent("agent_events", 100)
            if events:
                last = events[-1]
                st.write("Current assessment / last decision:", last["decision"])
                st.write("Last action:", last["action"]["kind"])
                st.write("Reason:", last["reason"])
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                k: (
                                    pd.to_datetime(event[k], unit="s", utc=True).isoformat()
                                    if k == "timestamp"
                                    else event[k]
                                )
                                for k in [
                                    "timestamp",
                                    "decision",
                                    "reason",
                                    "actual_outcome",
                                    "verification_status",
                                ]
                            }
                            for event in events
                        ]
                    ),
                    hide_index=True,
                )
            st.subheader("Active alerts")
            st.json(repo.get("active_alerts") or {})
            st.subheader("Recent calibration")
            st.json(repo.recent("calibrations", 1))
        with history_tab:
            records = repo.recent("telemetry", 500)
            st.dataframe(pd.DataFrame(records), hide_index=True)
            st.download_button(
                "Download recent telemetry",
                pd.DataFrame(records).to_csv(index=False),
                "telemetry.csv",
                "text/csv",
            )
    finally:
        repo.close()


live_view()
repo = Repository(config.database_path)
try:
    current = ControlSettings.model_validate(repo.get("control") or {})
    with st.sidebar.form("controls"):
        st.subheader("Controller")
        mode = st.selectbox("Mode", ["AUTO", "MANUAL"], index=0 if current.mode == "AUTO" else 1)
        manual = st.slider("Manual fan %", 0, 100, int(current.manual_fan))
        setpoint = st.slider("Setpoint °C", 20.0, 35.0, float(current.setpoint))
        if st.form_submit_button("Apply controller settings"):
            repo.set(
                "control",
                ControlSettings(mode=mode, manual_fan=manual, setpoint=setpoint).model_dump(),
            )
            st.success("Settings submitted to runtime safety checks.")
    if config.simulation_mode:
        sim = SimulatorSettings.model_validate(repo.get("simulator") or {})
        with st.sidebar.form("simulator"):
            st.subheader("Simulator disturbances")
            heat = st.slider("Heat load °C/s", 0.0, 0.5, float(sim.heat_load), 0.01)
            ambient = st.slider("Ambient °C", 0.0, 45.0, float(sim.ambient_temperature))
            effectiveness = st.slider(
                "Fan effectiveness °C/s", 0.0, 0.5, float(sim.fan_effectiveness), 0.01
            )
            noise = st.slider("Sensor noise σ °C", 0.0, 1.0, float(sim.noise), 0.01)
            fault = st.checkbox("Sensor failure", sim.sensor_failure)
            if st.form_submit_button("Apply disturbance"):
                repo.set(
                    "simulator",
                    SimulatorSettings(
                        heat_load=heat,
                        ambient_temperature=ambient,
                        fan_effectiveness=effectiveness,
                        noise=noise,
                        sensor_failure=fault,
                    ).model_dump(),
                )
                st.success("Disturbance submitted to simulator.")
finally:
    repo.close()

st.divider()
st.caption("Made by Maskini · © 2026 Maskini")
