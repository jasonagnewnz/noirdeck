import React, { useState } from 'react'
import { api } from '../../api.js'

// A guided (gated) build card, narrated in plain English for a non-technical
// operator. The technical record is always one <details> away, never gone.

const STEPS = [
  ['plan', 'Designing it'],
  ['build', 'Writing the code'],
  ['test', 'Testing until it passes'],
  ['review', 'A second engineer reviews and fixes what they find'],
  ['finish', 'Writing the docs and final checks'],
]

// status -> [what the operator reads, which pill class colours it]
const FRIENDLY = {
  queued: ['Waiting to start', 'queued'],
  running: ['Being built', 'running'],
  awaiting_plan: ['Waiting for your approval', 'GAP'],
  blocked: ['Needs your attention', 'blocked'],
  attention: ['Finished — please take a look', 'GAP'],
  done: ['Done', 'done'],
  cancelled: ['Stopped', 'cancelled'],
}

// Plainer wording for the standard (auto-checked) acceptance criteria than the
// backend's stored text, which leans technical.
const STD_TEXT = {
  'std-tests': 'All the automated tests pass',
  'std-gates': 'The automatic quality checks found nothing serious',
  'std-run': 'The finished software was run end to end',
}

const h3Style = { fontSize: 12.5, fontWeight: 700, margin: '0 0 6px' }

const fmtTime = (s) => (s == null ? '—' : s < 90 ? `${s}s` : `${Math.round(s / 60)}m`)

