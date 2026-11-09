# Interview talking points

Notes for talking about this project in an interview. Each answer is short enough to say out loud;
the ADRs in `docs/adr/` have the full reasoning.

## 1. The 60-second pitch

> I built a shop-floor telemetry platform end to end. Simulated machines publish Sparkplug B over
> MQTT, the way real edge gateways do. A separate ingestor service decodes it, auto-registers
> machines from their birth messages, writes readings to TimescaleDB in bulk, and evaluates alarm
> rules. A FastAPI service serves REST and a WebSocket live feed, and a React and TypeScript
> dashboard shows live charts, history and alarms, with role-based access. Everything is
> containerized, starts with one command, and CI tests each app on its own plus the whole stack
> end to end. I wrote an ADR for each major decision, so I can explain what I chose, what I
> rejected, and when I'd change my mind.

If they want one highlight: **the database is the source of truth and everything else is
allowed to be lossy.** The live feed can drop data for a slow client, the ingestor's buffer can
drop its oldest rows if the DB is down for hours, and the dashboard repairs gaps by backfilling
from REST on every reconnect.

## 2. Demo script (about 5 minutes)

1. `make up`, then `make ps`: point out the health-gated order (db → migrate → api → web).
2. Open http://localhost:8080, log in. The **● Live** badge shows the WebSocket is connected.
3. Click **laser1**. The chart is full immediately: that's the REST backfill, then live points append.
4. Watch for a power spike over 1500 W. An alarm appears in the panel (edge-triggered: one event
   per crossing, not one per reading). Click **Acknowledge** as an engineer. A viewer doesn't see the
   button, and the API returns 403 if they try anyway.
5. Switch to **1h**: the average line is flat, but the min–max band shows every spike. That's why
   the aggregate endpoint returns min and max, not just the average.
6. **Resilience:** `docker compose -f deploy/docker-compose.yml restart api`. The badge goes to
   "Reconnecting…", comes back on its own, and the chart has no hole (backfill on reconnect).
7. `docker compose -f deploy/docker-compose.yml restart ingestor`. The ingestor logs `flushed
   buffer; stopping` on the way down, requests a rebirth on the way up, and data resumes.
8. Show http://localhost:8000/docs (Swagger) and one ADR.

## 3. Decisions and trade-offs

| Decision | Why | Main alternative | When I'd switch |
|---|---|---|---|
| **Sparkplug B on MQTT** (ADR 0003) | Standard topics, typed metrics, birth/death state, aliases to keep payloads small, auto-discovery of devices | Plain MQTT + JSON: readable, but every vendor needs custom parsing and there's no offline detection | Plain MQTT for a single in-house device type |
| **Separate ingestor** (ADR 0004) | One writer: no duplicate ingestion and one owner of alarm state; API deploys don't pause ingest; each scales independently | Consume MQTT inside the API: every replica would ingest the same data | If ingest were tiny and there was only ever one API instance |
| **TimescaleDB** (ADR 0002) | Time-series performance (chunks, compression, `time_bucket`) and relational joins in one SQL database | InfluxDB: strong for metrics, but a second query language and no joins to assets or batches | Very high cardinality or metrics-only workloads |
| **WebSocket + per-client bounded queues** (ADR 0005) | Push in about a second; a slow client can only lose its own oldest events | SSE: simpler and one-way, also defensible. Polling: latency and DB load grow with clients | SSE if it stays strictly server-to-client |
| **REST as source of truth in the UI** (ADR 0006) | A missed live event can never leave the screen wrong; the UI refetches on reconnect and on alarm events | Patch UI state from event payloads: fewer requests, but drifts when events are missed | Never fully; I'd add caching (React Query) instead |
| **Same-origin proxy** (ADR 0006/0007) | Vite in dev and nginx in prod proxy `/api` and `/ws`, so there's no CORS at all | CORS in FastAPI: works, but needs an allowed-origins list per environment and preflight requests | A public API used by other origins |
| **Migrations as a one-shot job** (ADR 0007) | Runs once per deploy before the apps start; replicas never race; a failed migration doesn't crash-loop the API | Migrate on API startup | Never with more than one replica |
| **Monorepo** (ADR 0001) | Shared models and the Sparkplug library change together in one PR; path-filtered CI keeps it fast | Polyrepo with published packages | Separate teams with separate release cycles |

