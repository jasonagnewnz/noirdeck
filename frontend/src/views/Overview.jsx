import { useCallback, useEffect, useRef, useState } from 'react'
import { ago, api, useData } from '../api.js'
import IntentBar from '../IntentBar.jsx'
import ToolPrompter from '../ToolPrompter.jsx'

// Ask Noirdeck: a plain-English question box answered from local project state.
function AskBox({ launch }) {
  const [q, setQ] = useState('')
  const [job, setJob] = useState(null)
  const [err, setErr] = useState(null)
  const timer = useRef(null)
  const launched = useRef(null)

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

  const ask = useCallback(async (question) => {
    if (!question.trim()) return
    setErr(null)
    try {
      const { id } = await api('/ask', { body: { question } })
      setJob({ id, status: 'running', question })
    } catch (ex) {
      setErr(ex.message)
    }
  }, [])

  useEffect(() => {
    if (launch?.kind !== 'ask' || launched.current === launch.id) return
    launched.current = launch.id
    const question = launch.prompt || ''
    setQ(question)
    ask(question)
  }, [launch, ask])

  const submit = async (e) => {
    e.preventDefault()
    ask(q)
  }

  return (
    <div className="panel reveal d1">
      <h2>Ask Noirdeck</h2>
      <form onSubmit={submit} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input
          value={q}
          maxLength={500}
          style={{ flex: 1, minWidth: 260 }}
          placeholder='e.g. "which projects need attention?" — answered read-only from your actual files'
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

export default function Overview({ overview: ov, bump, launch, onIntent }) {
  const { data: commits } = useData('/commits', bump)
  const { data: dg } = useData('/digest', bump)
  const { data: fleet } = useData('/fleet', bump)
  if (!ov) return <div className="loading">getting your projects ready</div>
  const h = ov.history
  const peak = h.by_hour
    .map((c, hr) => [hr, c])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
  return (
    <>
      <IntentBar fleet={fleet || []} onIntent={onIntent} />
      <ToolPrompter fleet={fleet || []} onIntent={onIntent} />

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
            <div key={line} className={`digest-line${i < dg.attention ? ' attn' : ''}`}>
              <span className="bullet" aria-hidden="true">
                {i < dg.attention ? '▸' : '·'}
              </span>
              <span>{line}</span>
            </div>
          ))}
        </div>
      )}

      <AskBox launch={launch} />

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
          <div className="k">Reviews waiting</div>
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
          {ov.fleet_attention.length === 0 && <div className="faint">every project clean and pushed</div>}
          <table>
            <caption className="visually-hidden">Projects needing attention</caption>
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
              {(commits?.follow_on || []).slice(0, 8).map((f) => (
                <tr key={`${f.repo}-${f.kind}-${f.detail}`}>
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

        <BackupDisclosure bump={bump} />
      </div>
    </>
  )
}

// Telling people what you copy off their machine is not a footnote. This states
// it on the front page: what is protected, what is deliberately left behind, and
// whether a restore has actually been proven.
function BackupDisclosure({ bump }) {
  const { data: v } = useData('/vault', bump)
  const [show, setShow] = useState(false)
  if (!v) return null
  const man = v.manifest
  const verified = v.last_verified ? ago(new Date(v.last_verified).getTime() / 1000) : null
  return (
    <div className="panel reveal d4">
      <h2>Your backup</h2>
      <p className="sechint">
        {v.configured
          ? 'noirdeck keeps an encrypted copy of the work you cannot regenerate, and proves it by restoring a file and comparing it byte for byte after every run.'
          : 'Backups are OFF — nothing is being copied anywhere. Point NOIRDECK_VAULT_REPO at a destination to turn them on.'}
      </p>
      <div style={{ marginBottom: 8 }}>
        <span className="faint">restore verified: </span>
        {verified ? <span className="pill PASS">{verified}</span> : <span className="pill GAP">never</span>}
      </div>
      <button type="button" className="act ghost" aria-expanded={show} onClick={() => setShow(!show)}>
        {show ? 'hide' : 'what exactly is copied?'}
      </button>
      {show && man && (
        <div style={{ marginTop: 10 }}>
          <p className="subsec">Kept from {man.root}</p>
          <ul className="tight">
            {man.included.map((i) => (
              <li key={i.path}>
                <code>{i.path}</code> <span className="dim">— {i.what}</span>
                {!i.present && <span className="faint"> (not present)</span>}
              </li>
            ))}
          </ul>
          <p className="subsec">Never copied</p>
          <ul className="tight">
            {man.excluded.map((e) => (
              <li key={e.path}>
                <code>{e.path}</code> <span className="dim">— {e.why}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
