# 0001: Monorepo layout

- Status: accepted
- Date: 2026-11-05

## Context
The system has an API, an MQTT ingestor, a simulator and a web UI that share
contracts (REST schemas, Sparkplug metric names, alarm definitions).

## Decision
Keep all services in one repository under `apps/`, with shared deploy config in `deploy/`.

## Alternatives
Polyrepo (one repo per service): independent release cadence, but contract changes
need coordinated PRs and CI across repos.

## Consequences
- A single PR can change an API contract and its consumers atomically.
- CI must use path filters so unrelated changes do not rebuild everything.
- Repo grows larger; mitigated by per-app tooling and caching.
