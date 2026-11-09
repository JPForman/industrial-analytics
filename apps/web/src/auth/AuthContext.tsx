import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { ApiError, apiFetch } from '../api/client'
import type { Role, User } from '../api/types'

interface Session {
  token: string
  user: User
}

interface AuthValue {
  session: Session | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  /** Wraps apiFetch with the token; a 401 (expired/revoked) logs the user out. */
  request: <T>(path: string, init?: { method?: 'GET' | 'POST'; body?: unknown; signal?: AbortSignal }) => Promise<T>
}

const AuthContext = createContext<AuthValue | null>(null)

// The JWT lives only in React state (memory). localStorage would survive a refresh, but any XSS
// could read it. The trade-off is a re-login on refresh; production would add an httpOnly
// refresh-token cookie so the access token can stay short-lived and in memory.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)

  const logout = useCallback(() => setSession(null), [])

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await apiFetch<{ access_token: string }>('/auth/login', {
      method: 'POST',
      body: { email, password },
    })
    const user = await apiFetch<User>('/auth/me', { token: access_token })
    setSession({ token: access_token, user })
  }, [])

  const token = session?.token ?? null
  const request = useCallback(
    async <T,>(path: string, init: { method?: 'GET' | 'POST'; body?: unknown; signal?: AbortSignal } = {}) => {
      try {
        return await apiFetch<T>(path, { ...init, token })
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) setSession(null)
        throw err
      }
    },
    [token],
  )

  const value = useMemo(() => ({ session, login, logout, request }), [session, login, logout, request])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

const RANK: Record<Role, number> = { viewer: 0, engineer: 1, admin: 2 }

/** UI-side mirror of the API's require_role. Only hides controls; the API is what enforces. */
// eslint-disable-next-line react-refresh/only-export-components
export function hasRole(user: User | undefined, min: Role): boolean {
  return user !== undefined && RANK[user.role] >= RANK[min]
}