## 4. Failure modes: "what happens when…"

| Failure | What happens | Why |
|---|---|---|
| **Broker restarts** | Edge, ingestor and API bridge all reconnect with backoff. The edge bumps `bdSeq` and re-births | Each MQTT client has a reconnect loop; Sparkplug birth/death sequencing handles the rest |
| **Ingestor sees a `seq` gap** | It sends `NCMD Node Control/Rebirth` (rate-limited to one per 5 s per node) and rebuilds its alias map | Aliases could have changed; rebirth makes state trustworthy again |
| **Database down** | Ingest keeps buffering, up to 50,000 rows (about 2 hours for 7 tags at 1 Hz), then drops the oldest. Flushes retry with exponential backoff up to 30 s. REST returns errors, `/ready` fails | Bounded memory beats an out-of-memory crash; dropped rows are lost (not in the DB) |
| **Flush fails halfway** | The DB rolls back, and the in-memory alarm state is rolled back too (snapshot) | Otherwise the retry would see "alarm already open" and silently skip writing the alarm |
| **Same data arrives twice** | Ignored | `ON CONFLICT DO NOTHING` on the `(tag_id, ts)` primary key: ingest is idempotent |
| **A browser stops reading** | Its own queue fills and drops its oldest events. Nobody else is affected | `publish` uses `put_nowait` and never awaits a client |
| **API restarts** | Dashboards reconnect with jittered backoff and backfill the gap over REST | The broadcaster keeps no history; the DB does |
| **Two operators acknowledge at once** | Exactly one wins; the other gets 409 and the UI just refreshes | A single atomic `UPDATE … WHERE acknowledged_at IS NULL` |
| **Edge node loses power** | The broker publishes its Last Will (`NDEATH`); a stale death from an old session is ignored | `bdSeq` ties each death to the session it belongs to |
| **Shutdown (deploy)** | The ingestor drains its buffer on SIGTERM; uvicorn finishes in-flight requests | Exec-form `CMD` makes the app PID 1 so it receives the signal |

## 5. Security

- **Authentication vs authorization:** JWT (HS256) proves *who you are* (401 if missing or invalid).
  Roles (viewer < engineer < admin) decide *what you can do* (403). `require_role` on the API is
  the enforcement; hiding buttons in the UI is only convenience.
- **Login** returns the same 401 for an unknown email and a wrong password, so attackers can't use
  the error to find which emails exist. Passwords are hashed with bcrypt (8–72 characters: bcrypt's
  limit).
- **Responses never include the password hash:** endpoints return Pydantic `*Out` models, never ORM
  objects.
- **WebSocket token:** browsers can't set headers on a WebSocket, so the JWT goes in the query
  string. Risk: URLs end up in logs. Mitigations here: nginx logs `/ws/` without the query, and a
  logging filter redacts `token=` in the API logs. The proper fix is a **one-time ticket**
  (`POST /ws/ticket` with the normal Bearer header returns a random, single-use ticket valid for
  about 30 s).
- **Token storage in the browser:** memory only, never localStorage (XSS could read it). The
  production answer is a short-lived access token plus an httpOnly, SameSite refresh cookie.
- **Secrets:** never in git or images (`.dockerignore` excludes `.env`). `JWT_SECRET` is required;
  the app refuses to start without it.
- **Not done yet:** MQTT has anonymous access on 1883 (dev only). Production: TLS on 8883,
  per-client credentials and topic ACLs. Also rate limiting on login.

## 6. Testing and CI

- **Pure core, thin I/O shell:** the Sparkplug state machine, alarm transitions and message building
  are plain functions with fast unit tests. MQTT and DB code is a thin layer around them.
- **Real databases where it matters:** API tests default to SQLite for speed, but CI runs them
  against a real TimescaleDB service container, because SQLite doesn't enforce foreign keys or
  support `time_bucket`.
