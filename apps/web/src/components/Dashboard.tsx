import { useCallback, useEffect, useRef, useState } from 'react'
import { qs } from '../api/client'
import type { Asset, LiveEvent, ReadingsPage, Tag } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { mergePoints, toPoint, type Point } from '../live/series'
import { useLiveFeed, type FeedStatus } from '../live/useLiveFeed'
import { AlarmsPanel } from './AlarmsPanel'
import { AssetList } from './AssetList'
import { TagChart, type Range } from './TagChart'

export const LIVE_WINDOW_MS = 5 * 60_000

type Series = Record<number, Point[]>

export function Dashboard() {
  const { session, logout, request } = useAuth()
  const [asset, setAsset] = useState<Asset | null>(null)
  const [tags, setTags] = useState<Tag[]>([])
  const [series, setSeries] = useState<Series>({})
  const [range, setRange] = useState<Range>('live')
  const [alarmRefresh, setAlarmRefresh] = useState(0)

  // Load the selected asset's tags; reset the live series so charts don't mix assets.
  useEffect(() => {
    if (!asset) return
    const ctrl = new AbortController()
    setSeries({})
    request<Tag[]>(`/assets/${asset.id}/tags`, { signal: ctrl.signal })
      .then(setTags)
      .catch(() => {
        if (!ctrl.signal.aborted) setTags([])
      })
    return () => ctrl.abort()
  }, [asset, request])

  // Backfill the live window over REST. Called on every WS (re)connect, because the live feed is
  // best-effort: readings published while we were disconnected exist only in the database.
  const tagsRef = useRef(tags)
  useEffect(() => {
    tagsRef.current = tags
  }, [tags])
  const backfill = useCallback(async () => {
    const end = new Date()
    const start = new Date(end.getTime() - LIVE_WINDOW_MS)
    await Promise.all(
      tagsRef.current.map(async (tag) => {
        const page = await request<ReadingsPage>(
          `/tags/${tag.id}/readings${qs({ start: start.toISOString(), end: end.toISOString(), limit: 1000 })}`,
        )
        const points = page.items.map((r) => toPoint(r.ts, r.value))
        setSeries((s) => ({ ...s, [tag.id]: mergePoints(s[tag.id] ?? [], points, start.getTime()) }))
      }),
    ).catch(() => undefined) // a failed backfill leaves a gap; the live feed still fills forward
  }, [request])

  const onEvent = useCallback((event: LiveEvent) => {
    if (event.type === 'alarm') {
      setAlarmRefresh((n) => n + 1)
      return
    }
    const point = toPoint(event.ts, event.value)
    setSeries((s) => {
      if (!(event.tag_id in s) && !tagsRef.current.some((t) => t.id === event.tag_id)) return s
      return { ...s, [event.tag_id]: mergePoints(s[event.tag_id] ?? [], [point], point.t - LIVE_WINDOW_MS) }
    })
  }, [])

  const onOpen = useCallback(() => {
    void backfill()
    setAlarmRefresh((n) => n + 1) // alarm events may also have been missed while disconnected
  }, [backfill])

  // One socket for the page. With no asset selected the API sends every tag (no tag_id = all);
  // onEvent ignores readings for tags we aren't showing.
  const status = useLiveFeed({ token: session?.token ?? null, tagIds: tags.map((t) => t.id), onEvent, onOpen })

  return (
    <div className="app">
      <header className="topbar">
        <strong>Shop-floor telemetry</strong>
        <FeedBadge status={status} />
        <span className="spacer" />
        <span className="muted small">
          {session?.user.email} · {session?.user.role}
        </span>
        <button type="button" className="small-btn" onClick={logout}>
          Sign out
        </button>
      </header>
      <aside className="sidebar">
        <AssetList selectedId={asset?.id ?? null} onSelect={setAsset} />
      </aside>
      <main className="main">
        {!asset ? (
          <p className="muted">Select an asset to see its tags.</p>
        ) : (
          <>
            <div className="row between">
              <h2>
                {asset.name} <span className="muted small">{asset.asset_type}</span>
              </h2>
              <div role="group" aria-label="Time range" className="segmented">
                {(['live', '1h', '24h'] as const).map((r) => (
                  <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>
                    {r === 'live' ? 'Live 5 min' : r}
                  </button>
                ))}
              </div>
            </div>
            <div className="charts">
              {tags.map((tag) => (
                <TagChart key={tag.id} tag={tag} range={range} livePoints={series[tag.id] ?? []} windowMs={LIVE_WINDOW_MS} />
              ))}
            </div>
          </>
        )}
      </main>
      <aside className="alarms-col">
        <AlarmsPanel refreshKey={alarmRefresh} />
      </aside>
    </div>
  )
}

function FeedBadge({ status }: { status: FeedStatus }) {
  const label = { open: 'Live', connecting: 'Connecting…', reconnecting: 'Reconnecting…' }[status]
  return (
    <span className={`feed feed-${status}`} role="status">
      <span aria-hidden="true">{status === 'open' ? '●' : '○'}</span> {label}
    </span>
  )
}
