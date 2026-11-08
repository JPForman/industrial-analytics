# 0005: WebSocket live feed with an in-process broadcaster

- Status: accepted
- Date: 2026-11-07

## Context
The dashboard needs readings and alarm events pushed within about a second, with no polling. The
ingestor already republishes normalized JSON on MQTT (`ia/v1/live/{tag_id}`, `ia/v1/alarms`,
ADR 0004). Browsers can't speak MQTT over plain TCP, and the broker shouldn't be exposed to them.

## Decision
- The API runs one MQTT bridge per process (`app/mqtt_bridge.py`, started in the FastAPI
  `lifespan`). It subscribes to both topics and hands each message to an in-process `Broadcaster`
  (`app/live.py`).
- `GET /ws/live` is a WebSocket endpoint (`app/routers/live.py`). Clients may filter with repeated
  `tag_id` params. Alarms always go to every client.
- Each client gets a bounded `asyncio.Queue` (1000 events). `publish` never awaits. When a client's
  queue is full, its oldest event is dropped and counted, so a slow client can't stall the others.
- Auth: the JWT goes in `?token=`, because the browser `WebSocket` API can't set an Authorization
  header. A bad token or unknown user is rejected before `accept()` (HTTP 403 on the upgrade).

## Alternatives
- **Server-Sent Events (SSE):** plain HTTP, reconnects on its own, and works through every proxy.
  It's one-way, which is all we need today. We chose WebSocket because the next features (choosing
  tags mid-session, acknowledging alarms live) send data from client to server, and FastAPI and
  Starlette support it well. SSE would also have been a defensible choice.
- **Polling the REST API:** simple, but it adds latency and DB load that grow with the number of
  clients.
- **MQTT over WebSockets from the browser:** no bridge needed, but it exposes the broker, needs
  broker-side ACLs that match our RBAC, and sends raw topics to the UI.
- **A shared pub/sub layer (Redis) between API replicas:** not needed. Each replica runs its own
  bridge and MQTT already fans out to every subscriber, so the broker already plays that role.
- **Disconnecting slow clients instead of dropping:** stricter. It's a better choice if the
  client must see every event. A live chart only cares about the latest values and can backfill
  history over REST.
- **Auth via a cookie or first-message token:** a cookie needs CSRF/origin checks. A token sent as
  the first message keeps it out of URLs, but means accepting the socket before you know who's on
  the other end.

## Consequences
- The feed is best-effort. Readings are QoS 0 end to end and slow clients lose their oldest events.
  The database is the source of truth: on reconnect, the UI refetches history and open alarms over
  REST.
- The token appears in URLs, so it can land in server and proxy access logs (uvicorn logs the
  query string). Mitigations: short token lifetimes, TLS, and redacting the access log. A stronger
  fix is a single-use, short-lived WebSocket ticket from `POST /ws/ticket`.
- A token is checked only at connect time. A socket stays open after its token expires until the
  client disconnects. A fix: close the socket when the token's `exp` passes.
- The DB session used for the auth lookup is closed right away, so long-lived sockets don't pin
  pool connections.
- If the broker is down, the bridge reconnects with backoff. REST keeps working and `/ready` only
  checks the DB.
- `LIVE_BRIDGE_ENABLED=false` runs the API with REST only.
