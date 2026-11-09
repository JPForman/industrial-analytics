import { useEffect, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { qs } from '../api/client'
import type { AggregateBucket, Tag } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import type { Point } from '../live/series'

export type Range = 'live' | '1h' | '24h'

/** History ranges use the aggregate endpoint. Bucket sizes are picked so a chart gets ~60-100
 *  points, well under the API's 2000-bucket cap, and come from its allowlist. */
const HISTORY: Record<Exclude<Range, 'live'>, { ms: number; bucket: string }> = {
  '1h': { ms: 60 * 60_000, bucket: '1m' },
  '24h': { ms: 24 * 60 * 60_000, bucket: '15m' },
}

const timeTick = (t: number) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
const fullTime = (t: unknown) => new Date(Number(t)).toLocaleTimeString()
const axis = { stroke: 'var(--axis)', tick: { fill: 'var(--text-secondary)', fontSize: 11 } }

interface Props {
  tag: Tag
  range: Range
  livePoints: Point[]
  windowMs: number
}

export function TagChart({ tag, range, livePoints, windowMs }: Props) {
  const title = `${tag.name}${tag.unit ? ` (${tag.unit})` : ''}`
  const latest = livePoints.at(-1)
  return (
    <figure className="card chart">
      <figcaption className="row between">
        <span>{title}</span>
        {range === 'live' && latest && (
          <span className="latest">
            {latest.v.toFixed(1)} <span className="muted small">{tag.unit}</span>
          </span>
        )}
      </figcaption>
      {range === 'live' ? <LiveChart points={livePoints} windowMs={windowMs} unit={tag.unit} /> : <HistoryChart tag={tag} range={range} />}
    </figure>
  )
}

function LiveChart({ points, windowMs, unit }: { points: Point[]; windowMs: number; unit: string }) {
  if (points.length === 0) return <p className="muted chart-empty">Waiting for data…</p>
  const end = points[points.length - 1].t
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={[end - windowMs, end]} tickFormatter={timeTick} {...axis} />
        <YAxis domain={['auto', 'auto']} width={48} {...axis} />
        <Tooltip labelFormatter={fullTime} formatter={(v) => [`${Number(v).toFixed(2)} ${unit}`, 'value']} contentStyle={tooltipStyle} />
        {/* Animation off: re-animating on every 1 Hz update makes the line jitter. */}
        <Line dataKey="v" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

interface BandPoint {
  t: number
  avg: number
  band: [number, number]
}

function HistoryChart({ tag, range }: { tag: Tag; range: Exclude<Range, 'live'> }) {
  const { request } = useAuth()
  const [data, setData] = useState<BandPoint[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    const { ms, bucket } = HISTORY[range]
    const end = new Date()
    const start = new Date(end.getTime() - ms)
    setData(null)
    request<AggregateBucket[]>(
      `/tags/${tag.id}/readings/aggregate${qs({ start: start.toISOString(), end: end.toISOString(), bucket })}`,
      { signal: ctrl.signal },
    )
      .then((rows) => setData(rows.map((r) => ({ t: Date.parse(r.bucket), avg: r.avg, band: [r.min, r.max] }))))
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted) setError(String(err))
      })
    return () => ctrl.abort()
  }, [request, tag.id, range])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="muted chart-empty">Loading…</p>
  if (data.length === 0) return <p className="muted chart-empty">No data in this range.</p>
  return (
    <ResponsiveContainer width="100%" height={180}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={timeTick} {...axis} />
        <YAxis domain={['auto', 'auto']} width={48} {...axis} />
        <Tooltip
          labelFormatter={fullTime}
          formatter={(v, name) =>
            Array.isArray(v)
              ? [`${Number(v[0]).toFixed(1)} – ${Number(v[1]).toFixed(1)} ${tag.unit}`, 'min – max']
              : [`${Number(v).toFixed(2)} ${tag.unit}`, String(name)]
          }
          contentStyle={tooltipStyle}
        />
        {/* min/max band shows spikes the average would hide; gaps stay gaps (no connectNulls). */}
        <Area dataKey="band" stroke="none" fill="var(--series-1)" fillOpacity={0.18} isAnimationActive={false} />
        <Line dataKey="avg" name="avg" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

const tooltipStyle = {
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  fontSize: 12,
}
