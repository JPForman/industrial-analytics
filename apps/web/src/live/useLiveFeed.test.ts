import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { backoffMs, liveUrl, MAX_BACKOFF_MS, useLiveFeed } from './useLiveFeed'

/** Minimal controllable WebSocket: tests drive open/message/close by hand. */
class FakeSocket {
  static instances: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  closed = false
  url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }
  close() {
    this.closed = true
  }
}

beforeEach(() => {
  FakeSocket.instances = []
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

describe('backoffMs', () => {
  it('grows exponentially, is capped, and never hits zero', () => {
    expect(backoffMs(0, () => 0.999)).toBe(999)
    expect(backoffMs(3, () => 0.999)).toBe(7992)
    expect(backoffMs(20, () => 0.999)).toBeLessThanOrEqual(MAX_BACKOFF_MS)
    expect(backoffMs(5, () => 0)).toBe(250)
  })
})

describe('liveUrl', () => {
  it('uses wss on https and repeats tag_id', () => {
    const loc = { protocol: 'https:', host: 'plant.example.com' } as Location
    expect(liveUrl('abc', [1, 2], loc)).toBe('wss://plant.example.com/ws/live?token=abc&tag_id=1&tag_id=2')
  })
})

describe('useLiveFeed', () => {
  it('delivers events, and on reconnect calls onOpen again so the caller can backfill', () => {
    const onEvent = vi.fn()
    const onOpen = vi.fn()
    const { result } = renderHook(() => useLiveFeed({ token: 't', tagIds: [2], onEvent, onOpen }))
    expect(result.current).toBe('connecting')

    const first = FakeSocket.instances[0]
    expect(first.url).toContain('tag_id=2')
    act(() => first.onopen?.())
    expect(result.current).toBe('open')
    expect(onOpen).toHaveBeenCalledTimes(1)

    act(() => first.onmessage?.({ data: '{"type":"reading","tag_id":2,"ts":"2026-11-08T00:00:00Z","value":1}' }))
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: 'reading', value: 1 }))

    act(() => first.onclose?.()) // e.g. API restarted
    expect(result.current).toBe('reconnecting')
    act(() => vi.advanceTimersByTime(MAX_BACKOFF_MS))
    expect(FakeSocket.instances).toHaveLength(2)

    act(() => FakeSocket.instances[1].onopen?.())
    expect(onOpen).toHaveBeenCalledTimes(2)
  })

  it('reconnects when the tag set changes but not when the same ids are re-sent', () => {
    const { rerender, unmount } = renderHook(({ ids }) => useLiveFeed({ token: 't', tagIds: ids, onEvent: vi.fn() }), {
      initialProps: { ids: [2, 3] },
    })
    rerender({ ids: [3, 2] }) // new array, same set
    expect(FakeSocket.instances).toHaveLength(1)
    rerender({ ids: [4] })
    expect(FakeSocket.instances).toHaveLength(2)
    expect(FakeSocket.instances[0].closed).toBe(true)

    unmount()
    expect(FakeSocket.instances[1].closed).toBe(true)
    act(() => FakeSocket.instances[1].onclose?.())
    act(() => vi.advanceTimersByTime(MAX_BACKOFF_MS))
    expect(FakeSocket.instances).toHaveLength(2) // no reconnect after unmount
  })

  it('does not connect without a token', () => {
    renderHook(() => useLiveFeed({ token: null, tagIds: [], onEvent: vi.fn() }))
    expect(FakeSocket.instances).toHaveLength(0)
  })
})
