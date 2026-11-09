/** Pure time-series helpers for the live chart (unit-tested, no React). */

export interface Point {
  t: number // epoch ms
  v: number
}

/**
 * Merge new points into a series: dedupe by timestamp, sort, and drop anything older than
 * `sinceMs`. Backfill (REST) and live (WebSocket) points can overlap or arrive out of order,
 * e.g. a live reading lands before the backfill response does. Keying by timestamp makes the
 * merge order-independent, the same idea as the API's ON CONFLICT DO NOTHING on (tag_id, ts).
 */
export function mergePoints(existing: Point[], incoming: Point[], sinceMs: number): Point[] {
  const byTime = new Map<number, number>()
  for (const p of existing) byTime.set(p.t, p.v)
  for (const p of incoming) byTime.set(p.t, p.v)
  return [...byTime.entries()]
    .filter(([t]) => t >= sinceMs)
    .sort((a, b) => a[0] - b[0])
    .map(([t, v]) => ({ t, v }))
}

export function toPoint(ts: string, value: number): Point {
  return { t: Date.parse(ts), v: value }
}