- **Migrations are tested:** upgrade → downgrade → upgrade in CI.
- **Frontend tests fake only the network** (`fetch` and `WebSocket`); components, auth and the API
  client are real code.
- **End-to-end smoke test** builds every image and checks that data actually flows from the
  simulator to the browser-facing proxy. It catches Dockerfile, compose and nginx mistakes that
  unit tests can't.
- **Strict typing:** mypy strict on Python, TypeScript strict on the frontend.

## 7. Scaling: what changes at 10× and 100×

- **More machines:** MQTT shared subscriptions (`$share/ingest/spBv1.0/#`) let several ingestors split
  the load. Alarm ownership then has to be partitioned (for example by edge node) so two
  ingestors never own the same rule.
- **Several consumers of the raw stream** (ML, a data lake, other plants): put Kafka between the
  broker and the consumers for replay and independent read positions.
- **More dashboards:** API replicas behind a load balancer. Each replica runs its own MQTT bridge,
  and the broker fans out to all of them, so no Redis is needed for the live feed.
- **Long history:** TimescaleDB **continuous aggregates** (pre-computed rollups), retention policies
  to drop raw data after N days, and compression (already on after 7 days, segmented by tag).
- **Deployment:** the same images on Kubernetes: Deployments for api, web and ingestor, a Job (or
  init container) for migrations, readiness probes on `/ready`, liveness on `/health`, secrets
  from a secret manager.
- **Reproducible builds:** lock Python dependencies (`uv lock`) the way `package-lock.json` already
  locks the frontend.

## 8. Concept glossary (short answers)

- **MQTT vs Sparkplug B vs Mosquitto:** MQTT is the publish/subscribe transport protocol. Sparkplug B
  is a specification *on top of* MQTT: topic layout, protobuf payloads, birth/death state.
  Mosquitto is a broker, the server MQTT clients connect to.
- **OPC UA vs MQTT:** OPC UA is a rich, typed information model, usually client/server, strong at
  the PLC/controls layer. MQTT is lightweight pub/sub, good for sending data up to IT systems. A
  common pattern is an edge gateway that *reads* OPC UA from machines and *publishes* Sparkplug B
  upstream.
- **Unified Namespace (UNS):** one shared, hierarchical topic space (site/area/line/machine) on a
  broker that every system publishes to and reads from, instead of point-to-point integrations.
  Sparkplug is one common way to build it.
- **Assets and tags:** an asset is a machine. A tag is one measured signal on it (`power_w`,
  `head_temp_c`). Readings are `(tag, timestamp, value)` rows.
- **QoS 0/1/2:** at most once, at least once, exactly once. Telemetry uses 0 (the next reading
  replaces a lost one); commands like rebirth use 1.
- **WebSocket vs SSE vs polling:** WebSocket is two-way and long-lived. SSE is one-way server push
  over plain HTTP with built-in reconnect. Polling is simple but adds latency and load per client.
- **Hypertable:** a TimescaleDB table automatically partitioned into time chunks, so queries over a
  time range only touch the chunks in that range.
- **Keyset pagination:** `WHERE ts > :last_seen ORDER BY ts LIMIT n`. Page 1000 costs the same as
  page 1, unlike `OFFSET`, which scans and discards rows.
- **Idempotent:** doing it twice has the same effect as once (our ingest, thanks to `ON CONFLICT`).
- **Alembic:** versioned database migrations for SQLAlchemy. Autogenerate drafts them; you review
  them, especially for TimescaleDB DDL, which it can't see.
- **asyncpg / async SQLAlchemy:** a non-blocking Postgres driver, so one process can serve many
  requests while waiting on the DB. Gotcha: no lazy loading, so related data is loaded explicitly.
- **mypy vs Pydantic vs ruff:** mypy checks types *before* running (static). Pydantic validates data
  *at runtime* (requests, settings). ruff is a linter and formatter for style and bug patterns.
- **Docker image vs container vs volume:** an image is the read-only template, a container is a
  running instance of it, and a volume is storage that outlives containers (our database files).
- **Container vs VM:** containers share the host's kernel and start in milliseconds; a VM runs its
  own whole OS. Containers isolate less, but are much lighter.
