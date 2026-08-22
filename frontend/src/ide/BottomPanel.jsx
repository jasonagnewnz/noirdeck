import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import TermPane from './TermPane.jsx'

// A terminal that belongs to the shell rather than to one view.
//
// Before this existed, the only terminal in noirdeck lived inside Build Live,
// so checking on a running session meant leaving whatever you were reading.
// That is the difference between a view switcher and an IDE: not the furniture,
// but being able to see two things at once.
//
// Loaded lazily by App, because mounting it is what pulls in xterm.

const HEIGHT_KEY = 'nd.panelH'
const MIN_HEIGHT = 140

// A panel taller than the window leaves nothing to look at above it, which is
// the state people get stuck in after a drag that overshoots.
const maxHeight = () => Math.max(MIN_HEIGHT, window.innerHeight - 220)

export default function BottomPanel({ height, onResize, onClose, onOpenWorkspace }) {
  const [sessions, setSessions] = useState(null)
  const [sid, setSid] = useState(null)
  const dragFrom = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const rows = await api('/workspace')
      setSessions(rows)
      // Follow the live set rather than a remembered id: a session that ended
      // while the panel was closed must not leave it pointed at nothing.
      setSid((current) => (rows.some((r) => r.id === current) ? current : (rows[0]?.id ?? null)))
    } catch {
      setSessions([])
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Pointer events rather than mouse events, so a drag works on a touchscreen
  // and keeps delivering moves after the cursor leaves the handle.
  const startDrag = (e) => {
    e.preventDefault()
    dragFrom.current = { y: e.clientY, height }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onDrag = (e) => {
    if (!dragFrom.current) return
    const next = dragFrom.current.height + (dragFrom.current.y - e.clientY)
    onResize(Math.min(maxHeight(), Math.max(MIN_HEIGHT, next)))
  }
  const endDrag = (e) => {
    dragFrom.current = null
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    try {
      localStorage.setItem(HEIGHT_KEY, String(height))
    } catch {
      // The height still applies for this tab; only the memory of it is lost.
    }
  }

  // Keyboard resizing, because a drag handle nobody can reach is not a control.
  const onHandleKey = (e) => {
    const step = e.shiftKey ? 48 : 16
    if (e.key === 'ArrowUp') onResize(Math.min(maxHeight(), height + step))
    else if (e.key === 'ArrowDown') onResize(Math.max(MIN_HEIGHT, height - step))
    else return
    e.preventDefault()
  }

  return (
    <section className="dock" style={{ height: `${height}px` }} aria-label="Terminal panel">
      {/* biome-ignore lint/a11y/useFocusableInteractive: separator is focusable via tabIndex below */}
      <div
        className="dock-grip"
        role="separator"
        aria-label="Resize terminal panel"
        aria-orientation="horizontal"
        aria-valuenow={height}
        tabIndex={0}
        onPointerDown={startDrag}
        onPointerMove={onDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={onHandleKey}
      />
      <header className="dock-bar">
        <span className="dock-title">Terminal</span>
        {sessions?.length > 0 && (
          <select className="dock-pick" aria-label="Session" value={sid ?? ''} onChange={(e) => setSid(e.target.value)}>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.project}
                {s.runner ? ` · ${s.runner}` : ''}
              </option>
            ))}
          </select>
        )}
        <button type="button" className="dock-act" onClick={refresh} title="Re-read the live session list">
          Refresh
        </button>
        <span className="dock-spacer" />
        <button type="button" className="dock-act" onClick={onClose} title="Close the panel (Ctrl+`)">
          Close
        </button>
      </header>
      <div className="dock-body">
        {sessions === null && <p className="dock-empty">Looking for live sessions…</p>}
        {sessions?.length === 0 && (
          <p className="dock-empty">
            No session is running.{' '}
            <button type="button" className="linkish" onClick={onOpenWorkspace}>
              Start one in Build Live
            </button>
            .
          </p>
        )}
        {/* Keyed on the session id so switching sessions builds a new terminal
            rather than repainting the old one with someone else's scrollback. */}
        {sid && <TermPane key={sid} sid={sid} />}
      </div>
    </section>
  )
}
