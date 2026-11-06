# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Purpose and working style

This project is interview prep for a full-stack role at EWI (Buffalo Manufacturing Works): Python/FastAPI, React/TypeScript, SQL, Docker/Kubernetes, CI/CD, industrial protocols (MQTT, Sparkplug B, OPC UA), and architecture judgment. It is built to a professional standard, as if it were a real shop-floor system.

- **The user is learning as we build.** Pause at each meaningful step to explain the key concept, package, or trade-off before or as you introduce it. Keep explanations short and tied to the interview (why this choice, what the alternative was).
- Record significant design decisions as ADRs in `docs/adr/` (context, decision, alternatives, consequences).
- Work on feature branches and open PRs so CI is exercised; do not commit or push without the user asking.

## Product

A shop-floor telemetry platform. Simulated machines (laser, stamping press, 3D printer) publish Sparkplug B (NBIRTH/DDATA/NDEATH) to a Mosquitto broker. An ingestor stores readings in Postgres/TimescaleDB, tracks batches/runs and evaluates alarm rules. A FastAPI service serves REST plus a WebSocket live feed. A React + TypeScript dashboard shows assets, live charts, alarms, run history, and role-gated admin.

```
simulator --MQTT/Sparkplug B--> mosquitto --> ingestor --> TimescaleDB
                                                                |
React (Vite/TS) <---------- REST + WebSocket ---------- FastAPI api
```

## Repo layout (monorepo)

Status key: **[exists]** in the repo now, **[planned]** not built yet. Update this as phases land.

- `apps/api/` **[exists]**: FastAPI, SQLAlchemy 2.0 async, Alembic, pytest. Auth + RBAC (`app/deps.py`: `get_current_user`, `require_role`), domain models, and the assets/tags router (`app/routers/assets.py`, shared helpers in `routers/common.py`: `Page`, `PageParams`, `commit_or_409`, `get_or_404`) are done; batches, readings, alarms, user admin, logging are next.
- `apps/ingestor/` **[planned]**: async MQTT consumer (aiomqtt + Sparkplug protobuf), batch inserts, alarm evaluation.
- `apps/simulator/` **[planned]**: fake machines publishing Sparkplug B.
- `apps/web/` **[planned]**: React + TypeScript + Vite, Vitest + Testing Library, Playwright smoke test.
- `deploy/` **[exists]**: `docker-compose.yml` (TimescaleDB only so far); Kubernetes manifests planned.
- `docs/` **[exists]**: architecture notes; `docs/adr/` holds decision records.
- `.github/workflows/` **[exists]**: `api-ci.yml` (ruff, mypy, migration round trip, pytest against a TimescaleDB service container, path-filtered). Web CI and GHCR image publishing planned.
- `.gitignore`, `.editorconfig`, `README.md` **[exists]**.

## Roadmap (phases)

1. Reset and repo bootstrap: git, private GitHub repo `industrial-analytics`, first CI. **[done; pre-commit and branch protection still open]**
2. Backend core **[in progress: scaffold, auth, Alembic, domain models/migration done; routers, pagination, logging pending]**: settings, async DB, Alembic, auth + RBAC (`get_current_user`, `require_role`), asset/tag/reading/alarm/batch routers, tests.
3. Messaging: Mosquitto, Sparkplug B simulator, ingestor, WebSocket live feed.
4. Frontend: login, role-gated routes, asset dashboard, live charts, alarms, batch history, tests.
5. Containers and CI/CD: multi-stage non-root Dockerfiles, compose, GitHub Actions, GHCR, Trivy, Dependabot, k8s manifests.
6. Interview polish: README with diagram, ADRs, seed data, demo script, trade-off talking points.

The full plan lives at `~/.claude/plans/the-purpose-of-this-structured-pumpkin.md`.

## Domain model (implemented in `apps/api/app/models.py`)

