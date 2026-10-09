FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce AS build
WORKDIR /build
COPY requirements/py311-runtime.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes --prefix=/install -r /tmp/requirements.txt
COPY pyproject.toml README.md ./
COPY app ./app
COPY mcp_server ./mcp_server
COPY scripts ./scripts
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir=/wheel .

FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 EVENTOPS_HOST=0.0.0.0 \
    EVENTOPS_DATABASE=/var/lib/eventops/eventops.sqlite3 EVENTOPS_SEED_CATALOG=true \
    EVENTOPS_AGENT_MODE=offline
RUN useradd --system --uid 10001 --create-home appuser && mkdir -p /var/lib/eventops \
    && chown appuser:appuser /var/lib/eventops
COPY --from=build /install /usr/local
COPY --from=build /wheel /tmp/wheel
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheel/*.whl \
    && rm -rf /tmp/wheel
USER 10001:10001
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
