# Industrial Analytics

Shop-floor telemetry platform: simulated machines publish Sparkplug B over MQTT,
an ingestor stores readings in TimescaleDB and evaluates alarms, a FastAPI service
serves REST + WebSocket, and a React/TypeScript dashboard shows live data.

## Quickstart

Needs Docker (with Compose v2), `make` and `openssl`.

```bash
make up      # build and start everything
```

- Dashboard: http://localhost:8080
- API docs (Swagger): http://localhost:8000/docs

The first `make up` writes a random `JWT_SECRET` to `deploy/.env` (gitignored) and reuses it after that.

A fresh database has no users. Sign up (new accounts are viewers), then promote yourself to engineer to acknowledge alarms:

```bash
curl -X POST localhost:8080/api/auth/signup -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"choose-a-password"}'
docker compose -f deploy/docker-compose.yml exec db \
  psql -U industrial -d industrial -c "update users set role='engineer' where email='you@example.com'"
```

Alarm rules have no API yet, so add one with SQL, e.g. laser1 power above 1500 W:

```bash
docker compose -f deploy/docker-compose.yml exec db psql -U industrial -d industrial -c \
  "insert into alarm_rules (tag_id, operator, threshold, severity, enabled)
   select t.id, 'gt', 1500, 'critical', true from tags t join assets a on a.id = t.asset_id
   where a.name = 'laser1' and t.name = 'power_w'"
```

## Commands

| Command | What it does |
|---|---|
| `make up` | Build and start the whole stack |
| `make down` | Stop everything, keep the data |
| `make ps` | Status and health of each service |
| `make logs` | Follow logs (`make logs s=ingestor` for one service) |
| `make infra` | Start only Postgres + Mosquitto, to run the apps from source |

Running each app from source (venvs, tests, linting) is described in `CLAUDE.md`.
Design decisions are in `docs/adr/`.
