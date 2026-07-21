import { useEffect, useRef, useState } from 'react'
import type { Provenance } from './api'

export interface BusEvent {
  id: string
  topic: string
  ts: number
  provenance: Provenance
  run_id: string | null
  payload: unknown
}

/**
 * Subscribes to the backend event bus. Auto-reconnects with backoff so an
 * accidental backend restart mid-demo heals itself instead of needing an F5.
 */
export function useEventStream(limit = 300) {
  const [connected, setConnected] = useState(false)
  const [events, setEvents] = useState<BusEvent[]>([])
  const retry = useRef(0)
  const sock = useRef<WebSocket | null>(null)

  useEffect(() => {
    let disposed = false
    let timer: number | undefined

    const open = () => {
      if (disposed) return
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/ws`)
      sock.current = ws

      ws.onopen = () => {
        if (disposed) return
        retry.current = 0
        setConnected(true)
      }
      ws.onmessage = (m) => {
        try {
          const evt = JSON.parse(m.data) as BusEvent
          setEvents((prev) => {
            const next = [...prev, evt]
            return next.length > limit ? next.slice(next.length - limit) : next
          })
        } catch {
          /* ignore malformed frame */
        }
      }
      ws.onclose = () => {
        if (disposed) return
        setConnected(false)
        const delay = Math.min(8000, 500 * 2 ** retry.current++)
        timer = window.setTimeout(open, delay)
      }
      ws.onerror = () => ws.close()
    }

    open()
    return () => {
      disposed = true
      if (timer) window.clearTimeout(timer)
      sock.current?.close()
    }
  }, [limit])

  return { connected, events }
}
