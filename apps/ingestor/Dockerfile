# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f apps/ingestor/Dockerfile .
# Needs two monorepo siblings: packages/sparkplug (decoding) and apps/api (shared ORM models).

FROM python:3.15-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src

COPY deploy/docker/deps.py deploy/docker/deps.py
COPY packages/sparkplug/pyproject.toml packages/sparkplug/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/ingestor/pyproject.toml apps/ingestor/pyproject.toml
RUN python deploy/docker/deps.py packages/sparkplug/pyproject.toml apps/api/pyproject.toml \
        apps/ingestor/pyproject.toml > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY packages/sparkplug packages/sparkplug
COPY apps/api/app apps/api/app
COPY apps/ingestor/ingestor apps/ingestor/ingestor
RUN pip install --no-deps ./packages/sparkplug ./apps/api ./apps/ingestor

FROM python:3.15-slim
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv
USER app
# The ingestor traps SIGTERM and flushes its buffer before exiting; exec form makes sure it gets it.
CMD ["industrial-ingestor"]
