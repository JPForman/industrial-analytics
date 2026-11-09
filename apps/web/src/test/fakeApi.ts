import { vi } from 'vitest'

type Handler = (init: RequestInit | undefined, url: URL) => { status?: number; body?: unknown }

/**
 * Stub global fetch with a route table keyed by "METHOD /path" (path without the /api prefix).
 * Tests exercise real components and the real apiFetch, faking only the network boundary.
 */
export function fakeApi(routes: Record<string, Handler>) {
  const calls: string[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const key = `${init?.method ?? 'GET'} ${url.pathname.replace(/^\/api/, '')}`
    calls.push(key)
    const handler = routes[key]
    if (!handler) return new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 })
    const { status = 200, body = null } = handler(init, url)
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export const ENGINEER = { id: 1, email: 'eng@example.com', role: 'engineer' as const }
export const VIEWER = { id: 2, email: 'view@example.com', role: 'viewer' as const }
