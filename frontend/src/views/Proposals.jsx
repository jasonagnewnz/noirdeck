import React, { useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'

export default function Proposals({ bump }) {
  const [refresh, setRefresh] = useState(0)
  const { data: proposals } = useData('/proposals?status=proposed', bump + refresh)
  const { data: applied } = useData('/proposals?status=approved', bump + refresh)
  // only rows with a written file AND a pre-apply snapshot can be undone
  const revertible = (applied || []).filter((p) => p.target_path && p.prior_existed !== null)
  const { data: insights } = useData('/insights', bump + refresh)
  const [propPage, propPager] = usePager(proposals || [], 10)
  const [insPage, insPager] = usePager(insights || [], 25)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)

  const act = async (path, body = {}) => {
    setBusy(path); setErr(null)
    try { await api(path, { body }) } catch (e) {
      // two 409s are really confirmations: replacing an existing file on approve,
      // and reverting a file that was hand-edited after it was applied
      const confirmable =
        (/target exists/.test(e.message) &&
          'This target file already exists — replace it with the proposed version?') ||
        (/changed since/.test(e.message) &&
          'This file was edited after the proposal was applied — revert it anyway and lose those edits?')
      if (confirmable && window.confirm(confirmable)) {
        try { await api(path, { body: { ...body, overwrite: true } }) } catch (e2) { setErr(e2.message) }
      } else setErr(e.message)
    }
    setBusy(null); setRefresh((r) => r + 1)
  }

  return (
    <>
      <div className="viewhead">
        <h1>Proposals</h1>
        <p>Everything noirdeck wants to add to your estate — nothing lands in ~/.claude until you approve it here.</p>
      </div>

      <div className="panel">
        <h2>Mining</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="act" disabled={!!busy} onClick={() => act('/mine')}>run heuristic mining now</button>
          <button className="act ghost" disabled={!!busy} onClick={() => act('/mine/llm')}>run LLM pass (armed only)</button>
        </div>
        {err && <div className="err" role="alert">{err}</div>}
      </div>

      {propPager && <div className="panel">{propPager}</div>}
      {propPage.map((p) => (
        <div className="panel" key={p.id}>
          <h2>#{p.id} · {p.kind} — <b>{p.title}</b></h2>
          {p.target_path && <div className="faint" style={{ marginBottom: 8 }}>→ ~/.claude/{p.target_path}</div>}
          {p.diff ? (
            <>
              {/* review the CHANGE, not a wall of full-file text */}
              <div className="mono-block">{p.diff}</div>
              <details style={{ marginTop: 6 }}>
                <summary>full proposed content</summary>
                <div className="mono-block" style={{ marginTop: 6 }}>{p.body}</div>
              </details>
            </>
          ) : (
            <div className="mono-block">{p.body}</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="act" disabled={!!busy} onClick={() => act(`/proposals/${p.id}/approve`)}>approve{p.target_path ? ' & write' : ''}</button>
            <button className="act ghost" disabled={!!busy} onClick={() => act(`/proposals/${p.id}/dismiss`)}>dismiss</button>
          </div>
        </div>
      ))}
      {(proposals || []).length === 0 && <div className="panel"><div className="faint">no pending proposals — run mining</div></div>}

      {revertible.length > 0 && (
        <div className="panel">
          <h2>Applied — <b>still reversible</b></h2>
          <p className="faint" style={{ margin: '0 0 6px' }}>
            Everything here was written to your estate and can be undone with one click.
          </p>
          <table><caption className="visually-hidden">Applied proposals that can be reverted</caption><tbody>
            {revertible.slice(0, 15).map((p) => (
              <tr key={p.id}>
                <td className="clip">#{p.id} · {p.kind} — {p.title}</td>
                <td className="dim clip">~/.claude/{p.target_path}</td>
                <td className="num">
                  <button className="act ghost" disabled={!!busy}
                    onClick={() => act(`/proposals/${p.id}/revert`)}>revert this</button>
                </td>
              </tr>
            ))}
          </tbody></table>
        </div>
      )}

      <div className="panel">
        <h2>Miner insights (LLM pass)</h2>
        {insPage.map((i) => (
          <div key={i.id} style={{ marginBottom: 6 }}>
            <span className="chip">{i.kind}</span> <span className="dim">{i.body}</span>
          </div>
        ))}
        {(insights || []).length === 0 && <div className="faint">none yet — arm and run the nightly LLM pass</div>}
        {insPager}
      </div>
    </>
  )
}
