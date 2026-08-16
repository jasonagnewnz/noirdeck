import { useEffect, useRef, useState } from 'react'
import { ago, api, useData } from '../api.js'

// Ask-your-estate: a plain-English question box answered by a read-only session.
function AskBox() {
  const [q, setQ] = useState('')
  const [job, setJob] = useState(null)
  const [err, setErr] = useState(null)
  const timer = useRef(null)

  useEffect(() => {
    if (job?.status !== 'running') return undefined
    timer.current = setInterval(async () => {
      try {
        const j = await api(`/ask/${job.id}`)
        setJob(j)
        if (j.status !== 'running') clearInterval(timer.current)
      } catch {
        /* poll again */
      }
    }, 2000)
    return () => clearInterval(timer.current)
  }, [job?.id, job?.status])

  const submit = async (e) => {
    e.preventDefault()
    setErr(null)
    try {
      const { id } = await api('/ask', { body: { question: q } })
      setJob({ id, status: 'running', question: q })
    } catch (ex) {
      setErr(ex.message)
    }
  }

  return (
    <div className="panel reveal d1">
      <h2>Ask your estate</h2>
      <form onSubmit={submit} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input
          value={q}
          maxLength={500}
          style={{ flex: 1, minWidth: 260 }}
          placeholder='e.g. "which projects have unpushed work?" — answered read-only, from your actual files'
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="act" type="submit" disabled={job?.status === 'running' || !q.trim()}>
          ask
        </button>
      </form>
      {job?.status === 'running' && (
        <div role="status" aria-live="polite" className="dim" style={{ marginTop: 8 }}>
          Reading your files to answer — usually under a minute…
        </div>
      )}
      {job && job.status !== 'running' && (
        <div className="kickoff" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
          {job.answer}
        </div>
      )}
      {err && (
        <div className="err" role="alert">
          {err}
        </div>
      )}
    </div>
  )
}

export default function Overview({ overview: ov, bump }) {
  const { data: commits } = useData('/commits', bump)
  const { data: dg } = useData('/digest', bump)
  if (!ov) return <div className="loading">reading the estate</div>
  const h = ov.history
  const peak = h.by_hour
    .map((c, hr) => [hr, c])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
  return (
    <>
      <div className="viewhead reveal">
        <h1>Estate overview</h1>
        <p>Live read of ~/.claude — {h.total_prompts.toLocaleString()} prompts of history feeding the mentor.</p>
      </div>

      {dg && (
        <div className="panel reveal d1">
          <h2>
            While you were away
            {dg.attention > 0 && (
              <>
                {' '}
                —{' '}
                <b>
                  {dg.attention} thing{dg.attention === 1 ? '' : 's'} need{dg.attention === 1 ? 's' : ''} you
                </b>
              </>
            )}
          </h2>
          {dg.lines.map((line, i) => (
            <div key={i} className={`digest-line${i < dg.attention ? ' attn' : ''}`}>
              <span className="bullet" aria-hidden="true">
                {i < dg.attention ? '▸' : '·'}
              </span>
              <span>{line}</span>
            </div>
          ))}
        </div>
      )}

      <AskBox />

      <div className="grid cols-4 reveal d1">
        <div className="stat">
          <div className="k">Skills</div>
          <div className="v">{ov.skills}</div>
        </div>
        <div className="stat">
          <div className="k">Agents</div>
          <div className="v">{ov.agents}</div>
        </div>
        <div className="stat">
          <div className="k">Memories</div>
          <div className="v">
            {ov.memories.total} <small>/ {ov.memories.namespaces} ns</small>
          </div>
        </div>
        <div className="stat accent">
          <div className="k">Proposals pending</div>
          <div className="v">{ov.proposals_pending}</div>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="panel reveal d2">
          <h2>
            Open loops — <b>sessions that ended unfinished</b>
          </h2>
          {ov.open_loops.length === 0 && <div className="faint">none detected in recent sessions</div>}
          <table>
            <caption className="visually-hidden">Sessions that ended unfinished</caption>
            <tbody>
              {ov.open_loops.map((s) => (
                <tr key={s.session_id}>
                  <td className="clip">{s.first_prompt || <span className="faint">(untitled session)</span>}</td>
                  <td className="dim num">{ago(s.mtime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel reveal d2">
          <h2>
            Fleet attention — <b>work at risk</b>
          </h2>
          {ov.fleet_attention.length === 0 && <div className="faint">every repo clean and pushed</div>}
          <table>
            <caption className="visually-hidden">Repos needing attention</caption>
            <tbody>
              {ov.fleet_attention.slice(0, 8).map((f) => (
                <tr key={f.path}>
                  <td>
                    {f.name} <span className="faint">[{f.branch}]</span>
                  </td>
                  <td className="dim">{f.reasons.join('; ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="panel reveal d3">
          <h2>Recent sessions</h2>
          <table>
            <caption className="visually-hidden">Recent Claude Code sessions</caption>
            <tbody>
              {ov.recent_sessions.slice(0, 8).map((s) => (
                <tr key={s.session_id}>
                  <td className="clip">{s.first_prompt || <span className="faint">(system)</span>}</td>
                  <td className="dim num">{ago(s.mtime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel reveal d3">
          <h2>
            Follow-on radar — <b>changes missing their companion</b>
          </h2>
          {(commits?.follow_on || []).length === 0 && <div className="faint">nothing flagged</div>}
          <table>
            <caption className="visually-hidden">Commits missing a likely companion change</caption>
            <tbody>
              {(commits?.follow_on || []).slice(0, 8).map((f, i) => (
                <tr key={i}>
                  <td className="faint" style={{ whiteSpace: 'nowrap' }}>
                    {f.repo}
                  </td>
                  <td>
                    <span className="chip hot">{f.kind}</span>
                  </td>
                  <td className="dim clip" title={f.detail}>
                    {f.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="panel reveal d4">
          <h2>Fleet commits</h2>
          <table>
            <caption className="visually-hidden">Recent commits across the fleet</caption>
            <tbody>
              {(commits?.feed || []).slice(0, 10).map((c) => (
                <tr key={c.repo + c.sha}>
                  <td className="faint" style={{ whiteSpace: 'nowrap' }}>
                    {c.repo}
                  </td>
                  <td className="clip">{c.subject}</td>
                  <td className="dim num">{ago(c.ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel reveal d4">
          <h2>Rhythm</h2>
          <div style={{ marginBottom: 8 }}>
            <span className="faint">peak hours (NZ): </span>
            {peak.map(([hr]) => (
              <span key={hr} className="chip hot">
                {String(hr).padStart(2, '0')}:00
              </span>
            ))}
          </div>
          <div style={{ marginBottom: 8 }}>
            <span className="faint">top slash: </span>
            {h.top_slash.slice(0, 6).map(([s, c]) => (
              <span key={s} className="chip">
                {s} ×{c}
              </span>
            ))}
          </div>
          <div>
            <span className="faint">busiest projects: </span>
            {h.top_projects.slice(0, 5).map(([p, c]) => (
              <span key={p} className="chip">
                {p.split('/').pop() || p} ×{c}
              </span>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