- **Multi-stage build:** compile in a big image, copy only the result into a small runtime image.
- **Layer caching:** order Dockerfile steps from least to most frequently changing (dependencies
  before source).
- **Liveness vs readiness:** liveness asks "is the process alive?" (restart it if not). Readiness asks
  "can it serve right now?" (stop sending traffic if not). `/health` and `/ready` here.
- **Kubernetes:** runs containers across many machines: restarts failed ones, scales replicas,
  rolls out new versions gradually, routes traffic through Services.
- **CI service containers:** CI starts a throwaway Postgres next to the test job. Nothing is hosted;
  it disappears when the job ends.
- **Edge + cloud hybrid:** keep collection and safety-critical logic (alarms) near the machines,
  where they keep working if the internet link drops, and send data to a central or cloud system
  for history and analytics across sites.

## 9. Study sheet: the answers to get exactly right

1. **Why snapshot alarm state around a flush?** If the commit fails, the DB rolls back but memory
   would still say "alarm open". On retry the edge-triggered check sees no change and the alarm
   event is **never written**. So copy the state before the transaction and restore it on failure.
2. **Why is the WS token in the query string, and what's the fix?** Browsers can't set headers on a
   WebSocket. The risk is that URLs are logged. The fix is a one-time, short-lived ticket.
3. **How is a slow WebSocket client isolated?** Each client has its own bounded queue, and `publish`
   uses `put_nowait`, dropping that client's oldest event when full. `await queue.put` would block
   the bridge and every other client.
4. **Why close the DB session in the WS handler?** A socket can stay open for hours; holding a pooled
   connection that long would exhaust the pool and starve REST.
5. **What happens when the WebSocket reconnects?** `onOpen` fires, the dashboard backfills the last
   5 minutes over REST, and `mergePoints` dedupes by timestamp. The server can't replay because the
   broadcaster keeps no history; only the DB has it.
6. **Why does an alarm event trigger a refetch instead of an insert?** The event lacks the joined
   fields (asset name, tag name, threshold), and a missed event would leave the panel wrong. The
   event is a signal; REST is the data.
7. **A viewer un-hides the Acknowledge button. Then what?** The API returns **403** (authorization)
   from `require_role(Role.engineer)`. 401 would mean "not authenticated".
8. **Why a separate migrate job?** Replicas would race to migrate, and a failed migration would
   crash-loop the API. It runs once per deploy, before the apps; with nothing to apply it's a no-op.
9. **Why install dependencies before copying the code?** Layer caching: a code change then rebuilds
   only the last cheap layer instead of reinstalling every package.
10. **Why `service_healthy` instead of plain `depends_on`?** Started is not ready. Postgres needs a
    few seconds after the container starts; the healthcheck waits for `pg_isready`.
11. **What's lost when the ingestor's buffer overflows?** The oldest rows. They never reach the DB.
    That's the deliberate trade: bounded memory over a crash.
12. **Why rebirth on a `seq` gap?** A lost message might have been a birth that changed aliases, so
    the consumer can't trust its alias map until the edge node re-sends its births.

## 10. Honest limitations (say them before they're found)

- No alarm-rule API or UI yet; rules are inserted with SQL.
- No admin endpoint for roles; promotion is SQL.
- Python dependencies aren't locked; builds resolve `>=` ranges.
- Logging is plain text; no metrics or tracing yet (next: structured JSON logs, Prometheus metrics
  for buffer size, dropped rows, flush latency, connected clients).
- A WebSocket stays open after its token expires (checked only at connect).
- MQTT is anonymous and unencrypted in dev.
- One ingestor instance: fine for one site, needs shared subscriptions plus alarm partitioning to
  scale out.

## 11. Questions to ask them

- What protocols do your partners' machines speak today: OPC UA, MQTT/Sparkplug, vendor APIs?
  Is there a Unified Namespace effort?
- Where does data processing run: on site, in the cloud, or both?
- How are deployments done today (on-prem servers, Kubernetes, a cloud provider)?
- How do projects move from a research demo to something a manufacturer runs in production?
- What does the team's code review and CI process look like?
