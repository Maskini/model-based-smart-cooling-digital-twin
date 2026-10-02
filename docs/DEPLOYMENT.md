# Deploy the Live + Simulation portfolio app

The repository is prepared for deployment. Creating paid hosting resources is a separate owner-approved step.

## Render architecture

One Docker web service runs:

- Nginx on Render's assigned `PORT`, routing `/api/*` to FastAPI and the remaining paths (including WebSockets) to Streamlit.
- One FastAPI/Uvicorn process on internal port 8000, owning hardware state and isolated simulation sessions.
- Streamlit on internal port 8502, calling the same API.

Render terminates public HTTPS. ESP32 requests travel outbound over Wi-Fi/Internet to the public `/api/devices/{device_id}/telemetry` route; commands return in the response. No publicly exposed MQTT broker, inbound device port, separate frontend app or third-party database is required. MQTT remains available as an optional LAN adapter.

## Render setup

1. Create a Blueprint from this repository and branch `codex/implement-digital-twin` using `render.yaml`. After merging, change the deployment branch to `main` in the blueprint and service.
2. Review the current compute and disk cost before provisioning. The included plan is `0.5c-512mb` with a 1 GB persistent disk in Frankfurt. Start with the configured session limit and increase resources if actual usage requires it.
3. The blueprint generates separate `HARDWARE_API_TOKEN`, `ADMIN_API_TOKEN` and `DASHBOARD_PASSWORD` secrets. Keep these in Render's environment settings.
4. Public visitors can immediately use Simulation without signing in. Live values are read-only for visitors. Unlocking live controls requires the owner password; the dashboard keeps the admin token server-side.
5. For real hardware, copy the hardware token, device ID, public backend URL and trusted root CA into the ignored configuration for `firmware/smart_cooling_http` and flash it. See [the HTTP contract](HTTP_API.md).

Automatic deploys remain off. `/api/health` stays healthy when no ESP32 is connected, so an offline device does not make Render restart a functioning public demonstration. Child-process exits stop the service; Render can restart the complete stack. Docker's health check verifies both dashboard and API. CI additionally exercises public simulation, hardware authentication, safety and session isolation through Nginx.

## Environment variables

| Variable | Purpose / default |
|---|---|
| `PORT` | Public proxy port assigned by Render |
| `BACKEND_URL` | Dashboard-to-API URL; container sets `http://127.0.0.1:8000` |
| `DEVICE_ID` | Expected hardware identity; `cooling-01` |
| `HARDWARE_TRANSPORT` | `REST` by default; optional `MQTT` for LAN compatibility |
| `HARDWARE_API_TOKEN` | Device authentication; empty disables REST device access |
| `ADMIN_API_TOKEN` | Owner control and private API authentication |
| `DASHBOARD_PASSWORD` | Owner dashboard login |
| `PUBLIC_DEMO` | `true`: anonymous isolated simulations and read-only live display |
| `DATABASE_PATH` | Base path; live history uses sibling `*.live.sqlite` on `/data` |
| `TELEMETRY_TIMEOUT` | Seconds before hardware is Offline; default 10 |
| `SIMULATION_START_TEMPERATURE` | 27 °C |
| `SIMULATION_HUMIDITY` | 47% |
| `SIMULATION_HEAT_LOAD` | 0.12 °C/s |
| `SIMULATION_MAX_SESSIONS` | 16 concurrent visitor contexts |
| `SIMULATION_SESSION_TTL` | 900 seconds without visitor activity |
| `AGENT_ENABLED` | Autonomous supervision enabled by default |
| `LLM_ENABLED` | Optional diagnostics disabled by default |
| `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL` | Optional diagnostic provider adapter configuration |

No secrets are written into the image or Git. Keep `.env` and firmware `config.h` local. A private dashboard (`PUBLIC_DEMO=false`) needs both the owner password and admin token configured.

## Docker server

```bash
docker compose -f compose.deploy.yml up -d --build
docker compose -f compose.deploy.yml ps
```

The default host binding is `127.0.0.1:8501`. Use a trusted HTTPS reverse proxy to publish the service, forwarding WebSockets, or access it through `ssh -L 8501:127.0.0.1:8501 your-server`. Set owner/device secrets in `.env` to enable live hardware operations. Without them, public simulation still works and hardware access stays disabled.

Keep one container replica and one Uvicorn worker. Session state and capabilities are in memory; multiple workers would require a shared session store, which this prototype intentionally avoids. A named volume persists hardware telemetry, control settings, agent memory and calibration parameters. Visitor simulation state is disposable. Back up the disk before deleting a service or volume.

## Local start

```bash
python scripts/run_demo.py
```

This starts FastAPI on 8000 and Streamlit on 8501. For separate terminals:

```bash
python -m uvicorn smart_cooling_twin.api:app --host 127.0.0.1 --port 8000
streamlit run dashboard/app.py --server.address=127.0.0.1 --server.headless=true
```

The optional original MQTT demonstration remains available with `python scripts/run_demo.py --local-broker --port 18883`. Select Live Hardware to inspect that MQTT source; visitor Simulation stays independent. Do not run the old standalone twin against the same MQTT device at the same time as the API's MQTT adapter.

References: [Render web services](https://render.com/docs/web-services), [persistent disks](https://render.com/docs/disks), [Blueprint reference](https://render.com/docs/blueprint-spec), [Streamlit reverse proxy guidance](https://docs.streamlit.io/knowledge-base/deploy/deploy-streamlit-domain-port-80).


## Free portfolio deployment

Use `render-free.yaml` for a Free Render web service; `render.yaml` retains the paid disk-backed option. The free configuration runs the same dashboard and API, defaults to public Simulation, disables external AI calls, and does not request a paid disk.

In Render, create a Blueprint from this GitHub repository and select branch `codex/implement-digital-twin` and Blueprint path `render-free.yaml`. Confirm that the proposed service has the **Free** instance type and no disk before deploying. If using manual Web Service creation instead, select Docker, the same branch, Free instance type, and the environment variables from `render-free.yaml`.

Render Free sleeps after 15 idle minutes; waking normally takes about one minute. Local SQLite history and simulation sessions reset on restart, redeployment or sleep. Free usage quotas apply; bandwidth/build overages may be billed if a payment method is present. Without a payment method, limits suspend services/builds instead. Review the workspace billing settings to keep the demo at zero cost. See [Render Free documentation](https://render.com/docs/free).

Use this for the portfolio demonstration. Continuous hardware monitoring with retained history needs durable storage and a suitable always-on service. Once deployed, add the actual public URL to the GitHub repository's Website field and README; do not substitute the local `127.0.0.1` address.
