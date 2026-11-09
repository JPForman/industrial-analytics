# 0006: React dashboard: same-origin proxy, in-memory token, REST as the source of truth

- Status: accepted
- Date: 2026-11-08

## Context
Operators need a browser dashboard with login, an asset list, live charts per tag, history, and
an alarms panel with acknowledge (engineer+). The live feed is best-effort (ADR 0005): events can
be dropped for slow clients and are lost while disconnected. The API has no CORS configuration.

## Decision
- **Stack:** React 19 + TypeScript (strict) on Vite, Vitest + Testing Library, Recharts. Lives in
  `apps/web`, with its own CI workflow (`web-ci.yml`: lint, typecheck, test, build).
- **Same origin, no CORS:** the app calls `/api/*` and `/ws/live`. In dev the Vite server proxies
  them to FastAPI (`/api` prefix stripped). In production a reverse proxy (nginx) does the same, so
  the browser only ever sees one origin.
- **Token in memory:** the JWT is kept in React state only, never in localStorage. A refresh means
  logging in again.
- **One WebSocket per page,** opened by `useLiveFeed`. It reconnects with exponential backoff and
  full jitter (capped at 30 s), and calls `onOpen` on every (re)connect.
- **REST is the source of truth:** on every (re)connect the dashboard backfills the last 5 minutes
  of raw readings per tag and refetches the alarm list. Backfill and live points are merged by
  timestamp (`mergePoints`), so their arrival order doesn't matter. An `alarm` event is used only
  as a signal to refetch `GET /alarms`; the UI never patches state from the event payload.
- **History** uses the aggregate endpoint (1h → 1 m buckets, 24h → 15 m buckets) and draws the
  min–max band behind the average, so short spikes stay visible.
- **RBAC in the UI is cosmetic:** `hasRole` hides the Acknowledge button for viewers; the API's
  `require_role` is the real enforcement. A 409 on acknowledge (someone else got there first) just
  refetches.

## Alternatives
- **CORS in FastAPI** instead of a proxy: works, but adds a config surface (allowed origins per
  environment) and preflight requests; the proxy matches how production is served anyway.
- **localStorage token:** survives refresh, but any XSS can read it. The production answer is a
  short-lived in-memory access token plus an httpOnly, SameSite refresh cookie.
- **React Query / TanStack Query** for server state (caching, retries, refetch on focus): the
  right choice as screens grow; skipped here to keep the dependency surface small and explainable.
- **Applying alarm events directly to local state:** fewer requests, but the event lacks fields
  the list needs and a missed event would leave the panel wrong until reload.
- **Generated API types** (openapi-typescript from `/openapi.json`): better than the hand-written
  `src/api/types.ts` once the API grows; a CI check could fail on drift.
- **A router (React Router):** not needed for one screen. Add it when there are deep-linkable
  pages (asset detail, run history).

## Consequences
- Reloading the page logs the user out (accepted for now).
- With no asset selected the socket subscribes to every tag (the API treats no `tag_id` as all)
  and the client ignores readings it isn't showing. Fine at this scale; an explicit
  "alarms only" option in the API would remove the waste.
- Each reconnect costs one readings query per visible tag plus one alarms query: cheap, and
  jittered backoff spreads the load after an API restart.
- The production bundle is ~550 kB, mostly Recharts; code-splitting the charts is an easy win.
