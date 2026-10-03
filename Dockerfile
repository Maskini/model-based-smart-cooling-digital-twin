FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends nginx-light tini gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY simulator/ simulator/
RUN pip install .
COPY dashboard/ dashboard/
COPY scripts/ scripts/
COPY deployment/ deployment/
COPY .streamlit/ .streamlit/
RUN mkdir -p /data && chown app:app /data && chmod +x deployment/entrypoint.sh
ENV DATABASE_PATH=/data/twin.sqlite PORT=8501 PUBLIC_DEMO=true HARDWARE_TRANSPORT=REST AGENT_ENABLED=true LLM_ENABLED=false
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python scripts/deployment_health.py
ENTRYPOINT ["/usr/bin/tini", "--", "/app/deployment/entrypoint.sh"]
