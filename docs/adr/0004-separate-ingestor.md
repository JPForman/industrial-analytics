# 0004: A separate ingestor process owns the MQTT-to-database path

- Status: accepted
- Date: 2026-11-07

## Context
Telemetry arrives continuously over MQTT. Something must decode Sparkplug B, keep per-device
alias/sequence state, write readings in bulk, and evaluate alarms. The API also serves users.

## Decision
Run a dedicated `apps/ingestor` service with one MQTT subscription. It shares the SQLAlchemy models
with the API (imported from `app.models`; `app.base` keeps them free of API settings), writes in
buffered bulk inserts, evaluates alarm rules, and republishes normalized JSON (`ia/v1/live/{tag_id}`,
`ia/v1/alarms`) for the API's WebSocket feed. Its core (Sparkplug state, alarm transitions) is pure
code; MQTT and DB I/O sit in a thin shell.

## Alternatives
- Consume MQTT inside the API: one fewer service, but every API replica would ingest (duplicates or
  need leader election), API deploys would pause ingest, and request latency competes with writes.
- Devices POST to the API: loses MQTT's last-will/offline semantics and broker decoupling.
- A stream platform (Kafka) between broker and DB: better replay and fan-out at large scale, but
  heavy for one site; a reasonable future step if multiple consumers need the raw stream.

## Consequences
- Ingest keeps running when the API is redeployed or slow; each scales independently.
- Exactly one writer: no duplicate ingestion, simple alarm state (one process owns it).
  Running two ingestors would need MQTT shared subscriptions plus partitioned alarm ownership.
- The buffer is bounded (drops oldest on overflow) and retried with backoff, so a DB outage
  degrades to data loss of the oldest rows, not a crash. Shutdown drains the buffer.
- Coupling: the ingestor depends on the API package's models. Schema changes go through the
  API's Alembic migrations; both CI workflows run when `apps/api/app/**` changes.
