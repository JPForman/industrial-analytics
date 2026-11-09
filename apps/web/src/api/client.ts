/** Thin fetch wrapper: same-origin `/api` prefix (proxied to FastAPI), Bearer token, typed errors. */

export const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

interface RequestOptions {
  token?: string | null
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  })
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res))
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** FastAPI errors are `{detail: string}` or, for 422, `{detail: [{msg, ...}]}`. */
async function errorDetail(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const { detail } = body as { detail: unknown }
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join('; ')
    }
  } catch {
    // not JSON; fall through
  }
  return `${res.status} ${res.statusText}`
}

/** Build a query string, repeating keys for arrays (FastAPI's `list[int]` query format). */
export function qs(params: Record<string, string | number | (string | number)[] | undefined>) {
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue
    for (const v of Array.isArray(value) ? value : [value]) sp.append(key, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}
