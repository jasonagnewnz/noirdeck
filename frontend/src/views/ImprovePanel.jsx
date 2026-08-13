import React, { useState } from 'react'
import { api, useData } from '../api.js'

// change-status → existing pill vocabulary (queued=amber, done=quiet, dismissed=faint)
const STATUS_PILL = { proposed: 'queued', merged: 'done', discarded: 'dismissed' }

const CAP = 10 // changes shown before the "older" fold

export default function ImprovePanel({ bump }) {
  const [ver, setVer] = useState(0) // local refetch counter — bumped after every action
  const { data, error, loading } = useData('/improve', bump + ver)
  const { data: fleet } = useData('/fleet', bump)
  const [pick, setPick] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')   // async progress text (role="status")
  const [actErr, setActErr] = useState('') // action failures (role="alert"), e.g. 409 detail

  const call = async (path, body, okNote) => {
    setBusy(true); setActErr(''); setNote('')
    try {
      await api(path, { body })
      if (okNote) setNote(okNote)
      setVer((v) => v + 1)
    } catch (e) { setActErr(e.message) }
    finally { setBusy(false) }
  }

  const mapRepo = () => {
    if (!pick) return
    call('/improve/repos', { project: pick, enabled: true }, `${pick} mapped`)
    setPick('')
  }

  const decideChange = (c, action) => {
    if (action === 'merge' && !window.confirm(
      `Merge ${c.branch} into ${c.project}? This lands the change on the repo's main branch.`)) return
    call(`/improve/changes/${c.id}`, { action },
      action === 'merge' ? `change #${c.id} merged` : `change #${c.id} discarded`)
  }

  const renderChange = (c) => (
    <div key={c.id} style={{ borderTop: '1px solid var(--line-soft)', padding: '8px 0' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <b>{c.project}</b>
        <span className="chip">{c.kind}</span>
        <span className="dim">{c.target_file}</span>
        <span className={`pill ${STATUS_PILL[c.status] || 'queued'}`}>{c.status}</span>
        <span className="faint" style={{ marginLeft: 'auto' }}>{(c.created_at || '').slice(0, 16)}</span>
      </div>
      <div className="dim" style={{ marginTop: 2 }}>
        {c.summary} · tests:{' '}
        <span className={(c.tests || '').startsWith('FAIL') ? 'err' : undefined}
          style={{ padding: 0 }}>{c.tests || 'not run'}</span>
      </div>
      {c.status === 'proposed' && (
        <>
          <details style={{ marginTop: 6 }}>
            <summary>view diff</summary>
            <div className="mono-block" style={{ marginTop: 6 }}>{c.diff}</div>
          </details>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="act" disabled={busy}
              onClick={() => decideChange(c, 'merge')}>merge into main</button>
            <button className="act ghost" disabled={busy}
              onClick={() => decideChange(c, 'discard')}>discard</button>
          </div>
        </>
      )}
    </div>
  )

  const repos = data?.repos || []
  const changes = data?.changes || []
  const mapped = new Set(repos.map((r) => r.project))
  const unmapped = (fleet || []).map((f) => f.name).filter((n) => !mapped.has(n))
  const head = changes.slice(0, CAP)
  const rest = changes.slice(CAP)
  const runBlocked = !data?.armed ? 'improver is disarmed (NOIRDECK_IMPROVER_ARMED) — fail-closed'
    : !data?.model_available ? 'local model offline — start Ollama first' : null

  return (
    <div className="panel">
      <h2>Improve — <b>a local model, quietly</b></h2>
      {loading && !data && <div className="loading">checking the improver</div>}
      {error && <div className="err" role="alert">{error.message}</div>}
      {data && (
        <>
          {/* status line */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className={`pill ${data.armed ? 'GAP' : 'dismissed'}`}>
              {data.armed ? 'armed' : 'off'}
            </span>
            <span className="dim">model <b>{data.model}</b></span>
            <span className={`pill ${data.model_available ? 'PASS' : 'BLOCKER'}`}>
              {data.model_available ? 'reachable' : 'local model offline'}
            </span>
            <button className="act" disabled={busy || !!runBlocked}
              title={runBlocked || 'propose one small change per enabled repo, on isolated branches'}
              onClick={() => call('/improve/run', {},
                'run started — proposals appear below as they land')}>
              run now
            </button>
          </div>

          {/* map form + mapped repos */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', maxWidth: 480 }}>
            <div style={{ flex: 1 }}>
              <label className="fl" htmlFor="improve-repo">Map a repo</label>
              <select id="improve-repo" value={pick} disabled={busy}
                onChange={(e) => setPick(e.target.value)}>
                <option value="">— choose a repo —</option>
                {unmapped.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <button className="act" disabled={busy || !pick} onClick={mapRepo}
              style={{ marginBottom: 1 }}>map repo</button>
          </div>
          <div style={{ marginTop: 8 }}>
            {repos.length === 0 && (
              <div className="dim">no repos mapped — map one above and the local model will start proposing small improvements.</div>
            )}
            {repos.map((r) => (
              <span key={r.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginRight: 12 }}>
                <span className={r.enabled ? 'chip hot' : 'chip'}>{r.project}</span>
                <button className="act ghost sm" disabled={busy}
                  aria-label={`${r.enabled ? 'disable' : 'enable'} improvements for ${r.project}`}
                  onClick={() => call('/improve/repos', { project: r.project, enabled: !r.enabled })}>
                  {r.enabled ? 'disable' : 'enable'}
                </button>
              </span>
            ))}
          </div>

          {actErr && <div className="err" role="alert">{actErr}</div>}
          <div role="status" aria-live="polite" className="dim">{note}</div>

          {/* changes, newest first (API order) */}
          <div className="faint" style={{ marginTop: 14, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.13em' }}>
            Proposed changes
          </div>
          {changes.length === 0 && (
            <div className="faint" style={{ marginTop: 4 }}>
              nothing proposed yet — the improver runs nightly while armed.
            </div>
          )}
          {head.map(renderChange)}
          {rest.length > 0 && (
            <details style={{ marginTop: 6 }}>
              <summary>{rest.length} older change{rest.length === 1 ? '' : 's'}</summary>
              {rest.map(renderChange)}
            </details>
          )}
        </>
      )}
    </div>
  )
}
