import { useState } from 'react'
import { api, useData } from '../api.js'

// change-status → existing pill vocabulary (queued=amber, done=quiet, dismissed=faint)
const STATUS_PILL = { proposed: 'queued', merged: 'done', discarded: 'dismissed' }

const CAP = 10 // changes shown before the "older" fold

export default function ImprovePanel({ bump }) {
  const [ver, setVer] = useState(0) // local refetch counter — bumped after every action
  const { data, error, loading } = useData('/improve', bump + ver)
  const { data: fleet } = useData('/fleet', bump)
  const [pick, setPick] = useState('')
  const [tKind, setTKind] = useState('skill')
  const [tPick, setTPick] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('') // async progress text (role="status")
  const [actErr, setActErr] = useState('') // action failures (role="alert"), e.g. 409 detail

  const call = async (path, body, okNote) => {
    setBusy(true)
    setActErr('')
    setNote('')
    try {
      await api(path, { body })
      if (okNote) setNote(okNote)
      setVer((v) => v + 1)
    } catch (e) {
      setActErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  const mapRepo = () => {
    if (!pick) return
    call('/improve/repos', { project: pick, enabled: true }, `${pick} mapped`)
    setPick('')
  }

  const decideChange = (c, action) => {
    // say the real merge target — the merge lands on the repo's CURRENT
    // branch, which is not always main
    const target = (fleet || []).find((f) => f.name === c.project)?.branch
    if (
      action === 'merge' &&
      !window.confirm(`Merge ${c.branch} into ${target ? `'${target}'` : 'the current branch'} of ${c.project}?`)
    )
      return
    call(
      `/improve/changes/${c.id}`,
      { action },
      action === 'merge' ? `change #${c.id} merged` : `change #${c.id} discarded`
    )
  }

  const renderChange = (c) => (
    <div key={c.id} style={{ borderTop: '1px solid var(--line-soft)', padding: '8px 0' }}>
      <div className="ctlrow" style={{ gap: 8 }}>
        <b>{c.project}</b>
        <span className="chip">{c.kind}</span>
        <span className="dim">{c.target_file}</span>
        <span className={`pill ${STATUS_PILL[c.status] || 'queued'}`}>{c.status}</span>
        <span className="faint" style={{ marginLeft: 'auto' }}>
          {(c.created_at || '').slice(0, 16)}
        </span>
      </div>
      <div className="dim" style={{ marginTop: 2 }}>
        {c.summary} · tests:{' '}
        <span className={(c.tests || '').startsWith('FAIL') ? 'err' : undefined} style={{ padding: 0 }}>
          {c.tests || 'not run'}
        </span>
        {c.model && <span className="faint"> · {c.model}</span>}
      </div>
      {c.status === 'proposed' && (
        <>
          <details style={{ marginTop: 6 }}>
            <summary>view diff</summary>
            <div className="mono-block" style={{ marginTop: 6 }}>
              {c.diff}
            </div>
          </details>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="act" disabled={busy} onClick={() => decideChange(c, 'merge')}>
              merge
            </button>
            <button className="act ghost" disabled={busy} onClick={() => decideChange(c, 'discard')}>
              discard
            </button>
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
  const pending = changes.filter((c) => c.status === 'proposed').length
  const runBlocked = !data?.armed
    ? 'improver is disarmed (NOIRDECK_IMPROVER_ARMED) — fail-closed'
    : !data?.model_available
      ? 'local model offline — start Ollama first'
      : null

  return (
    <>
      <div className="panel">
        <h2>Local improver — scope & controls</h2>
        <p className="sechint">
          A local model (via Ollama — zero cloud calls) quietly proposes small, safe improvements: docstrings, comment
          tidy, READMEs. It only ever works on what you map or arm here, on isolated branches, and nothing merges
          without your click.
        </p>
        {loading && !data && <div className="loading">checking the improver</div>}
        {error && (
          <div className="err" role="alert">
            {error.message}
          </div>
        )}
        {data && (
          <>
            <div className="subsec">Status</div>
            <div className="ctlrow">
              <span className={`pill ${data.armed ? 'GAP' : 'dismissed'}`}>{data.armed ? 'armed' : 'off'}</span>
              <span className="dim">
                model <b>{data.model}</b>
              </span>
              <span className={`pill ${data.model_available ? 'PASS' : 'BLOCKER'}`}>
                {data.model_available ? 'reachable' : 'local model offline'}
              </span>
              <button
                className="act"
                disabled={busy || !!runBlocked}
                title={runBlocked || 'propose one small change per enabled repo, on isolated branches'}
                onClick={() => call('/improve/run', {}, 'run started — proposals appear below as they land')}
              >
                run now
              </button>
            </div>

            <div className="subsec">Repos under improvement</div>
            <div className="formrow" style={{ maxWidth: 480 }}>
              <div style={{ flex: 1 }}>
                <label className="fl" htmlFor="improve-repo">
                  Map a repo
                </label>
                <select id="improve-repo" value={pick} disabled={busy} onChange={(e) => setPick(e.target.value)}>
                  <option value="">— choose a repo —</option>
                  {unmapped.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
              <button className="act" disabled={busy || !pick} onClick={mapRepo} style={{ marginBottom: 1 }}>
                map repo
              </button>
            </div>
            <div style={{ marginTop: 8 }}>
              {repos.length === 0 && (
                <div className="dim">
                  no repos mapped — map one above and the local model will start proposing small improvements.
                </div>
              )}
              {repos.map((r) => (
                <span key={r.id} className="chipgroup">
                  <span className={r.enabled ? 'chip hot' : 'chip'}>{r.project}</span>
                  {(data.models || []).length > 0 && (
                    <select
                      value={r.model || ''}
                      disabled={busy}
                      aria-label={`AI model for ${r.project}`}
                      onChange={(e) =>
                        call(
                          '/improve/repos',
                          { project: r.project, enabled: !!r.enabled, model: e.target.value },
                          `${r.project} → ${e.target.value || `default (${data.model})`}`
                        )
                      }
                    >
                      <option value="">default ({data.model})</option>
                      {data.models.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  )}
                  <button
                    className="act ghost sm"
                    disabled={busy}
                    aria-label={`${r.enabled ? 'disable' : 'enable'} improvements for ${r.project}`}
                    onClick={() => call('/improve/repos', { project: r.project, enabled: !r.enabled })}
                  >
                    {r.enabled ? 'disable' : 'enable'}
                  </button>
                </span>
              ))}
            </div>

            {/* estate targets: ~/.claude assets, individually armed, output goes
                through the Proposals view (never written directly) */}
            {data.targets && data.assets && (
              <>
                <div className="subsec">Estate targets — skills + memory, armed by you</div>
                <div className="formrow" style={{ maxWidth: 620 }}>
                  <div>
                    <label className="fl" htmlFor="imp-tkind">
                      Type
                    </label>
                    <select
                      id="imp-tkind"
                      value={tKind}
                      disabled={busy}
                      onChange={(e) => {
                        setTKind(e.target.value)
                        setTPick('')
                      }}
                    >
                      <option value="skill">skill</option>
                      <option value="memory">memory</option>
                    </select>
                  </div>
                  <div style={{ flex: 1 }}>
                    <label className="fl" htmlFor="imp-tpick">
                      Add a target
                    </label>
                    <select id="imp-tpick" value={tPick} disabled={busy} onChange={(e) => setTPick(e.target.value)}>
                      <option value="">— choose a {tKind} —</option>
                      {(data.assets[tKind] || [])
                        .filter((a) => !data.targets.some((t) => t.target_path === a.target_path))
                        .map((a) => (
                          <option key={a.target_path} value={a.target_path}>
                            {a.label}
                          </option>
                        ))}
                    </select>
                  </div>
                  <button
                    className="act"
                    disabled={busy || !tPick}
                    style={{ marginBottom: 1 }}
                    onClick={() => {
                      call(
                        '/improve/targets',
                        { kind: tKind, target_path: tPick },
                        'added disarmed — arm it to let the improver work on it'
                      )
                      setTPick('')
                    }}
                  >
                    add
                  </button>
                </div>
                <div style={{ marginTop: 8 }}>
                  {data.targets.length === 0 && (
                    <div className="dim">
                      no estate targets — the improver only ever touches what you add AND arm here; results appear as
                      proposals.
                    </div>
                  )}
                  {data.targets.map((t) => (
                    <span key={t.id} className="chipgroup">
                      <span
                        className={t.armed ? 'chip hot' : 'chip'}
                        title={t.armed ? `armed until ${(t.armed_until || '').slice(0, 16)}` : 'disarmed'}
                      >
                        {t.kind}: {t.target_path.split('/').slice(-2).join('/')}
                      </span>
                      {(data.models || []).length > 0 && (
                        <select
                          value={t.model || ''}
                          disabled={busy}
                          aria-label={`AI model for ${t.target_path}`}
                          onChange={(e) =>
                            call('/improve/targets', {
                              kind: t.kind,
                              target_path: t.target_path,
                              model: e.target.value,
                            })
                          }
                        >
                          <option value="">default ({data.model})</option>
                          {data.models.map((m) => (
                            <option key={m} value={m}>
                              {m}
                            </option>
                          ))}
                        </select>
                      )}
                      <button
                        className="act ghost sm"
                        disabled={busy}
                        onClick={() =>
                          call(
                            `/improve/targets/${t.id}`,
                            { action: t.armed ? 'disarm' : 'arm' },
                            t.armed ? 'disarmed' : 'armed for 7 days'
                          )
                        }
                      >
                        {t.armed ? 'disarm' : 'arm 7d'}
                      </button>
                      <button
                        className="x"
                        aria-label={`Remove target ${t.target_path}`}
                        onClick={() => call(`/improve/targets/${t.id}`, { action: 'remove' }, 'removed')}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </>
            )}

            {/* what the improver has learned from merge/discard decisions —
                deterministic tallies that re-rank and mute future candidates */}
            {data.learning && Object.keys(data.learning.kinds).length > 0 && (
              <>
                <div className="subsec">Learned from your decisions</div>
                <div className="dim">
                  {Object.entries(data.learning.kinds)
                    .map(([k, s]) => `${k} ${s.merged}✓/${s.discarded}✗`)
                    .join(' · ')}
                  {Object.keys(data.learning.models).length > 0 && (
                    <>
                      {' '}
                      — by model:{' '}
                      {Object.entries(data.learning.models)
                        .map(([m, s]) => `${m} ${s.merged}✓/${s.discarded}✗`)
                        .join(' · ')}
                    </>
                  )}
                  {data.learning.muted.length > 0 && (
                    <span>
                      {' '}
                      — muted: <b>{data.learning.muted.join(', ')}</b> (merge one to un-mute)
                    </span>
                  )}
                </div>
              </>
            )}

            {actErr && (
              <div className="err" role="alert">
                {actErr}
              </div>
            )}
            <div role="status" aria-live="polite" className="dim">
              {note}
            </div>
          </>
        )}
      </div>

      {data && (
        <div className="panel">
          <h2>Improver output — {pending > 0 ? <b>{pending} awaiting your decision</b> : 'proposed changes'}</h2>
          <p className="sechint">
            Each change is a branch diff with its test result. Merge lands it on the repo's current branch; discard
            teaches the ranker what not to suggest again.
          </p>
          {changes.length === 0 && (
            <div className="faint">nothing proposed yet — the improver runs nightly while armed.</div>
          )}
          {/* changes, newest first (API order) */}
          {head.map(renderChange)}
          {rest.length > 0 && (
            <details style={{ marginTop: 6 }}>
              <summary>
                {rest.length} older change{rest.length === 1 ? '' : 's'}
              </summary>
              {rest.map(renderChange)}
            </details>
          )}
        </div>
      )}
    </>
  )
}
