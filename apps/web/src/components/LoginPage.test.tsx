import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import { ENGINEER, fakeApi } from '../test/fakeApi'

async function signIn(password: string) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'eng@example.com')
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('login', () => {
  it('shows a generic error on 401 and stays on the login form', async () => {
    fakeApi({ 'POST /auth/login': () => ({ status: 401, body: { detail: 'Invalid credentials' } }) })
    render(<App />)
    await signIn('wrong-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
  })

  it('logs in, loads the user, and sends the Bearer token on later calls', async () => {
    const { fetchMock } = fakeApi({
      'POST /auth/login': () => ({ body: { access_token: 'jwt-123', token_type: 'bearer' } }),
      'GET /auth/me': () => ({ body: ENGINEER }),
      'GET /assets': () => ({ body: { items: [], total: 0, limit: 200, offset: 0 } }),
      'GET /alarms': () => ({ body: { items: [], total: 0, limit: 50, offset: 0 } }),
    })
    vi.stubGlobal('WebSocket', class { close() {} })
    render(<App />)
    await signIn('correct-password')

    expect(await screen.findByText(/eng@example.com · engineer/)).toBeInTheDocument()
    const me = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/auth/me'))
    expect((me?.[1]?.headers as Record<string, string>).Authorization).toBe('Bearer jwt-123')
  })
})
