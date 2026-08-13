import { useEffect, useRef, useState } from 'react'

export async function api(path, opts) {
  const r = await fetch(`/api${path}`, opts && {
    method: opts.method || 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts.body ?? {}),
  })
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail || detail } catch { /* keep statusText */ }
    throw new Error(detail)
  }
  return r.json()
}

// Fetch on mount + refetch when the SSE bus reports a change (bump) — the "live" in live view.
export function useData(path, bump = 0) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    let alive = true
    api(path)
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState({ data: null, error, loading: false }))
    return () => { alive = false }
  }, [path, bump])
  return state
}

export function useEvents() {
  const [live, setLive] = useState(false)
  const [bump, setBump] = useState(0)
  const src = useRef(null)
  useEffect(() => {
    const es = new EventSource('/api/events')
    src.current = es
    es.onopen = () => setLive(true)
    es.onerror = () => setLive(false)
    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'change') setBump((b) => b + 1)
        if (msg.type === 'hello' || msg.type === 'ping') setLive(true)
      } catch { /* ignore malformed */ }
    }
    return () => es.close()
  }, [])
  return { live, bump }
}

export const ago = (tsSec) => {
  if (!tsSec) return '—'
  const s = Math.max(0, Date.now() / 1000 - tsSec)
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}
