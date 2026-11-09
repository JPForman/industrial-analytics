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

- `apps/api/` **[exists]**: FastAPI, SQLAlchemy 2.0 async, Alembic, pytest. Auth + RBAC (`app/deps.py`: `get_current_user`, `require_role`), domain models, and the assets/tags router (`app/routers/assets.py`, shared helpers in `routers/common.py`: `Page`, `PageParams`, `commit_or_409`, `get_or_404`) and the batches router (`app/routers/batches.py`: start / complete / abort state machine) and the readings router (`app/routers/readings.py`: idempotent bulk ingest via ON CONFLICT DO NOTHING; keyset-paginated range query with required start/end) and the aggregate endpoint (`GET /tags/{id}/readings/aggregate`: TimescaleDB `time_bucket`, allowlisted bucket sizes, 2000-bucket cap, gaps left as gaps) and the live feed (ADR 0005: `app/mqtt_bridge.py` subscribes to the ingestor's `ia/v1/live/#` + `ia/v1/alarms` and runs from the FastAPI `lifespan`; `app/live.py` `Broadcaster` gives each client a bounded queue that drops oldest; `app/routers/live.py` `WS /ws/live?token=<jwt>&tag_id=N`, rejected before accept on a bad token; events are `{type: reading|alarm, ...}`) are done. Env adds `MQTT_HOST`, `MQTT_PORT`, `LIVE_BRIDGE_ENABLED`. The alarms router (`app/routers/alarms.py`: `GET /alarms?state=active|unacknowledged|all&asset_id&severity` flattened via one join in `_alarm_select()`, `GET /alarms/{id}`, `POST /alarms/{id}/acknowledge` engineer+, atomic `UPDATE ... WHERE acknowledged_at IS NULL`, 409 on a second ack) is done (committed on `feat/alarms-dashboard`, PR 10). Acks are not pushed live (that would need the API to publish to MQTT so all replicas see it); the UI refetches instead. User admin and logging are deferred.
- `packages/sparkplug/` **[exists]**: shared Sparkplug B library. `sparkplug_b.proto` is a subset of the official schema (same field numbers); `sparkplug_b_pb2.py/.pyi` are generated and committed. Regenerate with `docker run --rm -v "$PWD/sparkplug:/out" python:3.13-slim sh -c "pip install -q grpcio-tools && python -m grpc_tools.protoc -I/out --python_out=/out --pyi_out=/out /out/sparkplug_b.proto"` and keep the `protobuf>=` pin at or above the generator version. API: `Topic.parse/str`, `encode`, `decode`, `Metric`, `MessageType`, `DataType`.
- `apps/simulator/` **[exists]**: edge node `edge1` (group `BuffaloWorks`) with devices `laser1`, `press1`, `printer1`. `edge_node.py` builds messages (pure, tested); `main.py` does MQTT I/O (aiomqtt): NBIRTH/DBIRTH, DDATA every `INTERVAL_S`, NDEATH as Last Will, rebirth on `NCMD Node Control/Rebirth`, reconnect with backoff and bdSeq bump. Conventions: aliases are `(device_index+1)*100 + metric_index`; DBIRTH carries `Properties/AssetType` and `Properties/Unit/<metric>` string metrics. Env: `MQTT_HOST`, `MQTT_PORT`, `INTERVAL_S`, `SPIKE_PROB`, `SEED`, `GROUP_ID`, `EDGE_NODE_ID`.
- `apps/ingestor/` **[exists]**: one MQTT subscription to `spBv1.0/#` (ADR 0004). `state.py` is the pure Sparkplug state machine (bdSeq session tracking, seq gaps, alias maps, stale NDEATH ignored); `registry.py` upserts Asset/Tags from DBIRTH; `writer.py` is a bounded buffer (`deque(maxlen)`, drops oldest) with bulk `ON CONFLICT DO NOTHING` flushes and edge-triggered alarm open/clear (alarm state snapshot restored if a flush fails); `main.py` handles MQTT, rate-limited rebirth requests (NCMD), live republish to `ia/v1/live/{tag_id}` and `ia/v1/alarms` (JSON), signal-driven graceful shutdown. Env: `DATABASE_URL`, `MQTT_HOST`, `MQTT_PORT`, `FLUSH_INTERVAL_S`, `RULE_REFRESH_S`. Imports models from the API package; `app/base.py` holds `Base` so that works without `JWT_SECRET`.
- `apps/web/` **[exists]** (ADR 0006): React 19 + TypeScript strict + Vite 7, Vitest + Testing Library, Recharts. `src/api/client.ts` (`apiFetch` with `/api` prefix, `ApiError`, `qs`), `src/api/types.ts` (hand-mirrored Pydantic models), `src/auth/AuthContext.tsx` (JWT in memory only; `request()` logs out on 401; `hasRole` is cosmetic), `src/live/useLiveFeed.ts` (one socket per page, jittered exponential backoff, `onOpen` on every reconnect), `src/live/series.ts` (`mergePoints`: dedupe by timestamp, window trim), `src/components/` (`LoginPage`, `Dashboard` owns the feed and does the 5-minute REST backfill on each (re)connect, `AssetList`, `TagChart` live line or aggregate history with min–max band, `AlarmsPanel` refetches on `alarm` events, Acknowledge for engineer+, 409 treated as a refresh). Vite dev proxy: `/api/*` → API with the prefix stripped, `/ws` with `ws: true`; target from `API_URL` (default `http://localhost:8000`). Tests fake only `fetch` (`src/test/fakeApi.ts`) and `WebSocket`.
- `deploy/` **[exists]** (ADR 0007): `docker-compose.yml` is the full stack: `db` (TimescaleDB), `mqtt` (Mosquitto, config in `deploy/mosquitto/`, anonymous on 1883 for dev only), one-shot `migrate` (API image, `alembic upgrade head`), `api` (:8000), `ingestor`, `simulator`, `web` (nginx on :8080). Health-gated order: db → migrate → api → web. `deploy/nginx/default.conf.template` is the production twin of the Vite proxy (envsubst `API_UPSTREAM`). `deploy/docker/deps.py` lists third-party deps from pyproject files for a cached dependency layer. Each app has a multi-stage `Dockerfile` built from the repo root (root `.dockerignore`).
- `docs/` **[exists]**: `docs/adr/` holds decision records (0001 monorepo, 0002 TimescaleDB, 0003 Sparkplug B, 0004 separate ingestor, 0005 WebSocket live feed, 0006 web dashboard, 0007 containers and compose).
- `.github/workflows/` **[exists]**: `api-ci.yml` (ruff, mypy, migration round trip, pytest against a TimescaleDB service container) `python-libs-ci.yml` (matrix over `packages/sparkplug` and `apps/simulator`), `ingestor-ci.yml` (Postgres service), `web-ci.yml` (npm ci, lint, typecheck, test, build on Node 20.19), and `stack-ci.yml` (builds all images, `compose up`, end-to-end smoke test through nginx: SPA, signup/login, ≥3 auto-registered assets, readings in DB). All path-filtered. GHCR publishing deferred.
- `.gitignore`, `.editorconfig`, `.dockerignore`, `Makefile`, `README.md` (quickstart; full README with diagram in PR 12) **[exists]**.

## Roadmap

**Deadline: the interview is Monday 2026-11-09.** On Saturday 2026-11-07 the user chose "end-to-end demo first" with lighter teaching (key concepts, a walkthrough, one quiz per phase). Remaining work, one PR each, in order:

1. Mosquitto + Sparkplug B library + simulator **[done in PR 7]**
2. Ingestor: MQTT to DB, alias map from births, seq-gap rebirth, alarm evaluation **[done in PR 8]**
3. WebSocket live feed in the API **[done in PR 9]**
4. React/TS dashboard: login, assets, live chart, aggregates, alarms **[built in PR 10]**
5. Dockerfiles for every service, full-stack `docker compose up`, CI builds images **[built in PR 11]**
6. README with architecture diagram, plus an interview talking-points doc

Deliberately deferred (explain these, don't build them before Monday): alarm-rule CRUD UI, admin user-role endpoint, structured logging, Kubernetes manifests, GHCR publishing, pre-commit, branch protection (needs GitHub Pro on a private repo).

### Current state (handoff, updated 2026-11-08)

- PRs: #7 merged. **#8** `feat/ingestor` targets `main`, open. **#9** `feat/live-feed` (WebSocket live feed) is **stacked on #8** (base `feat/ingestor`), open. **#10** `feat/alarms-dashboard` (ready for review) is stacked on #9. **PR 11** `feat/docker` is stacked on #10. After #8 is squash-merged: `git fetch && git rebase --onto origin/main feat/ingestor feat/live-feed`, `git push --force-with-lease`, `gh pr edit 9 --base main`; repeat the same for the next branch after #9 merges. Ask the user before merging.
- Branch **`feat/alarms-dashboard`** = **PR #10** (ready for review) (base `feat/live-feed`): commit 1 is the alarms API (68 API tests pass on Postgres); commit 2 is the React dashboard in `apps/web` + `web-ci.yml` + ADR 0006 (13 Vitest tests, lint/typecheck/build clean; verified by hand against the live stack in Chrome: login, live charts with backfill, 1h/24h history, alarm filters).- `EWIPrep.ipynb` at the repo root shows as modified by the user. Not ours; leave it out of commits unless the user says otherwise.
- Branch **`feat/docker`** (from `feat/alarms-dashboard`) = **PR 11**: Dockerfiles, full-stack compose, nginx, `stack-ci.yml`, ADR 0007, plus `app/log_redaction.py` (uvicorn was logging the WS JWT; now `token=[redacted]`, tested) and `jwt_secret: Field(min_length=1)`. Verified locally: all images build, the stack comes up health-ordered, the smoke test passes on a fresh DB (`-p smoke`, then `down -v`), ingestor flushes on SIGTERM. Next: **PR 12**: README (architecture diagram, quickstart) + interview talking points.
- Quiz status: Phase 3 warm-up re-asked on 2026-11-08. Still shaky: the flush snapshot (they said "alarm triggered"; the real failure is a *missed* alarm on retry), WS query tokens (didn't know browsers can't set WS headers), slow-client isolation (answered `asyncio.wait`; the answer is `put_nowait` on a bounded per-client queue). Corrected; worth one more quick re-ask before the interview. Phase 4 (dashboard) quiz done: right on RBAC (but say authorization/403, not auth); weak on reconnect backfill (`onOpen` → REST backfill → `mergePoints`; the server can't replay because the Broadcaster keeps no history) and on why an alarm event triggers a refetch (event lacks the joined fields; a missed event would leave the panel wrong). Re-ask those two.
- On 2026-11-08 the user asked concept questions and got short answers: mypy vs Pydantic vs ruff, Alembic, asyncpg, SQLite vs Docker in tests, CI service containers (nothing is hosted), Docker image/container/volume, container vs VM, Kubernetes, cloud vs traditional hosting and edge+cloud hybrid, where data first hits the DB (the ingestor; raw readings are stored and aggregated at query time), WebSockets and our pub/sub, MQTT vs Sparkplug B vs Mosquitto, ingestor vs API communication (DB + broker only), tags/assets nomenclature, OPC UA vs MQTT (and Unified Namespace). These are good candidates for the talking-points doc (roadmap item 6).
- Unexplained once: a Postgres test run hung past 2 minutes, then passed in 28s on rerun (likely a leftover connection from a killed run). If CI hangs, look there.
- Testing gotcha: WebSocket tests use `httpx-ws` (`ASGIWebSocketTransport`). Open the client inside each test, not in a yield fixture (an anyio task group must exit in the task that entered it). A pre-accept close shows up as `WebSocketDisconnect(1008)` wrapped in an ExceptionGroup, not as HTTP 403.
- Dev DB (local `industrial`) contains demo user `demo@example.com` / `demo-password-1` (engineer), assets from the simulator (`edge1`: laser1, press1, printer1), and alarm rule 1 (laser1 `power_w` > 1500, critical). The test DB is `industrial_test`. Don't read `.env` files: the user denied that.
- Docker containers `deploy-db-1` and `deploy-mqtt-1` should be running (`docker compose -f deploy/docker-compose.yml up -d db mqtt` if not). The full containerized stack may also be running (`deploy-api-1`, `-web-1`, `-ingestor-1`, `-simulator-1`): it holds ports 8000/8080, so stop those services before running the apps from source.

Already done: repo bootstrap; API scaffold, auth/RBAC, Alembic, domain models (hypertable), assets/tags, batches (with race-safe finish), readings ingest + keyset query, `time_bucket` aggregates, MQTT + simulator (#7), ingestor (#8), WebSocket live feed (#9), alarms endpoint (PR 10, first commit).

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
- Full stack in containers: **`make up`** from the repo root (root `Makefile`: `up`, `down` = stop and keep data, `ps`, `logs s=<svc>`, `infra` = db + mqtt only). The first `make up` writes `deploy/.env` with a random `JWT_SECRET` (gitignored; compose reads it automatically; don't read it). Raw equivalent: `JWT_SECRET=... docker compose -f deploy/docker-compose.yml up -d --build`. Dashboard http://localhost:8080, Swagger http://localhost:8000/docs. A fresh DB has no users: sign up, then promote with SQL. After recreating only `api`, restart `web` (nginx caches the upstream IP). Never `down -v` the `deploy` project (it is the dev DB); use `-p <other>` for throwaway stacks.
- Local end-to-end run from source: `docker compose -f deploy/docker-compose.yml up -d db mqtt`, `alembic upgrade head` (from apps/api), then `apps/simulator/.venv/bin/industrial-simulator` and `apps/ingestor/.venv/bin/industrial-ingestor`. Start order doesn't matter: a late ingestor requests a rebirth. Alarm rules have no API yet; insert into `alarm_rules` with SQL (README has the statement). Model defaults like `AlarmRule.enabled` are Python-side only (no `server_default`), so raw SQL inserts must set them explicitly.
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
- Tests are required for new backend and frontend behaviour. Backend lint/type tools: ruff and strict mypy (configured in `apps/api/pyproject.toml`). Frontend (from `apps/web/`): `npm ci`, `npm run dev` (needs the API on :8000), `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. Pin npm deps with `--save-exact`. Pre-commit hooks are not set up yet.
- Environment: docker 28, node 20 / npm 11, gh authenticated as JPForman, git on `main`.
