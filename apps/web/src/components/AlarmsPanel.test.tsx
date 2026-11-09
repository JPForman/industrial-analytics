import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, type ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { Alarm, User } from '../api/types'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import { ENGINEER, VIEWER, fakeApi } from '../test/fakeApi'
import { AlarmsPanel } from './AlarmsPanel'

const alarm: Alarm = {
  id: 7,
  rule_id: 1,
  tag_id: 2,
  tag_name: 'power_w',
  unit: 'W',
  asset_id: 5,
  asset_name: 'laser1',
  operator: 'gt',
  threshold: 1500,
  severity: 'critical',
  value: 1594.4,
  triggered_at: '2026-11-08T12:00:00Z',
  cleared_at: null,
  acknowledged_at: null,
  acknowledged_by_id: null,
}

/** Log in through the real AuthProvider (against the fake API) before rendering children. */
function LoggedIn({ children }: { children: ReactNode }) {
  const { session, login } = useAuth()
  useEffect(() => {
    void login('x@example.com', 'password')
  }, [login])
  return session ? children : null
}

function renderAs(user: User, routes: Parameters<typeof fakeApi>[0]) {
  const api = fakeApi({
    'POST /auth/login': () => ({ body: { access_token: 't' } }),
    'GET /auth/me': () => ({ body: user }),
    ...routes,
  })
  render(
    <AuthProvider>
      <LoggedIn>
        <AlarmsPanel refreshKey={0} />
      </LoggedIn>
    </AuthProvider>,
  )
  return api
}

const page = (items: Alarm[]) => ({ body: { items, total: items.length, limit: 50, offset: 0 } })

describe('AlarmsPanel', () => {
  it('hides Acknowledge from viewers (the API enforces it too)', async () => {
    renderAs(VIEWER, { 'GET /alarms': () => page([alarm]) })
    expect(await screen.findByText('laser1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
  })

  it('lets an engineer acknowledge, then refetches the list', async () => {
    let acked = false
    const { calls } = renderAs(ENGINEER, {
      'GET /alarms': () => page([{ ...alarm, acknowledged_at: acked ? '2026-11-08T12:01:00Z' : null }]),
      'POST /alarms/7/acknowledge': () => {
        acked = true
        return { body: { ...alarm, acknowledged_at: '2026-11-08T12:01:00Z' } }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Acknowledge' }))
    expect(await screen.findByText('acknowledged')).toBeInTheDocument()
    expect(calls.filter((c) => c === 'GET /alarms')).toHaveLength(2)
  })

  it('treats 409 (someone else acked first) as a refresh, not an error', async () => {
    let acked = false
    renderAs(ENGINEER, {
      'GET /alarms': () => page([{ ...alarm, acknowledged_at: acked ? '2026-11-08T12:01:00Z' : null }]),
      'POST /alarms/7/acknowledge': () => {
        acked = true
        return { status: 409, body: { detail: 'Alarm already acknowledged' } }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Acknowledge' }))
    await waitFor(() => expect(screen.getByText('acknowledged')).toBeInTheDocument())
    expect(screen.queryByText(/409|already/)).not.toBeInTheDocument()
  })

  it('passes the filter to the API', async () => {
    const { fetchMock } = renderAs(ENGINEER, { 'GET /alarms': () => page([]) })
    await userEvent.selectOptions(await screen.findByLabelText('Alarm filter'), 'unacknowledged')
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('state=unacknowledged'))).toBe(true),
    )
  })
})
