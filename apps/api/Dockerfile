# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f apps/api/Dockerfile .

# --- build stage: resolve and install into a venv (anything needed only to build stays here) ---
FROM python:3.15-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src

# Dependencies first, in their own layer: only a pyproject change invalidates it.
COPY deploy/docker/deps.py deploy/docker/deps.py
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN python deploy/docker/deps.py apps/api/pyproject.toml > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# Then the code (changes often, cheap to reinstall).
COPY apps/api/app apps/api/app
RUN pip install --no-deps ./apps/api

# --- runtime stage: slim base + the venv, nothing else ---
FROM python:3.15-slim
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# Alembic config + scripts, so the same image runs migrations (`alembic upgrade head`).
COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
USER app
EXPOSE 8000
# Exec form: uvicorn is PID 1 and receives SIGTERM directly, so shutdown is graceful.
# --proxy-headers: trust X-Forwarded-* from nginx so client IPs/scheme are right.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
