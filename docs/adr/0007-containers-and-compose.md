# 0007: Container images and the full-stack compose file

- Status: accepted
- Date: 2026-11-08

## Context
Every service (api, ingestor, simulator, web) has to run with one command for demos and for an
end-to-end test in CI, and the same images should be what a real deployment (Kubernetes) runs.
The repo is a monorepo: the ingestor imports `packages/sparkplug` and the API's ORM models.

## Decision
- **One Dockerfile per app, built from the repo root** (`docker build -f apps/x/Dockerfile .`), so
  siblings are in the build context. A root `.dockerignore` excludes `.env` files, venvs,
  `node_modules`, tests, `.git` and the notebook.
- **Multi-stage builds.** Python: a build stage installs into `/opt/venv`; the runtime stage is
  `python:3.15-slim` plus that venv, running as a non-root user (uid 10001), exec-form `CMD` so the
  process is PID 1 and gets SIGTERM. Web: `node:20.19-alpine` runs `npm ci && npm run build`; the
  runtime is `nginx:1.28-alpine` with only `dist/` (about 92 MB, no Node).
- **Dependency layer caching:** `deploy/docker/deps.py` lists third-party dependencies from the
  `pyproject.toml` files; they're installed before the source is copied, then the local packages
  go in with `--no-deps`. A code change only rebuilds the last layer.
- **nginx is the production twin of the Vite proxy:** `/api/` is proxied with the prefix stripped,
  `/ws/` with `Upgrade`/`Connection` headers and a 1 h read timeout, `/assets/*` (hashed) cached
  for a year, `index.html` `no-cache`, and an SPA fallback. The `/ws/` access log omits the query
  string.
- **Migrations are a one-shot `migrate` service** (the API image running `alembic upgrade head`);
  `api` and `ingestor` wait for `service_completed_successfully`.
- **Health-gated startup:** `db` (pg_isready), `mqtt` (`mosquitto_sub` on a retained `$SYS`
  topic), and `api` (`/ready`, which checks the DB) have healthchecks; dependents use
  `service_healthy`.
- **Secrets:** compose passes `JWT_SECRET` through from the shell (`${JWT_SECRET:-}`). The API's
  Settings now require it to be non-empty, so the stack fails fast with a clear error. `:?` was
  rejected because compose interpolates the whole file, which would break `up -d db mqtt`.
- **Token redaction:** a logging filter (`app/log_redaction.py`) rewrites `token=...` to
  `token=[redacted]` in uvicorn's log lines, closing the log-leak risk noted in ADR 0005.
- **CI (`stack-ci.yml`):** build all images, `up`, wait for `/api/ready` through nginx, then
  assert the SPA loads, sign-up and login work through the proxy, at least 3 assets were
  auto-registered from DBIRTH, and readings are in the DB. Logs are dumped on failure.

## Alternatives
- **Migrations on API startup:** simpler, but N replicas race to migrate, and a failed migration
  crash-loops the API. In Kubernetes this becomes an init container or a pre-deploy Job.
- **One generic Python Dockerfile with build args:** less duplication, harder to read. Three
  short, explicit files won.
- **Lock files for Python (uv / pip-tools):** builds currently resolve `>=` ranges, so two builds
  can differ. `uv lock` + `uv sync --frozen` is the next step for reproducible images. The web
  image is already locked (`npm ci` + `package-lock.json`).
- **Distroless or Alpine Python images:** smaller, but Alpine's musl breaks many wheels and
  distroless has no shell for debugging. Slim is the pragmatic default.
- **Building and pushing to GHCR in CI:** deferred until there's somewhere to deploy to.
- **CORS instead of a reverse proxy:** see ADR 0006.

## Consequences
- `docker compose up` brings up the whole platform; the dashboard is on :8080, Swagger on :8000.
- The compose file holds dev-only database credentials; anything real would inject them as secrets.
- nginx resolves the API hostname at startup; recreating only `api` with a new IP needs a `web`
  restart (not an issue behind a Kubernetes Service).
- Python images are ~230–360 MB, mostly the base image and asyncpg/pydantic-core wheels.
- A fresh database has no users; sign up (viewer) and promote with SQL until the admin endpoint
  exists.