export default function GuidedCard({ b, refresh, openWorkspace }) {
  const [checked, setChecked] = useState({}) // operator tick-offs, local only
  const [revising, setRevising] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [busy, setBusy] = useState(null) // 'approve' | 'revise' | null
  const [err, setErr] = useState(null)

  const [statusText, pillClass] = FRIENDLY[b.status] || [b.status, b.status]
  const doneSet = new Set(b.log.filter((l) => l.status === 'done').map((l) => l.phase))
  const activePhase = (b.status === 'running' || b.status === 'blocked') ? b.phase : null
  const finished = b.status === 'done' || b.status === 'attention'

  const decide = async (action) => {
    setErr(null); setBusy(action)
    try {
      await api(`/builds/${b.id}/plan`, { body: { action, feedback } })
      setRevising(false); setFeedback('')
    } catch (ex) {
      // 409 = the build is no longer waiting on the plan; the card refreshes itself.
      setErr(`That didn't go through — ${ex.message}. This page updates itself, ` +
        'so the card above should show where the build really is.')
    } finally {
      setBusy(null); refresh()
    }
  }

  const ev = b.evidence
  const phaseDone = (name) =>
    !!(ev && (ev.phases || []).some((p) => p.phase === name && p.status === 'done'))
  const stdPass = {
    'std-tests': !!ev && /passed/i.test(ev.tests || '') && phaseDone('test'),
    'std-gates': !!ev && ev.qa_overall !== 'BLOCKER',
    'std-run': phaseDone('finish'),
  }
  const operatorChecks = (b.acceptance || []).filter((c) => c.kind === 'operator')
  const standardChecks = (b.acceptance || []).filter((c) => c.kind === 'standard')

  return (
    <>
      <h2>#{b.id} — <b>{b.name}</b>{' '}
        <span className={`pill ${pillClass}`}>{statusText}</span></h2>

      {/* narrated progress stepper */}
      <div aria-label="Build progress" style={{ margin: '6px 0' }}>
        {STEPS.map(([key, label]) => {
          if (doneSet.has(key)) {
            return <span key={key} className="chip" aria-label={`${label} — finished`}>
              ✓ {label}</span>
          }
          if (activePhase === key) {
            return b.status === 'blocked'
              ? <span key={key} className="pill blocked" style={{ marginRight: 6 }}
                  aria-label={`${label} — stuck, needs your attention`}>{label} — stuck</span>
              : <span key={key} className="pill running" style={{ marginRight: 6 }}
                  aria-label={`${label} — happening now`}>{label}…</span>
          }
          return <span key={key} className="chip"
            style={{ borderStyle: 'dashed', color: 'var(--ink-dim)' }}
            aria-label={`${label} — not started yet`}>{label}</span>
        })}
        {b.phase === 'complete'
          ? <span className="chip hot" aria-label="Done">Done</span>
          : <span className="chip" style={{ borderStyle: 'dashed', color: 'var(--ink-dim)' }}
              aria-label="Done — not yet">Done</span>}
      </div>

      {/* plan approval gate */}
      {b.status === 'awaiting_plan' && (
        <div className="kickoff" style={{ marginTop: 10 }}>
          <h3 style={h3Style}>Here's the plan — nothing gets built until you approve it</h3>
          <div style={{ whiteSpace: 'pre-wrap' }}>
            {b.plan_summary || 'The plan is still being written up — check back in a moment.'}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            <button className="act" disabled={!!busy}
              onClick={() => decide('approve')}>Approve — start building</button>
            <button className="act ghost" aria-expanded={revising} disabled={!!busy}
              onClick={() => setRevising((r) => !r)}>Request changes</button>
          </div>
          {revising && (
            <div style={{ marginTop: 8 }}>
              <label className="fl" htmlFor={`plan-fb-${b.id}`}>What should change?</label>
              <textarea id={`plan-fb-${b.id}`} rows={3} value={feedback}
                placeholder="Tell the planner what to change — plain English is perfect"
                onChange={(e) => setFeedback(e.target.value)} />
              <div style={{ marginTop: 6 }}>
                <button className="act" disabled={!!busy || !feedback.trim()}
                  onClick={() => decide('revise')}>Send changes back</button>
              </div>
            </div>
          )}
          {busy && (
            <div role="status" aria-live="polite" className="dim" style={{ marginTop: 8 }}>
              {busy === 'approve' ? 'Starting the build…' : 'Sending your feedback to the planner…'}
            </div>
          )}
          {err && <div className="err" role="alert">{err}</div>}
        </div>
      )}

      {b.question && b.status !== 'awaiting_plan' && (
        <div className="kickoff" style={{ marginTop: 8 }}>The builder asks: {b.question}</div>
      )}

      {/* acceptance checklist + evidence, once the build has finished */}
      {finished && (operatorChecks.length > 0 || standardChecks.length > 0) && (
        <div style={{ marginTop: 12 }}>
          <h3 style={h3Style}>Your checklist</h3>
          {operatorChecks.length > 0 && (
            <>
              <p className="faint" style={{ margin: '0 0 4px' }}>
                Your own success checks — tick them off as you try the software.
              </p>
              {operatorChecks.map((c) => {
                const cid = `b${b.id}-acc-${c.id}`
                return (
                  <div key={c.id}
                    style={{ display: 'flex', gap: 8, alignItems: 'flex-start', margin: '4px 0' }}>
                    <input type="checkbox" id={cid} checked={!!checked[c.id]}
                      style={{ width: 'auto', margin: '3px 0 0', flexShrink: 0 }}
                      onChange={(e) =>
                        setChecked((s) => ({ ...s, [c.id]: e.target.checked }))} />
                    <label htmlFor={cid} style={{ cursor: 'pointer' }}>{c.text}</label>
                  </div>
                )
              })}
            </>
          )}
          {standardChecks.map((c) => (
            <div key={c.id}
              style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '4px 0' }}>
              <span className={`pill ${stdPass[c.id] ? 'PASS' : 'GAP'}`}>
                {stdPass[c.id] ? 'checked ✓' : 'needs a look'}</span>
              <span>{STD_TEXT[c.id] || c.text}</span>
            </div>
          ))}
        </div>
      )}

      {finished && ev && (
        <div style={{ marginTop: 12 }}>
          <h3 style={h3Style}>What was actually done</h3>
          <div>{ev.commit_count} separate pieces of work were saved along the way</div>
          {ev.change_size && <div>Size of the latest change: {ev.change_size.trim()}</div>}
          <div>Tests: {ev.tests}</div>
          <details style={{ marginTop: 6 }}>
            <summary>the full record</summary>
            <div className="mono-block" style={{ marginTop: 6 }}>
              {(ev.commits || []).join('\n') || 'no work was recorded'}
            </div>
            <table style={{ marginTop: 8 }}>
              <thead>
                <tr><th>step</th><th>time</th><th>result</th><th className="num">tokens</th></tr>
              </thead>
              <tbody>
                {(ev.phases || []).map((p, i) => (
                  <tr key={i}>
                    <td>{p.phase}</td>
                    <td>{fmtTime(p.seconds)}</td>
                    <td><span className={`pill ${p.status === 'done' ? 'done' : 'blocked'}`}>
                      {p.status}</span></td>
                    <td className="num">{p.tokens ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}

      {/* actions */}
      <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        <button className="act ghost" onClick={() => openWorkspace({ project: b.name })}>
          open in workspace</button>
        {(b.status === 'running' || b.status === 'queued') && (
          <button className="act ghost"
            onClick={async () => { await api(`/builds/${b.id}/cancel`, { body: {} }); refresh() }}>
            stop this build</button>
        )}
        {(b.status === 'blocked' || b.status === 'cancelled' || b.status === 'attention') && (
          <button className="act"
            onClick={async () => {
              try { await api(`/builds/${b.id}/resume`, { body: {} }) } catch (ex) { setErr(ex.message) }
              refresh()
            }}>
            continue this build</button>
        )}
      </div>
      {err && b.status !== 'awaiting_plan' && <div className="err" role="alert">{err}</div>}

      {/* the raw phase log, for the curious */}
      <details style={{ marginTop: 8 }}>
        <summary>technical detail</summary>
        <div className="mono-block" style={{ marginTop: 6 }}>
          {b.log.map((l) =>
            `[${l.phase} · ${l.model} · ${l.seconds}s · qa:${l.qa_overall} · ${l.tokens ?? 0} tok]\n${l.summary}\n\n`,
          ).join('') || 'no phases completed yet'}
        </div>
      </details>
    </>
  )
}
