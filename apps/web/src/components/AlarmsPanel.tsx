import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { Alarm, Page } from '../api/types'
import { hasRole, useAuth } from '../auth/AuthContext'

type Filter = 'active' | 'unacknowledged' | 'all'

interface Props {
  /** Bumped by the dashboard on every `alarm` WS event and every reconnect: refetch. */
  refreshKey: number
}

const SEVERITY_ICON = { info: 'ℹ', warning: '▲', critical: '⬣' } as const

export function AlarmsPanel({ refreshKey }: Props) {
  const { request, session } = useAuth()
  const canAck = hasRole(session?.user, 'engineer')
  const [filter, setFilter] = useState<Filter>('active')
  const [alarms, setAlarms] = useState<Alarm[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // The WS event only says "something changed"; the REST list is the source of truth. That keeps
  // one code path for render and avoids patching local state from partial event payloads.
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const page = await request<Page<Alarm>>(`/alarms?state=${filter}&limit=50`, { signal })
        setAlarms(page.items)
        setError(null)
      } catch (err) {
        if (!signal?.aborted) setError(String(err))
      }
    },
    [request, filter],
  )

  useEffect(() => {
    const ctrl = new AbortController()
    void load(ctrl.signal)
    return () => ctrl.abort()
  }, [load, refreshKey])

  async function acknowledge(id: number) {
    try {
      await request<Alarm>(`/alarms/${id}/acknowledge`, { method: 'POST' })
    } catch (err) {
      // 409 = someone else acked first. Not an error for the operator: the refetch shows it.
      if (!(err instanceof ApiError && err.status === 409)) setError(String(err))
    }
    await load()
  }

  return (
    <section aria-label="Alarms" className="alarms">
      <div className="row between">
        <h2>Alarms</h2>
        <select aria-label="Alarm filter" value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          <option value="active">Active</option>
          <option value="unacknowledged">Unacknowledged</option>
          <option value="all">All</option>
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      {alarms === null ? (
        <p className="muted">Loading…</p>
      ) : alarms.length === 0 ? (
        <p className="muted">No {filter === 'all' ? '' : filter} alarms.</p>
      ) : (
        <ul className="alarm-list">
          {alarms.map((a) => (
            <li key={a.id} className={`alarm sev-${a.severity}`}>
              <div className="row between">
                <span className="sev-badge">
                  <span aria-hidden="true">{SEVERITY_ICON[a.severity]}</span> {a.severity}
                </span>
                <span className="muted small">{a.cleared_at ? 'cleared' : 'active'}</span>
              </div>
              <div>
                <strong>{a.asset_name}</strong> {a.tag_name} = {a.value.toFixed(1)} {a.unit}
                <span className="muted">
                  {' '}
                  ({a.operator === 'gt' ? '>' : '<'} {a.threshold} {a.unit})
                </span>
              </div>
              <div className="row between">
                <span className="muted small">{new Date(a.triggered_at).toLocaleTimeString()}</span>
                {a.acknowledged_at ? (
                  <span className="muted small">acknowledged</span>
                ) : canAck ? (
                  <button type="button" className="small-btn" onClick={() => void acknowledge(a.id)}>
                    Acknowledge
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
