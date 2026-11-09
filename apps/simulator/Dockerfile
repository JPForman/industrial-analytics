# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f apps/simulator/Dockerfile .

FROM python:3.15-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src

COPY deploy/docker/deps.py deploy/docker/deps.py
COPY packages/sparkplug/pyproject.toml packages/sparkplug/pyproject.toml
COPY apps/simulator/pyproject.toml apps/simulator/pyproject.toml
RUN python deploy/docker/deps.py packages/sparkplug/pyproject.toml apps/simulator/pyproject.toml \
        > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY packages/sparkplug packages/sparkplug
COPY apps/simulator/simulator apps/simulator/simulator
RUN pip install --no-deps ./packages/sparkplug ./apps/simulator

FROM python:3.15-slim
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv
USER app
CMD ["industrial-simulator"]
