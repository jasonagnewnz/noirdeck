import React, { useEffect, useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'

const LIBRARIES = [
  ['mix', 'Mix it up'],
  ['bespoke', 'Bespoke CSS'],
  ['fluent', 'Fluent 2'],
  ['material', 'Material 3'],
  ['carbon', 'IBM Carbon'],
  ['antd', 'Ant Design'],
  ['shadcn', 'shadcn/Radix'],
]
const LIB_LABEL = Object.fromEntries(LIBRARIES)

const ROUND_PILL = {
  proposing: 'running',
  ready: 'done',
  applying: 'queued',
  applied: 'done',
  'apply-blocked': 'blocked',
}
const VARIANT_PILL = { running: 'running', done: 'done', failed: 'blocked' }

export default function Design() {
  const { data: fleet } = useData('/fleet', 0)
  const [rounds, setRounds] = useState(null)
  const [form, setForm] = useState({ project: '', brief: '', library: 'mix' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [applyingId, setApplyingId] = useState(null)
  const [roundPage, roundPager] = usePager(rounds || [], 5)

  const refresh = async () => setRounds(await api('/design'))
  useEffect(() => { refresh() }, [])

  // Poll only while something is in flight — proposing (mocks rendering) or applying (writing to the repo).
  useEffect(() => {
    const active = (rounds || []).some((r) => r.status === 'proposing' || r.status === 'applying')
    if (!active) return
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [rounds])

  const propose = async (e) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      await api('/design', { body: form })
      setForm((f) => ({ ...f, brief: '' }))
      await refresh()
    } catch (ex) { setErr(ex.message) }
    finally { setBusy(false) }
  }

  const applyVariant = async (round, key) => {
    setErr(null); setApplyingId(round.id)
    try {
      await api(`/design/${round.id}/apply`, { body: { variant: key } })
      await refresh()
    } catch (ex) { setErr(ex.message) }
    finally { setApplyingId(null) }
  }

  const dismiss = async (round) => {
    if (!confirm(`Dismiss round #${round.id} — ${round.project}?`)) return
    setErr(null)
    try {
      const r = await fetch(`/api/design/${round.id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error(r.statusText || 'dismiss failed')
      await refresh()
    } catch (ex) { setErr(ex.message) }
  }

  return (
    <>
      <div className="viewhead">
        <h1>Design Studio</h1>
        <p>Propose a few directions, compare live mocks side-by-side, apply the one you like —
          mocks never touch the repo; apply writes to the real frontend and stops at code-ready.</p>
      </div>

      <div className="panel">
        <h2>Propose a round</h2>
        <form onSubmit={propose}>
          <label className="fl" htmlFor="design-project">Project</label>
          <select id="design-project" value={form.project} required
            onChange={(e) => setForm({ ...form, project: e.target.value })}>
            <option value="">— choose repo —</option>
            {(fleet || []).map((f) => <option key={f.path} value={f.name}>{f.name}</option>)}
          </select>
          <label className="fl" htmlFor="design-brief">Brief</label>
          <textarea id="design-brief" rows={4} value={form.brief} required
            placeholder="the client dashboard — dense tables, live status, dark"
            onChange={(e) => setForm({ ...form, brief: e.target.value })} />
          <label className="fl" htmlFor="design-library">Library</label>
          <select id="design-library" value={form.library} onChange={(e) => setForm({ ...form, library: e.target.value })}>
            {LIBRARIES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
          <p className="faint" style={{ marginTop: 6 }}>
            Mix it up pairs each variant with a different UI library, so you're comparing frameworks
            head-to-head as well as directions — that's the default. Pick one of the others to hold
            the library fixed and only vary direction.
          </p>
          <div style={{ marginTop: 10 }}>
            <button className="act" type="submit" disabled={busy}>propose variants</button>
          </div>
        </form>
        {err && <div className="err" role="alert">{err}</div>}
      </div>

      {roundPager && <div className="panel">{roundPager}</div>}
      {roundPage.map((r) => (
        <div className="panel" key={r.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
            <h2 style={{ marginBottom: 0 }}>#{r.id} <b>{r.project}</b> — {r.brief} ({LIB_LABEL[r.library] || r.library}){' '}
              <span className={`pill ${ROUND_PILL[r.status] || ''}`}>{r.status}</span>
            </h2>
            <button className="act ghost" style={{ flexShrink: 0 }}
              disabled={r.status === 'applying'} onClick={() => dismiss(r)}>
              dismiss</button>
          </div>

          <div className="variant-grid">
            {r.variants.map((v) => {
              const canApply = (r.status === 'ready' || r.status === 'apply-blocked') && v.status === 'done'
              const isApplied = r.applied_variant === v.key
              return (
                <div className="variant-card" key={v.key}>
                  <div>
                    <span className="chip">{v.direction}</span>
                    <span className="chip hot">{LIB_LABEL[v.library] || v.library}</span>
                    <span className={`pill ${VARIANT_PILL[v.status] || ''}`} style={{ marginLeft: 4 }}>
                      {v.status}
                    </span>
                    {isApplied && <span className="pill done" style={{ marginLeft: 4 }}>applied</span>}
                  </div>

                  {v.status === 'running' && <div className="loading">rendering mock…</div>}
                  {v.status === 'failed' && <div className="err" role="alert">{v.summary || 'mock render failed'}</div>}

                  {v.status === 'done' && (
                    <>
                      {v.summary && <p className="dim" style={{ fontSize: 12 }}>{v.summary}</p>}
                      <div className="mockframe">
                        <iframe src={`/api/design/${r.id}/mock/${v.key}`} sandbox="" title={`${r.id}-${v.key} mock`} />
                      </div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <a className="act ghost" style={{ textDecoration: 'none', display: 'inline-block' }}
                          href={`/api/design/${r.id}/mock/${v.key}`} target="_blank" rel="noopener noreferrer">
                          open full
                        </a>
                        {canApply && (
                          <button className="act" disabled={applyingId === r.id || r.status === 'applying'}
                            onClick={() => applyVariant(r, v.key)}>
                            {applyingId === r.id ? 'applying…' : 'apply'}
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )
            })}
          </div>

          {r.status === 'applied' && r.apply_summary && (
            <div className="kickoff" style={{ marginTop: 10 }}>{r.apply_summary}</div>
          )}
          {r.status === 'apply-blocked' && (
            <div className="err" role="alert" style={{ marginTop: 10 }}>apply blocked — {r.apply_summary || 'see logs'}</div>
          )}
        </div>
      ))}
      {(rounds || []).length === 0 && <div className="panel"><div className="faint">no design rounds yet</div></div>}
    </>
  )
}
