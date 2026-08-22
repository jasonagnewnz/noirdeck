import { useCallback, useEffect, useRef, useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'

const UI_KITS = [
  ['landing', 'Landing Page', 'Launch pages, offers, proof, pricing and contact flows.'],
  ['dashboard', 'Dashboard', 'Metrics, tables, filters, charts and status-heavy work.'],
  ['booking', 'Booking Flow', 'Services, availability, quote forms and confirmations.'],
  ['shopfront', 'Shopfront', 'Catalogs, menus, product pages, carts and checkout paths.'],
  ['portal', 'Admin Portal', 'Signed-in shells, records, settings and team controls.'],
  ['portfolio', 'Portfolio', 'Case studies, galleries, testimonials and contact CTAs.'],
]
const LEGACY_KIT_LABELS = {
  mix: 'Mixed kits',
  bespoke: 'Legacy kit',
  fluent: 'Legacy kit',
  material: 'Legacy kit',
  carbon: 'Legacy kit',
  antd: 'Legacy kit',
  shadcn: 'Legacy kit',
}
const KIT_LABEL = { ...Object.fromEntries(UI_KITS.map(([value, label]) => [value, label])), ...LEGACY_KIT_LABELS }

const ROUND_PILL = {
  proposing: 'running',
  ready: 'done',
  applying: 'queued',
  applied: 'done',
  'apply-blocked': 'blocked',
}
const VARIANT_PILL = { running: 'running', done: 'done', failed: 'blocked' }

export default function Design({ launch }) {
  const { data: fleet } = useData('/fleet', 0)
  const [rounds, setRounds] = useState(null)
  const [form, setForm] = useState({ project: '', brief: '', library: 'landing' })
  const [captureProject, setCaptureProject] = useState('')
  const [capture, setCapture] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [applyingId, setApplyingId] = useState(null)
  const [roundPage, roundPager] = usePager(rounds || [], 5)
  const launched = useRef(null)

  const refresh = useCallback(async () => setRounds(await api('/design')), [])
  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (launch?.view !== 'design' || launched.current === launch.id) return
    launched.current = launch.id
    setCapture(null)
    setCaptureProject(launch.captureProject || '')
    setForm((f) => ({
      ...f,
      project: launch.project || f.project,
      brief: launch.prompt || f.brief,
    }))
  }, [launch])

  // Poll only while something is in flight: proposing (mocks rendering) or applying (writing to the repo).
  useEffect(() => {
    const active = (rounds || []).some((r) => r.status === 'proposing' || r.status === 'applying')
    if (!active) return
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [rounds, refresh])

  const propose = async (e) => {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await api('/design', { body: form })
      setForm((f) => ({ ...f, brief: '' }))
      setCapture(null)
      await refresh()
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setBusy(false)
    }
  }

  const captureDesign = async () => {
    if (!captureProject) return
    setErr(null)
    setCapturing(true)
    try {
      const next = await api('/design/capture', { body: { project: captureProject } })
      setCapture(next)
      setForm((f) => ({ ...f, brief: next.brief, library: next.suggested_kit || f.library }))
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setCapturing(false)
    }
  }

  const applyVariant = async (round, key) => {
    setErr(null)
    setApplyingId(round.id)
    try {
      await api(`/design/${round.id}/apply`, { body: { variant: key } })
      await refresh()
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setApplyingId(null)
    }
  }

  const dismiss = async (round) => {
    if (!confirm(`Dismiss round #${round.id}: ${round.project}?`)) return
    setErr(null)
    try {
      const r = await fetch(`/api/design/${round.id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error(r.statusText || 'dismiss failed')
      await refresh()
    } catch (ex) {
      setErr(ex.message)
    }
  }

  return (
    <>
      <ViewHead
        title="Design"
        helpId="design"
        hint="Pick a project, choose one of six UI kits or capture a design from another project, then compare live previews before applying the winner."
      />

      <div className="panel">
        <h2>Design the product</h2>
        <p className="sechint">
          Choose where the UI should land, capture an existing design or describe the look, then generate three
          sandboxed previews. The project changes only after you apply a winning preview.
        </p>
        <form onSubmit={propose}>
          <label className="fl" htmlFor="design-project">
            Target project
          </label>
          <select
            id="design-project"
            value={form.project}
            required
            onChange={(e) => setForm({ ...form, project: e.target.value })}
          >
            <option value="">choose project</option>
            {(fleet || []).map((f) => (
              <option key={f.path} value={f.name}>
                {f.name}
              </option>
            ))}
          </select>

          <label className="fl" htmlFor="design-capture">
            Capture a design
          </label>
          <div className="capture-row">
            <select
              id="design-capture"
              value={captureProject}
              onChange={(e) => {
                setCaptureProject(e.target.value)
                setCapture(null)
              }}
            >
              <option value="">source project</option>
              {(fleet || []).map((f) => (
                <option key={f.path} value={f.name}>
                  {f.name}
                </option>
              ))}
            </select>
            <button className="act ghost" type="button" disabled={!captureProject || capturing} onClick={captureDesign}>
              {capturing ? 'capturing…' : 'capture design'}
            </button>
          </div>
          {capture && (
            <div className="capture-summary">
              <b>{capture.summary}</b>
              <div className="capture-tags">
                {(capture.evidence?.stack || []).slice(0, 5).map((item) => (
                  <span className="chip" key={item}>
                    {item}
                  </span>
                ))}
                {(capture.evidence?.colors || []).slice(0, 4).map((item) => (
                  <span className="chip hot" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            </div>
          )}

          <label className="fl" htmlFor="design-brief">
            UI brief
          </label>
          <textarea
            id="design-brief"
            rows={4}
            value={form.brief}
            required
            placeholder="Capture a design above, or describe the UI to apply."
            onChange={(e) => setForm({ ...form, brief: e.target.value })}
          />
          <fieldset className="kit-field">
            <legend className="fl">UI kit</legend>
            <div className="kit-grid">
              {UI_KITS.map(([value, label, hint]) => (
                <label className={`kit-card ${form.library === value ? 'on' : ''}`} key={value}>
                  <input
                    type="radio"
                    name="design-kit"
                    value={value}
                    checked={form.library === value}
                    onChange={(e) => setForm({ ...form, library: e.target.value })}
                  />
                  <span className="kit-name">{label}</span>
                  <span className="kit-hint">{hint}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div style={{ marginTop: 10 }}>
            <button className="act" type="submit" disabled={busy}>
              {busy ? 'creating previews…' : 'apply a UI'}
            </button>
          </div>
        </form>
        {err && (
          <div className="err" role="alert">
            {err}
          </div>
        )}
      </div>

      {(rounds || []).length > 0 && (
        <div className="listhead">
          UI rounds · <b>{(rounds || []).length}</b>
        </div>
      )}
      {roundPager && <div className="panel">{roundPager}</div>}
      {roundPage.map((r) => (
        <div className="panel" key={r.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
            <h2 style={{ marginBottom: 0 }}>
              #{r.id} <b>{r.project}</b>: {r.brief} ({KIT_LABEL[r.library] || r.library}){' '}
              <span className={`pill ${ROUND_PILL[r.status] || ''}`}>{r.status}</span>
            </h2>
            <button
              className="act ghost"
              type="button"
              style={{ flexShrink: 0 }}
              disabled={r.status === 'applying'}
              onClick={() => dismiss(r)}
            >
              dismiss
            </button>
          </div>

          <div className="variant-grid">
            {r.variants.map((v) => {
              const canApply = (r.status === 'ready' || r.status === 'apply-blocked') && v.status === 'done'
              const isApplied = r.applied_variant === v.key
              return (
                <div className="variant-card" key={v.key}>
                  <div>
                    <span className="chip">{v.direction}</span>
                    <span className="chip hot">{KIT_LABEL[v.library] || v.library}</span>
                    <span className={`pill ${VARIANT_PILL[v.status] || ''}`} style={{ marginLeft: 4 }}>
                      {v.status}
                    </span>
                    {isApplied && (
                      <span className="pill done" style={{ marginLeft: 4 }}>
                        applied
                      </span>
                    )}
                  </div>

                  {v.status === 'running' && <div className="loading">rendering mock…</div>}
                  {v.status === 'failed' && (
                    <div className="err" role="alert">
                      {v.summary || 'mock render failed'}
                    </div>
                  )}

                  {v.status === 'done' && (
                    <>
                      {v.summary && (
                        <p className="dim" style={{ fontSize: 12 }}>
                          {v.summary}
                        </p>
                      )}
                      <div className="mockframe">
                        <iframe src={`/api/design/${r.id}/mock/${v.key}`} sandbox="" title={`${r.id}-${v.key} mock`} />
                      </div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <a
                          className="act ghost"
                          style={{ textDecoration: 'none', display: 'inline-block' }}
                          href={`/api/design/${r.id}/mock/${v.key}`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          open full
                        </a>
                        {canApply && (
                          <button
                            className="act"
                            type="button"
                            disabled={applyingId === r.id || r.status === 'applying'}
                            onClick={() => applyVariant(r, v.key)}
                          >
                            {applyingId === r.id ? 'applying…' : 'apply this UI'}
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
            <div className="kickoff" style={{ marginTop: 10 }}>
              {r.apply_summary}
            </div>
          )}
          {r.status === 'apply-blocked' && (
            <div className="err" role="alert" style={{ marginTop: 10 }}>
              apply blocked: {r.apply_summary || 'see logs'}
            </div>
          )}
        </div>
      ))}
      {(rounds || []).length === 0 && (
        <div className="panel">
          <div className="faint">no design rounds yet</div>
        </div>
      )}
    </>
  )
}
