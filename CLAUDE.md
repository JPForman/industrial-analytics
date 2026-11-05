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

- `apps/api/` **[planned]**: FastAPI, SQLAlchemy 2.0 async, Alembic, pytest.
- `apps/ingestor/` **[planned]**: async MQTT consumer (aiomqtt + Sparkplug protobuf), batch inserts, alarm evaluation.
- `apps/simulator/` **[planned]**: fake machines publishing Sparkplug B.
- `apps/web/` **[planned]**: React + TypeScript + Vite, Vitest + Testing Library, Playwright smoke test.
- `deploy/` **[planned]**: docker-compose and Kubernetes (kustomize) manifests.
- `docs/` **[exists]**: architecture notes; `docs/adr/` holds decision records.
- `.github/workflows/` **[planned]**: CI (lint, type-check, tests, image build) and image publishing to GHCR.
- `.gitignore`, `.editorconfig`, `README.md` **[exists]**.

## Roadmap (phases)

1. Reset and repo bootstrap: git, private GitHub repo `industrial-analytics`, pre-commit, first CI. **[in progress]**
2. Backend core: settings, async DB, Alembic, auth + RBAC (`get_current_user`, `require_role`), asset/tag/reading/alarm/batch routers, tests.
3. Messaging: Mosquitto, Sparkplug B simulator, ingestor, WebSocket live feed.
4. Frontend: login, role-gated routes, asset dashboard, live charts, alarms, batch history, tests.
5. Containers and CI/CD: multi-stage non-root Dockerfiles, compose, GitHub Actions, GHCR, Trivy, Dependabot, k8s manifests.
6. Interview polish: README with diagram, ADRs, seed data, demo script, trade-off talking points.

The full plan lives at `~/.claude/plans/the-purpose-of-this-structured-pumpkin.md`.

## Domain model (target)

Site/Asset, Tag (metric), Reading (TimescaleDB hypertable), Batch/Run, AlarmRule, AlarmEvent, User with `Role` (viewer/engineer/admin).

## Legacy code

The earlier SQLite/FastAPI auth demo was moved out of the repo to `../industrialAnalytics_legacy/` (sibling directory; contains `backend/` and `EWIPrep.ipynb`). Port from it in Phase 2 and then it can be deleted:
- `backend/app/security.py`: bcrypt hashing and HS256 JWT create/decode (`decode_access_token` returns user id or `None`).
- `backend/app/routers/auth.py`: signup returns 409 on a duplicate email and always assigns the `viewer` role; login returns the same 401 for an unknown email and a wrong password, on purpose.
- `backend/app/schemas.py`: `UserOut` deliberately omits `password_hash` (never return raw ORM objects); passwords are 8-72 chars (bcrypt limit).
- The legacy app used `Base.metadata.create_all` with no migrations. The new project uses Alembic instead.

## Conventions

- Python 3.15 locally (the old venv was 3.15); pin the version in `pyproject.toml` and CI. Prefer a venv per app (`apps/<app>/.venv`, git-ignored).
- Secrets only in git-ignored `.env`; commit a `.env.example`. Settings come from pydantic-settings; a required secret must fail fast at import.
- Run commands from inside the relevant app directory unless a root `Makefile` or compose target says otherwise.
- Tests are required for new backend and frontend behaviour. No linter config exists yet; Phase 1 adds ruff, mypy, prettier/eslint via pre-commit.
- Environment: docker 28, node 20 / npm 11, gh authenticated as JPForman, git on `main`.
