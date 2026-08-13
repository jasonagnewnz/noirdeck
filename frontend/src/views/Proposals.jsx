import React, { useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'

export default function Proposals({ bump }) {
  const [refresh, setRefresh] = useState(0)
  const { data: proposals } = useData('/proposals?status=proposed', bump + refresh)
  const { data: insights } = useData('/insights', bump + refresh)
  const [propPage, propPager] = usePager(proposals || [], 10)
  const [insPage, insPager] = usePager(insights || [], 25)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)

  const act = async (path, body = {}) => {
    setBusy(path); setErr(null)
    try { await api(path, { body }) } catch (e) { setErr(e.message) }
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
          <div className="mono-block">{p.body}</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="act" disabled={!!busy} onClick={() => act(`/proposals/${p.id}/approve`)}>approve{p.target_path ? ' & write' : ''}</button>
            <button className="act ghost" disabled={!!busy} onClick={() => act(`/proposals/${p.id}/dismiss`)}>dismiss</button>
          </div>
        </div>
      ))}
      {(proposals || []).length === 0 && <div className="panel"><div className="faint">no pending proposals — run mining</div></div>}

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