- `Asset` (machine; `edge_node_id` + `device_id` unique, map to Sparkplug topics) has many `Tag` (one metric, unique per asset).
- `Reading`: narrow time-series row `(tag_id, ts, value)`, composite PK `(tag_id, ts)`; a TimescaleDB hypertable with compression, created by hand-written SQL in the migration (see ADR 0002).
- `Batch`: a production run on an asset defined by a time window; readings are joined by time range, not stamped with a batch id.
- `AlarmRule` (config: tag, operator, threshold, severity) and `AlarmEvent` (history: triggered/cleared/acknowledged).
- `User` with `Role` viewer/engineer/admin (viewer by default on signup).

## Commands (run from `apps/api/`)

```
python3.15 -m venv .venv && .venv/bin/pip install -e ".[dev]"            # setup
docker compose -f ../../deploy/docker-compose.yml up -d db               # TimescaleDB on :5432
cp .env.example .env                                                     # set JWT_SECRET
.venv/bin/alembic upgrade head                                           # apply migrations
.venv/bin/uvicorn app.main:app --reload                                  # run; docs at /docs
.venv/bin/pytest                                                         # tests (in-memory SQLite by default)
TEST_DATABASE_URL=postgresql+asyncpg://... .venv/bin/pytest              # against Postgres (CI does this)
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app tests migrations
.venv/bin/alembic revision --autogenerate -m "msg"                       # then REVIEW the script
```

Gotchas:
- Autogenerated migrations miss TimescaleDB DDL and do not drop Postgres enum types on downgrade; hand-edit both, and test `upgrade head`, `downgrade base`, `upgrade head`.
- Never point `TEST_DATABASE_URL` at your dev DB: the fixture runs `drop_all` afterwards. Use a separate DB: `docker exec deploy-db-1 psql -U industrial -d industrial -c 'create database industrial_test'`, then `TEST_DATABASE_URL=postgresql+asyncpg://industrial:industrial@localhost:5432/industrial_test`.
- Async SQLAlchemy cannot lazy-load relationships (`MissingGreenlet`): use `selectinload`, and keep ORM objects out of response annotations (return Pydantic `*Out` models).
- Router convention: protect the whole router with `dependencies=[Depends(get_current_user)]`, then add `require_role(...)` per write endpoint (reads: any user; create/update: engineer+; delete: admin). Tests use the `auth_headers(Role.x)` fixture and a role-matrix test.
- Settings are lazy (`get_settings()`); tests set `JWT_SECRET` in `tests/conftest.py` before importing the app.
- SQLite does not enforce foreign keys by default, so FK behavior must be verified against Postgres.

## Legacy code

The earlier SQLite/FastAPI auth demo was moved out of the repo to `../industrialAnalytics_legacy/` (sibling directory; contains `backend/` and `EWIPrep.ipynb`). Its auth code has already been ported to `apps/api` (async), so it can be deleted whenever. What was ported:
- `backend/app/security.py`: bcrypt hashing and HS256 JWT create/decode (`decode_access_token` returns user id or `None`).
- `backend/app/routers/auth.py`: signup returns 409 on a duplicate email and always assigns the `viewer` role; login returns the same 401 for an unknown email and a wrong password, on purpose.
- `backend/app/schemas.py`: `UserOut` deliberately omits `password_hash` (never return raw ORM objects); passwords are 8-72 chars (bcrypt limit).
- The legacy app used `Base.metadata.create_all` with no migrations. The new project uses Alembic instead.

## Conventions

- Python 3.15 locally (the old venv was 3.15); pin the version in `pyproject.toml` and CI. Prefer a venv per app (`apps/<app>/.venv`, git-ignored).
- Secrets only in git-ignored `.env`; commit a `.env.example`. Settings come from pydantic-settings; a required secret must fail fast at import.
- Run commands from inside the relevant app directory unless a root `Makefile` or compose target says otherwise.
- Tests are required for new backend and frontend behaviour. Backend lint/type tools: ruff and strict mypy (configured in `apps/api/pyproject.toml`). Frontend lint and pre-commit hooks are not set up yet.
- Environment: docker 28, node 20 / npm 11, gh authenticated as JPForman, git on `main`.
