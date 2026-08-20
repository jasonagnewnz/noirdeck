import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

// A second model looks at the live session and offers advice.
//
// Two ways in, one spine: press "ask for help", or switch on watching and let
// it speak up when the session shows a signal (a traceback, a failing test).
//
// It is ADVISORY. The consultant runs read-only and everything it produces is
// text you can read, copy or dismiss — there is nothing here to approve,
// because there is nothing it can change.

const POLL_MS = 1200
const POLL_GIVE_UP = 200 // ~4 min, past the backend's own 180s timeout

export default function ConsultPanel({ sessionId, runners = [] }) {
  const [question, setQuestion] = useState('')
  const [runner, setRunner] = useState('ollama')
  const [jobs, setJobs] = useState([])
  const [busy, setBusy] = useState(false)
  const [watching, setWatching] = useState(false)
  const [error, setError] = useState('')
  const timers = useRef(new Map())

  // Watching is per-session and off by default. Leaving a session must also
  // stop the watcher, or it keeps consulting about a terminal nobody is reading.
  useEffect(() => {
    setWatching(false)
    setJobs([])
    setError('')
    return () => {
      for (const t of timers.current.values()) clearTimeout(t)
      timers.current.clear()
    }
  }, [])

  const poll = useCallback((id, tries = 0) => {
    if (tries > POLL_GIVE_UP) return
    const t = setTimeout(async () => {
      try {
        const out = await api(`/consult/${id}`, { method: 'GET' })
        setJobs((prev) => prev.map((j) => (j.id === id ? out : j)))
        if (out.status === 'running') poll(id, tries + 1)
      } catch {
        /* the answer just does not arrive; the card keeps its running state */
      }
    }, POLL_MS)
    timers.current.set(id, t)
  }, [])

  const ask = async () => {
    if (!sessionId) return
    setBusy(true)
    setError('')
    try {
      const job = await api('/consult', { body: { session_id: sessionId, question, runner } })
      setJobs((prev) => [job, ...prev].slice(0, 8))
      setQuestion('')
      poll(job.id)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const toggleWatch = async () => {
    const next = !watching
    try {
      await api('/consult/watch', { body: { session_id: sessionId, enabled: next, runner } })
      setWatching(next)
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }

  if (!sessionId) return null

  return (
    <div className="consult">
      <div className="consult-bar">
        <button type="button" className="act" disabled={busy} onClick={ask}>
          {busy ? 'asking…' : 'ask for help'}
        </button>
        <input
          className="consult-q"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !busy && ask()}
          placeholder="optional — what do you want a second opinion on?"
          aria-label="What do you want a second opinion on?"
        />
        <select
          value={runner}
          onChange={(e) => setRunner(e.target.value)}
          aria-label="Which model to consult"
          title="Local runs on this machine with no egress. Hosted models send the (redacted) session out."
        >
          {(runners.length ? runners : [{ id: 'ollama', label: 'Ollama local' }]).map((r) => (
            <option key={r.id} value={r.id}>
              {r.label}
              {r.id === 'ollama' ? ' — local, no egress' : ''}
            </option>
          ))}
        </select>
        <label className="toggleline" htmlFor="consult-watch">
          <input id="consult-watch" type="checkbox" checked={watching} onChange={toggleWatch} />
          <span>watch and chime in</span>
        </label>
      </div>

      {error && (
        <div className="err" role="alert">
          {error}
        </div>
      )}

      {jobs.length === 0 ? (
        <p className="sechint">
          Nothing consulted yet. Everything sent is redacted for secrets first, and the consultant is read-only — it can
          suggest, never change.
        </p>
      ) : (
        <ul className="consult-list">
          {jobs.map((j) => (
            <li key={j.id} className={`consult-card is-${j.status}`}>
              <div className="consult-card-head">
                <span className="chip">{j.runner_label || j.runner}</span>
                {j.signal && <span className="chip hot">noticed: {j.signal}</span>}
                {j.redactions > 0 && (
                  <span className="chip" title="Secret-shaped values removed before the model saw this">
                    {j.redactions} redacted
                  </span>
                )}
                <span className="faint">{j.status}</span>
              </div>
              {j.question && <div className="consult-q-echo">“{j.question}”</div>}
              {j.status === 'running' && <div className="faint">thinking…</div>}
              {j.status === 'quiet' && <div className="faint">had nothing worth adding</div>}
              {j.status === 'failed' && <div className="err">{j.error}</div>}
              {j.status === 'done' && <div className="consult-answer">{j.answer}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
