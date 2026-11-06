# 0002: TimescaleDB (Postgres) for telemetry storage

- Status: accepted
- Date: 2026-11-05

## Context
Machines emit high-rate time-stamped readings. We need fast appends, time-range
queries, and retention/compression, while keeping plain SQL and relational data
(users, assets, batches) in the same database.

## Decision
Use Postgres with the TimescaleDB extension, run as a container in development and CI.
Readings will be a hypertable created by a hand-written Alembic migration.

## Alternatives
- Plain Postgres: simplest, but manual partitioning and no built-in compression/retention.
- Neon (serverless Postgres): easy hosting, but no TimescaleDB, scale-to-zero cold starts
  suit ingest poorly, and dev/CI would need network and secrets.
- InfluxDB or another dedicated TSDB: strong for metrics, but a second query language
  and no relational joins to batches/assets.

## Consequences
- Hypertables, compression and retention policies are available.
- Extra DDL (`create_hypertable`) must be hand-written in migrations.
- Hosting is limited to Timescale-capable Postgres (self-hosted, Timescale Cloud).
