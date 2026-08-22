import { useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'

// Hygiene panel: auto-dedupe/tidy findings, optimised-for-Claude memory upkeep.
// Strictly read-only except "propose merge", which drafts a proposal for the
// Proposals view: nothing is rewritten or deleted without the operator approving.
function Hygiene({ bump }) {
  const [ns, setNs] = useState('') // '' = server default (the primary namespace)
  const { data: h, loading } = useData(ns ? `/hygiene?namespace=${encodeURIComponent(ns)}` : '/hygiene', bump)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  if (loading)
    return (
      <div className="panel">
        <h2>Hygiene</h2>
        <div className="loading">scanning</div>
      </div>
    )
  const r = h?.namespace_report
  const shownNs = ns || h?.namespace || ''
  const canPropose = !!h && shownNs === h.primary_namespace
  const merge = async (files) => {
    setBusy(true)
    setMsg(null)
    try {
      const out = await api('/hygiene/merge', { body: { namespace: ns, files } })
      setMsg(`proposal #${out.proposal_id} drafted → review it in Proposals`)
    } catch (e) {
      setMsg(e.message)
    } finally {
      setBusy(false)
    }
  }
  const pairList = [
    ...(r?.exact_dupes || []).map((g) => ({ files: g, label: 'exact duplicate', ratio: 1 })),
    ...(r?.near_dupes || []).map((p) => ({ files: [p.a, p.b], label: 'near duplicate', ratio: p.ratio })),
  ]
  return (
    <div className="panel">
      <h2>
        Hygiene: <b>{h?.finding_count ?? 0} findings</b>
      </h2>
      <p className="sechint">
        Read-only upkeep scan: duplicates, near-empty and oversized files, dangling [[links]], index drift. "propose
        merge" drafts a consolidation through the Proposals view: nothing here rewrites or deletes anything directly.
      </p>
      <div className="ctlrow" style={{ marginBottom: 10 }}>
        <select
          value={shownNs}
          onChange={(e) => setNs(e.target.value)}
          style={{ maxWidth: 320 }}
          aria-label="Memory namespace"
        >
          {(h?.available_namespaces || (shownNs ? [shownNs] : [])).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        {!canPropose && h && <span className="faint">read-only scan: proposals only target {h.primary_namespace}</span>}
        {msg && <span className="chip hot">{msg}</span>}
      </div>
      {!r && <div className="faint">this project has no memories yet</div>}
      {r && (
        <>
          {r.skipped && <div className="dim">⚠ {r.skipped}</div>}
          {pairList.length > 0 && (
            <details open>
              <summary>
                <span className="chip hot">duplicates</span> ×{pairList.length}
              </summary>
              <div style={{ padding: '6px 0 10px 14px' }}>
                {pairList.map((p, i) => (
                  <div
                    key={i}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '2px 0', flexWrap: 'wrap' }}
                  >
                    <span className="dim">{p.files.join(' ↔ ')}</span>
                    <span className="faint">
                      {p.label}
                      {p.ratio < 1 ? ` ${Math.round(p.ratio * 100)}%` : ''}
                    </span>
                    {canPropose && (
                      <button type="button" className="act ghost" disabled={busy} onClick={() => merge(p.files)}>
                        propose merge
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
          {r.oversized.length > 0 && (
            <details>
              <summary>
                <span className="chip">oversized</span> ×{r.oversized.length}{' '}
                <span className="faint">· token diet: split or trim</span>
              </summary>
              <div style={{ padding: '6px 0 10px 14px' }}>
                {r.oversized.map((f) => (
                  <div key={f.file} className="dim">
                    · {f.file} <span className="faint">{(f.size / 1024).toFixed(1)}KB</span>
                  </div>
                ))}
              </div>
            </details>
          )}
          {r.tiny.length > 0 && (
            <details>
              <summary>
                <span className="chip">near-empty</span> ×{r.tiny.length}
              </summary>
              <div style={{ padding: '6px 0 10px 14px' }}>
                {r.tiny.map((f) => (
                  <div key={f.file} className="dim">
                    · {f.file} <span className="faint">{f.size}B</span>
                  </div>
                ))}
              </div>
            </details>
          )}
          {r.dangling_links.length > 0 && (
            <details>
              <summary>
                <span className="chip">dangling [[links]]</span> ×{r.dangling_links.length}{' '}
                <span className="faint">· memories worth writing, or typos</span>
              </summary>
              <div style={{ padding: '6px 0 10px 14px' }}>
                {r.dangling_links.map((d) => (
                  <div key={d.file} className="dim">
                    · {d.file} → {d.links.join(', ')}
                  </div>
                ))}
              </div>
            </details>
          )}
          {(r.index_missing_files.length > 0 || r.unindexed.length > 0) && (
            <details>
              <summary>
                <span className="chip">index drift</span>: {r.index_missing_files.length} broken, {r.unindexed.length}{' '}
                unindexed
              </summary>
              <div style={{ padding: '6px 0 10px 14px' }}>
                {r.index_missing_files.map((f) => (
                  <div key={f} className="dim">
                    · MEMORY.md → missing {f}
                  </div>
                ))}
                {r.unindexed.map((f) => (
                  <div key={f} className="dim">
                    · not in MEMORY.md: {f}
                  </div>
                ))}
              </div>
            </details>
          )}
          {(h?.skill_dupes || []).length > 0 && (
            <details>
              <summary>
                <span className="chip hot">duplicate skills</span> ×{h.skill_dupes.length}
              </summary>
              <div style={{ padding: '6px 0 10px 14px' }}>
                {h.skill_dupes.map((g, i) => (
                  <div key={i} className="dim">
                    · {g.join(' ↔ ')}
                  </div>
                ))}
              </div>
            </details>
          )}
          {h?.finding_count === 0 && <div className="faint">clean: nothing to tidy</div>}
        </>
      )}
    </div>
  )
}

export default function Memories({ bump }) {
  const { data, loading } = useData('/memories', bump)
  const [q, setQ] = useState('')
  const ql = q.toLowerCase()
  const mems = (data?.memories || []).filter(
    (m) => !ql || m.name.toLowerCase().includes(ql) || (m.description || '').toLowerCase().includes(ql)
  )
  const [memPage, memPager] = usePager(mems, 50)
  if (loading) return <div className="loading">reading memory namespaces</div>
  return (
    <>
      <ViewHead
        title="Memories"
        helpId="memories"
        hint={`Everything your sessions remember: ${data.stats.total} files across ${data.stats.namespaces} namespaces: with the upkeep tooling to keep that knowledge base lean.`}
      />

      <div className="listhead">By type</div>
      <div className="grid cols-4">
        {Object.entries(data.stats.by_type).map(([t, c]) => (
          <div className="stat" key={t}>
            <div className="k">{t}</div>
            <div className="v">{c}</div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 14 }}>
        <Hygiene bump={bump} />
      </div>

      <div className="panel">
        <h2>All memories</h2>
        <p className="sechint">The raw inventory: filter by name or description.</p>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="filter…"
          style={{ marginBottom: 10 }}
          aria-label="Filter memories"
        />
        <table>
          <caption className="visually-hidden">All memory files across namespaces</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Description</th>
              <th scope="col">Type</th>
              <th scope="col">Namespace</th>
            </tr>
          </thead>
          <tbody>
            {memPage.map((m) => (
              <tr key={m.namespace + m.file}>
                <td style={{ whiteSpace: 'nowrap' }}>{m.name}</td>
                <td className="dim clip" title={m.description}>
                  {m.description}
                </td>
                <td className="faint">{m.type || '—'}</td>
                <td className="faint">{m.namespace}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {memPager}
      </div>
    </>
  )
}
