import { useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'

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
    setBusy(path)
    setErr(null)
    try {
      await api(path, { body })
    } catch (e) {
      // two 409s are really confirmations: replacing an existing file on approve,
      // and reverting a file that was hand-edited after it was applied
      const confirmable =
        (/target exists/.test(e.message) &&
          'This target file already exists — replace it with the proposed version?') ||
        (/changed since/.test(e.message) &&
          'This file was edited after the proposal was applied — revert it anyway and lose those edits?')
      if (confirmable && window.confirm(confirmable)) {
        try {
          await api(path, { body: { ...body, overwrite: true } })
        } catch (e2) {
          setErr(e2.message)
        }
      } else setErr(e.message)
    }
    setBusy(null)
    setRefresh((r) => r + 1)
  }

  return (
    <>
      <ViewHead
        title="Review"
        helpId="proposals"
        hint="The approval gate for changes Noirdeck wants to make to your AI workspace knowledge. Review, apply, or revert from one place."
      />

      <div className="panel">
        <h2>
          Mining — <b>find useful knowledge</b>
        </h2>
        <p className="sechint">
          Scans your session history for repeated prompts and patterns worth turning into skills or memories. Heuristic
          mining is instant and local; the LLM pass runs only while armed.
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="act" disabled={!!busy} onClick={() => act('/mine')}>
            run heuristic mining now
          </button>
          <button type="button" className="act ghost" disabled={!!busy} onClick={() => act('/mine/llm')}>
            run LLM pass (armed only)
          </button>
        </div>
        {err && (
          <div className="err" role="alert">
            {err}
          </div>
        )}
      </div>

      {(proposals || []).length > 0 && (
        <div className="listhead">
          Awaiting your decision · <b>{(proposals || []).length}</b>
        </div>
      )}
      {propPager && <div className="panel">{propPager}</div>}
      {propPage.map((p) => (
        <div className="panel" key={p.id}>
          <h2>
            #{p.id} · {p.kind} — <b>{p.title}</b>
          </h2>
          {p.target_path && (
            <div className="faint" style={{ marginBottom: 8 }}>
              → ~/.claude/{p.target_path}
            </div>
          )}
          {p.diff ? (
            <>
              {/* review the CHANGE, not a wall of full-file text */}
              <div className="mono-block">{p.diff}</div>
              <details style={{ marginTop: 6 }}>
                <summary>full proposed content</summary>
                <div className="mono-block" style={{ marginTop: 6 }}>
                  {p.body}
                </div>
              </details>
            </>
          ) : (
            <div className="mono-block">{p.body}</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button type="button" className="act" disabled={!!busy} onClick={() => act(`/proposals/${p.id}/approve`)}>
              approve{p.target_path ? ' & write' : ''}
            </button>
            <button
              type="button"
              className="act ghost"
              disabled={!!busy}
              onClick={() => act(`/proposals/${p.id}/dismiss`)}
            >
              dismiss
            </button>
          </div>
        </div>
      ))}
      {(proposals || []).length === 0 && (
        <div className="panel">
          <div className="faint">no pending proposals — run mining</div>
        </div>
      )}

      {revertible.length > 0 && (
        <div className="panel">
          <h2>
            Applied — <b>still reversible</b>
          </h2>
          <p className="sechint">
            Everything here was written to your estate with a pre-apply snapshot kept — one click undoes it. Files
            hand-edited after apply are detected and confirmed before reverting.
          </p>
          <table>
            <caption className="visually-hidden">Applied proposals that can be reverted</caption>
            <tbody>
              {revertible.slice(0, 15).map((p) => (
                <tr key={p.id}>
                  <td className="clip">
                    #{p.id} · {p.kind} — {p.title}
                  </td>
                  <td className="dim clip">~/.claude/{p.target_path}</td>
                  <td className="num">
                    <button
                      type="button"
                      className="act ghost"
                      disabled={!!busy}
                      onClick={() => act(`/proposals/${p.id}/revert`)}
                    >
                      revert this
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel">
        <h2>
          Miner insights — <b>LLM pass</b>
        </h2>
        <p className="sechint">
          Observations from the nightly LLM mining pass that aren't concrete proposals yet — patterns in how you work
          that may deserve a skill or memory later.
        </p>
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
