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

- `apps/api/` **[exists]**: FastAPI, SQLAlchemy 2.0 async, Alembic, pytest. Auth + RBAC (`app/deps.py`: `get_current_user`, `require_role`), domain models, and the assets/tags router (`app/routers/assets.py`, shared helpers in `routers/common.py`: `Page`, `PageParams`, `commit_or_409`, `get_or_404`) and the batches router (`app/routers/batches.py`: start / complete / abort state machine) and the readings router (`app/routers/readings.py`: idempotent bulk ingest via ON CONFLICT DO NOTHING; keyset-paginated range query with required start/end) and the aggregate endpoint (`GET /tags/{id}/readings/aggregate`: TimescaleDB `time_bucket`, allowlisted bucket sizes, 2000-bucket cap, gaps left as gaps) are done; alarms, user admin, logging are next.
- `packages/sparkplug/` **[exists]**: shared Sparkplug B library. `sparkplug_b.proto` is a subset of the official schema (same field numbers); `sparkplug_b_pb2.py/.pyi` are generated and committed. Regenerate with `docker run --rm -v "$PWD/sparkplug:/out" python:3.13-slim sh -c "pip install -q grpcio-tools && python -m grpc_tools.protoc -I/out --python_out=/out --pyi_out=/out /out/sparkplug_b.proto"` and keep the `protobuf>=` pin at or above the generator version. API: `Topic.parse/str`, `encode`, `decode`, `Metric`, `MessageType`, `DataType`.
- `apps/simulator/` **[exists]**: edge node `edge1` (group `BuffaloWorks`) with devices `laser1`, `press1`, `printer1`. `edge_node.py` builds messages (pure, tested); `main.py` does MQTT I/O (aiomqtt): NBIRTH/DBIRTH, DDATA every `INTERVAL_S`, NDEATH as Last Will, rebirth on `NCMD Node Control/Rebirth`, reconnect with backoff and bdSeq bump. Conventions: aliases are `(device_index+1)*100 + metric_index`; DBIRTH carries `Properties/AssetType` and `Properties/Unit/<metric>` string metrics. Env: `MQTT_HOST`, `MQTT_PORT`, `INTERVAL_S`, `SPIKE_PROB`, `SEED`, `GROUP_ID`, `EDGE_NODE_ID`.
- `apps/ingestor/` **[exists]**: one MQTT subscription to `spBv1.0/#` (ADR 0004). `state.py` is the pure Sparkplug state machine (bdSeq session tracking, seq gaps, alias maps, stale NDEATH ignored); `registry.py` upserts Asset/Tags from DBIRTH; `writer.py` is a bounded buffer (`deque(maxlen)`, drops oldest) with bulk `ON CONFLICT DO NOTHING` flushes and edge-triggered alarm open/clear (alarm state snapshot restored if a flush fails); `main.py` handles MQTT, rate-limited rebirth requests (NCMD), live republish to `ia/v1/live/{tag_id}` and `ia/v1/alarms` (JSON), signal-driven graceful shutdown. Env: `DATABASE_URL`, `MQTT_HOST`, `MQTT_PORT`, `FLUSH_INTERVAL_S`, `RULE_REFRESH_S`. Imports models from the API package; `app/base.py` holds `Base` so that works without `JWT_SECRET`.
- `apps/web/` **[planned]**: React + TypeScript + Vite, Vitest + Testing Library.
- `deploy/` **[exists]**: `docker-compose.yml` with `db` (TimescaleDB) and `mqtt` (Mosquitto, config in `deploy/mosquitto/`, anonymous on 1883 for dev only). App services to be added.
- `docs/` **[exists]**: `docs/adr/` holds decision records (0001 monorepo, 0002 TimescaleDB, 0003 Sparkplug B, 0004 separate ingestor).
- `.github/workflows/` **[exists]**: `api-ci.yml` (ruff, mypy, migration round trip, pytest against a TimescaleDB service container) `python-libs-ci.yml` (matrix over `packages/sparkplug` and `apps/simulator`), and `ingestor-ci.yml` (Postgres service). Both path-filtered. Web CI and image builds planned.
- `.gitignore`, `.editorconfig`, `README.md` **[exists]**.

## Roadmap

**Deadline: the interview is Monday 2026-11-09.** On Saturday 2026-11-07 the user chose "end-to-end demo first" with lighter teaching (key concepts, a walkthrough, one quiz per phase). Remaining work, one PR each, in order:

1. Mosquitto + Sparkplug B library + simulator **[done in PR 7]**
2. Ingestor: MQTT to DB, alias map from births, seq-gap rebirth, alarm evaluation **[done in PR 8]**
3. WebSocket live feed in the API
4. React/TS dashboard: login, assets, live chart, aggregates, alarms
5. Dockerfiles for every service, full-stack `docker compose up`, CI builds images
6. README with architecture diagram, plus an interview talking-points doc

Deliberately deferred (explain these, don't build them before Monday): alarm-rule CRUD UI, admin user-role endpoint, structured logging, Kubernetes manifests, GHCR publishing, pre-commit, branch protection (needs GitHub Pro on a private repo).

Already done: repo bootstrap; API scaffold, auth/RBAC, Alembic, domain models (hypertable), assets/tags, batches (with race-safe finish), readings ingest + keyset query, `time_bucket` aggregates.

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
- Python monorepo siblings are installed editable with `--config-settings editable_mode=compat` (e.g. `pip install -e ../../packages/sparkplug -e ../api --config-settings editable_mode=compat`), otherwise mypy can't see them. `apps/api/app/py.typed` marks the API package as typed.
- Ingestor integration tests need `TEST_DATABASE_URL` (Postgres); they `drop_all`/`create_all`, so never point it at the dev DB.
- Local end-to-end run: `docker compose -f deploy/docker-compose.yml up -d`, `alembic upgrade head` (from apps/api), then `apps/simulator/.venv/bin/industrial-simulator` and `apps/ingestor/.venv/bin/industrial-ingestor`. Start order doesn't matter: a late ingestor requests a rebirth. Alarm rules have no API yet; insert into `alarm_rules` with SQL.
- Tests for TimescaleDB-only SQL (`time_bucket`) are marked skip-on-SQLite (`needs_timescale`); run them with `TEST_DATABASE_URL` pointing at the Postgres test DB (it inherits the extension from template1).
- Test fixtures build tables with `create_all`, so `readings` is a plain table in local tests (a hypertable only in CI's first test, after migrations). Verify hypertable behaviour against the migrated dev DB.
- Timestamps are UTC and must be timezone-aware on input (`AwareDatetime`); SQLite drops tz info, so `ReadingOut` re-attaches UTC.
- `migrations/env.py` has an `include_object` filter so autogenerate ignores TimescaleDB-managed indexes (`readings_ts_idx`); add new Timescale-created objects to `TIMESCALE_MANAGED_INDEXES` or autogenerate will propose dropping them.
- Business invariants live in the DB where possible (e.g. partial unique index `uq_batches_one_running_per_asset`), surfaced as 409 via `commit_or_409`. Server-owned fields (`status`, `started_at`, `ended_at`) are never accepted from clients; state changes are action endpoints (`POST /batches/{id}/complete`).
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
