import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { usePager } from '../pager.jsx'

const PHASES = ['plan', 'build', 'test', 'review', 'finish']

export default function Builds({ openWorkspace }) {
  const [builds, setBuilds] = useState(null)
  const [form, setForm] = useState({ name: '', prompt: '' })
  const [err, setErr] = useState(null)
  const [open, setOpen] = useState(null)
  const [buildPage, buildPager] = usePager(builds || [], 10)

  const refresh = async () => setBuilds(await api('/builds'))
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [])

  const start = async (e) => {
    e.preventDefault(); setErr(null)
    try {
      await api('/builds', { body: form })
      setForm({ name: '', prompt: '' })
      await refresh()
    } catch (ex) { setErr(ex.message) }
  }
  const cancel = async (id) => { await api(`/builds/${id}/cancel`, { body: {} }); refresh() }

  return (
    <>
      <div className="viewhead">
        <h1>Builds</h1>
        <p>Full brief in → code-ready software out, unattended: plan → build → test-until-green →
          adversarial review → docs, with QA gates between phases. It commits locally and stops at
          code-ready — shipping stays yours.</p>
      </div>

      <div className="panel">
        <h2>Start a build</h2>
        <form onSubmit={start}>
          <label className="fl" htmlFor="build-name">New repo name</label>
          <input id="build-name" value={form.name} required placeholder="my-new-product"
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <label className="fl" htmlFor="build-prompt">The full brief — write it like a proper product spec</label>
          <textarea id="build-prompt" rows={7} value={form.prompt} required
            placeholder="What it is, who it's for, the features, the data it holds, how you'll know it works. The more complete the brief, the fewer assumptions the pipeline logs."
            onChange={(e) => setForm({ ...form, prompt: e.target.value })} />
          <div style={{ marginTop: 10 }}>
            <button className="act" type="submit">build it overnight-style</button>
          </div>
        </form>
        {err && <div className="err" role="alert">{err}</div>}
      </div>

      {buildPager && <div className="panel">{buildPager}</div>}
      {buildPage.map((b) => (
        <div className="panel" key={b.id}>
          <h2>#{b.id} — <b>{b.name}</b> <span className={`pill ${b.status === 'done' ? 'done' : b.status === 'running' ? 'running' : b.status === 'attention' ? 'GAP' : b.status}`}>{b.status}</span></h2>
          <div style={{ margin: '6px 0' }}>
            {PHASES.map((p, i) => {
              const entry = b.log.find((l) => l.phase === p)
              const state = entry ? (entry.status === 'done' ? 'PASS' : 'BLOCKER')
                : (b.phase === p && b.status === 'running' ? 'GAP' : '')
              return <span key={p} className={state ? `pill ${state}` : 'chip'} style={{ marginRight: 6 }}>
                {p}{entry ? ` ${Math.round(entry.seconds / 60)}m` : ''}</span>
            })}
            {b.tokens_out > 0 && <span className="faint"> {(b.tokens_out / 1000).toFixed(0)}k tok</span>}
          </div>
          {b.question && <div className="kickoff">Q: {b.question}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="act ghost" onClick={() => setOpen(open === b.id ? null : b.id)}>
              {open === b.id ? 'hide log' : 'phase log'}</button>
            <button className="act ghost" onClick={() => openWorkspace({ project: b.name })}>
              open in workspace</button>
            {(b.status === 'running' || b.status === 'queued') &&
              <button className="act ghost" onClick={() => cancel(b.id)}>cancel</button>}
            {(b.status === 'blocked' || b.status === 'cancelled' || b.status === 'attention') &&
              <button className="act" onClick={async () => { await api(`/builds/${b.id}/resume`, { body: {} }); refresh() }}>
                resume</button>}
          </div>
          {open === b.id && (
            <div className="mono-block" style={{ marginTop: 8 }}>
              {b.log.map((l, i) => `[${l.phase} · ${l.model} · ${l.seconds}s · qa:${l.qa_overall}]\n${l.summary}\n\n`).join('') || 'no phases completed yet'}
            </div>
          )}
        </div>
      ))}
      {(builds || []).length === 0 && <div className="panel"><div className="faint">no builds yet</div></div>}
    </>
  )
}
