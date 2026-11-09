import { useEffect, useRef, useState } from 'react'
import type { LiveEvent } from '../api/types'

export type FeedStatus = 'connecting' | 'open' | 'reconnecting'

interface Options {
  token: string | null
  /** Tags to receive readings for. Alarm events always arrive. Empty = alarms only is not
   *  expressible in the API (no tag_id means every tag), so we pass what the screen shows. */
  tagIds: number[]
  onEvent: (event: LiveEvent) => void
  /** Called on every successful (re)connect. The feed is best-effort (ADR 0005): anything
   *  published while we were disconnected is gone, so callers refetch over REST here. */
  onOpen?: () => void
}

export const MAX_BACKOFF_MS = 30_000

/** Exponential backoff with "full jitter", so 50 dashboards don't reconnect in lockstep after an
 *  API restart (thundering herd). */
export function backoffMs(attempt: number, random: () => number = Math.random): number {
  const ceiling = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt)
  return Math.max(250, Math.floor(random() * ceiling))
}

export function liveUrl(token: string, tagIds: number[], loc: Location = window.location): string {
  const scheme = loc.protocol === 'https:' ? 'wss' : 'ws'
  const params = new URLSearchParams({ token })
  for (const id of tagIds) params.append('tag_id', String(id))
  return `${scheme}://${loc.host}/ws/live?${params.toString()}`
}

export function useLiveFeed({ token, tagIds, onEvent, onOpen }: Options): FeedStatus {
  const [status, setStatus] = useState<FeedStatus>('connecting')

  // Callbacks go through refs so a re-render with new closures doesn't tear down the socket.
  const onEventRef = useRef(onEvent)
  const onOpenRef = useRef(onOpen)
  useEffect(() => {
    onEventRef.current = onEvent
    onOpenRef.current = onOpen
  })

  // A stable primitive key: a new array with the same ids must not reconnect.
  const tagKey = [...tagIds].sort((a, b) => a - b).join(',')

  useEffect(() => {
    if (!token) return
    const ids = tagKey ? tagKey.split(',').map(Number) : []
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    let disposed = false

    const connect = () => {
      socket = new WebSocket(liveUrl(token, ids))
      socket.onopen = () => {
        attempt = 0
        setStatus('open')
        onOpenRef.current?.()
      }
      socket.onmessage = (msg: MessageEvent<string>) => {
        try {
          onEventRef.current(JSON.parse(msg.data) as LiveEvent)
        } catch {
          // ignore a malformed frame rather than killing the feed
        }
      }
      socket.onclose = () => {
        if (disposed) return
        setStatus('reconnecting')
        timer = setTimeout(connect, backoffMs(attempt++))
      }
    }

    setStatus('connecting')
    connect()
    return () => {
      // Runs on unmount, logout, or when the tag set changes.
      disposed = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [token, tagKey])

  return status
}
