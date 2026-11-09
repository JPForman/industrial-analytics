import { useEffect, useState } from 'react'
import type { Asset, Page } from '../api/types'
import { useAuth } from '../auth/AuthContext'

interface Props {
  selectedId: number | null
  onSelect: (asset: Asset) => void
}

export function AssetList({ selectedId, onSelect }: Props) {
  const { request } = useAuth()
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // AbortController: if the component unmounts mid-request, don't set state afterwards.
    const ctrl = new AbortController()
    request<Page<Asset>>('/assets?limit=200', { signal: ctrl.signal })
      .then((page) => setAssets(page.items))
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted) setError(String(err))
      })
    return () => ctrl.abort()
  }, [request])

  if (error) return <p className="error">Could not load assets: {error}</p>
  if (!assets) return <p className="muted">Loading assets…</p>
  if (assets.length === 0) return <p className="muted">No assets yet. Start the simulator and ingestor.</p>

  return (
    <nav aria-label="Assets">
      <h2>Assets</h2>
      <ul className="asset-list">
        {assets.map((a) => (
          <li key={a.id}>
            <button
              type="button"
              className={a.id === selectedId ? 'asset selected' : 'asset'}
              aria-current={a.id === selectedId ? 'true' : undefined}
              onClick={() => onSelect(a)}
            >
              <span className="asset-name">{a.name}</span>
              <span className="muted small">
                {a.asset_type} · {a.site} · {a.edge_node_id}/{a.device_id}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
