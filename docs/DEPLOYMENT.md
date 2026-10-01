# Deploy the complete simulation

The hosted deployment runs the MQTT broker, physical simulator, twin runtime and Streamlit dashboard in one container. It keeps the broker on the container's loopback interface, serves the dashboard through the host's HTTPS endpoint, and stores SQLite history on a persistent disk. It is a single-instance simulation; do not scale replicas or connect real hardware to this deployment.

## Render

The repository includes `render.yaml` with a Docker web service in Frankfurt, a 1 GB persistent disk and a generated dashboard password. It deploys branch `codex/implement-digital-twin`; after merging, change the branch to `main` in Render and in the blueprint. Automatic deployment is disabled so pushes do not unexpectedly restart the running demonstration.

1. Sign in to Render and create a Blueprint from this GitHub repository.
2. Select `codex/implement-digital-twin` as the blueprint branch.
3. Review the service and disk price shown by Render before creating the resources. Persistent disks require paid compute.
4. Deploy and wait for the service to become healthy.
5. Find `DASHBOARD_PASSWORD` in the service's Environment settings. Enter it on the dashboard's sign-in screen. Do not commit it or post it in a GitHub issue.

Render's HTTP health check targets `/_stcore/health`. The process supervisor shuts down the container if any child exits, so Render can restart the whole stack. Docker's additional health check inspects the twin heartbeat and MQTT connection. Runtime data survives service restarts through `/data`; retain or back up the disk before deleting the service.

References: [Render Docker web services](https://render.com/docs/web-services), [persistent disks](https://render.com/docs/disks), [Blueprint configuration](https://render.com/docs/blueprint-spec), [current pricing](https://render.com/pricing).

## Existing server with Docker

```bash
# In .env, set DASHBOARD_PASSWORD to a unique random value of at least 16 characters.
docker compose -f compose.deploy.yml up -d --build
docker compose -f compose.deploy.yml ps
```

The default address is `127.0.0.1:8501`. Use an HTTPS reverse proxy on the server to publish it; the proxy must support WebSockets. Alternatively, access it privately through an SSH tunnel:

```bash
ssh -L 8501:127.0.0.1:8501 your-server
```

The named Docker volume preserves the database. Do not use `docker compose down -v` unless you intend to remove history. Keep one container instance. A password change invalidates existing application sessions on their next full rerun; restart the service when rotating the deployment secret.

## Deployment behavior

- Starts the regular simulator. Disturbances are controlled by the dashboard rather than the timed demo script.
- Requires a dashboard password before any data or control forms are rendered.
- Keeps MQTT private to the container; port 1883 is not exposed.
- Forces simulation mode and disables external LLM calls.
- Starts service processes as a non-root user; the entrypoint only prepares disk ownership before dropping privileges.
- Stops all processes on SIGTERM and fails the service if a child exits.
- Builds without local secrets, databases, virtual environments or firmware credentials.

The local development commands and optional unprotected localhost dashboard still work. This shared-password deployment is intended for a personal demonstration, not multi-user access management.
