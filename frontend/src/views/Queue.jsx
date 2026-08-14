import React, { useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'

// Arming = a CONTRACT, not a switch: expiry + task/token budget, revocable,
// double-gated with the env master flags. Runners re-check before every task.
function ArmPanel({ bump }) {
  const [refresh, setRefresh] = useState(0)
  const { data } = useData('/arming', bump + refresh)
  const [form, setForm] = useState({ hours: '10', max_tasks: '10', max_tokens: '' })
  const [err, setErr] = useState(null)
  const doArm = async (subsystem) => {
    setErr(null)
    try {
      await api('/arming', { body: {
        subsystem, hours: Number(form.hours) || 10,
        max_tasks: form.max_tasks ? Number(form.max_tasks) : null,
        max_tokens: form.max_tokens ? Number(form.max_tokens) : null,
      } })
    } catch (ex) { setErr(ex.message) }
    setRefresh((r) => r + 1)
  }
  const doRevoke = async (subsystem) => {
    setErr(null)
    try { await api(`/arming/${subsystem}`, { method: 'DELETE' }) } catch (ex) { setErr(ex.message) }
    setRefresh((r) => r + 1)
  }
  const row = (sub) => {
    const c = data?.contracts?.[sub] || { live: false }
    const env = data?.env?.[sub]
    return (
      <div key={sub} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '5px 0', flexWrap: 'wrap' }}>
        <span style={{ minWidth: 80 }}>{sub}</span>
        <span className={`pill ${env ? 'done' : ''}`} title="NOIRDECK_*_ARMED env master flag">
          env {env ? 'on' : 'off'}
        </span>
        {c.live ? (
          <>
            <span className="chip hot">armed until {new Date(c.armed_until).toLocaleString()}</span>
            <span className="faint">
              tasks {c.used_tasks}{c.max_tasks ? `/${c.max_tasks}` : ''} ·
              tokens {(c.used_tokens || 0).toLocaleString()}{c.max_tokens ? `/${c.max_tokens.toLocaleString()}` : ''}
            </span>
            <button className="act ghost" onClick={() => doRevoke(sub)}>disarm</button>
          </>
        ) : (
          <>
            <span className="faint">{c.armed_until && !c.revoked_at ? 'contract expired/spent' : 'disarmed'}</span>
            <button className="act ghost" onClick={() => doArm(sub)}>arm</button>
          </>
        )}
      </div>
    )
  }
  return (
    <div className="panel">
      <h2>Arming — <b>contract, not a switch</b></h2>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 8 }}>
        <div><label className="fl" htmlFor="arm-hours">Hours</label>
          <input id="arm-hours" style={{ width: 70 }} value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} /></div>
        <div><label className="fl" htmlFor="arm-max-tasks">Max tasks</label>
          <input id="arm-max-tasks" style={{ width: 80 }} value={form.max_tasks} onChange={(e) => setForm({ ...form, max_tasks: e.target.value })} placeholder="∞" /></div>
        <div><label className="fl" htmlFor="arm-max-tokens">Max tokens out</label>
          <input id="arm-max-tokens" style={{ width: 110 }} value={form.max_tokens} onChange={(e) => setForm({ ...form, max_tokens: e.target.value })} placeholder="∞" /></div>
        <span className="faint">arm uses these limits · runs need env flag AND a live contract</span>
      </div>
      {row('overnight')}
      {row('mining')}
      {err && <div className="err" role="alert">{err}</div>}
    </div>
  )
}

export default function Queue({ bump }) {
  const [refresh, setRefresh] = useState(0)
  const { data: tasks } = useData('/queue', bump + refresh)
  const [taskPage, taskPager] = usePager(tasks || [], 10)
  const { data: fleet } = useData('/fleet', bump)
  const [form, setForm] = useState({ project: '', title: '', prompt: '', weight: '' })
  const [answers, setAnswers] = useState({})
  const [err, setErr] = useState(null)

  const submit = async (e) => {
    e.preventDefault(); setErr(null)
    try {
      await api('/queue', { body: { ...form, weight: form.weight || null } })
      setForm({ project: form.project, title: '', prompt: '', weight: '' })
      setRefresh((r) => r + 1)
    } catch (ex) { setErr(ex.message) }
  }
  const act = async (path, body = {}) => {
    setErr(null)
    try { await api(path, { body }) } catch (ex) { setErr(ex.message) }
    setRefresh((r) => r + 1)
  }

  return (
    <>
      <div className="viewhead">
        <h1>Overnight queue</h1>
        <p>Tasks run autonomously via headless Claude — agent & model auto-routed, one at a time, token-capped.
          Anything it can't decide parks here as a question and the night moves on. It cannot push or
          deploy — a PreToolUse guard denies those at the harness level, and runs stop when the
          arming contract expires or its budget is spent.</p>
      </div>

      <ArmPanel bump={bump} />

      <div className="panel">
        <h2>Queue a task</h2>
        <form onSubmit={submit}>
          <label className="fl" htmlFor="queue-project">Project</label>
          <select id="queue-project" value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} required>
            <option value="">— choose repo —</option>
            {(fleet || []).map((f) => <option key={f.path} value={f.name}>{f.name}</option>)}
          </select>
          <label className="fl" htmlFor="queue-title">Title</label>
          <input id="queue-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required placeholder="e.g. Add retry/backoff to the Datto sync" />
          <label className="fl" htmlFor="queue-prompt">Task prompt</label>
          <textarea id="queue-prompt" rows={4} value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} required placeholder="What should the overnight session do? Be as specific as a good ticket." />
          <label className="fl" htmlFor="queue-weight">Effort</label>
          <select id="queue-weight" value={form.weight} style={{ maxWidth: 420 }}
            onChange={(e) => setForm({ ...form, weight: e.target.value })}>
            <option value="">auto — routed from the task text</option>
            <option value="light">light — one session, cheapest</option>
            <option value="heavy">heavy — plan first, then build, then a check pass</option>
          </select>
          <div style={{ marginTop: 10 }}><button className="act" type="submit">queue for tonight</button></div>
        </form>
        {err && <div className="err" role="alert">{err}</div>}
      </div>

      {taskPager && <div className="panel">{taskPager}</div>}
      {taskPage.map((t) => (
        <div className="panel" key={t.id}>
          <h2>#{t.id} — <b>{t.title}</b> <span className={`pill ${t.status}`}>{t.status}</span></h2>
          <div className="faint" style={{ marginBottom: 6 }}>
            {t.project.split('/').pop()} · model {t.model || 'auto'} · agent {t.agent_type || 'auto'}
            {t.weight ? ` · ${t.weight}${t.weight === 'heavy' ? ' (staged)' : ''}` : ''}
            {t.tokens_out ? ` · ${t.tokens_out.toLocaleString()} tok out` : ''}
          </div>
          {t.verdict && <div className="mono-block" style={{ maxHeight: 120 }}>{t.verdict}</div>}
          {t.status === 'blocked' && (
            <div style={{ marginTop: 8 }}>
              <div className="kickoff">Q: {t.question}</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <input placeholder="your answer — re-queues the task" value={answers[t.id] || ''}
                  aria-label={`Answer for task #${t.id}: ${t.title}`}
                  onChange={(e) => setAnswers({ ...answers, [t.id]: e.target.value })} />
                <button className="act" onClick={() => act(`/queue/${t.id}/answer`, { answer: answers[t.id] || '' })}>answer</button>
                <button className="act ghost" onClick={() => act(`/queue/${t.id}/cancel`)}>cancel</button>
              </div>
            </div>
          )}
          {t.status === 'queued' && (
            <div style={{ marginTop: 8 }}>
              <button className="act ghost" onClick={() => act(`/queue/${t.id}/cancel`)}>cancel</button>
            </div>
          )}
        </div>
      ))}
      {(tasks || []).length === 0 && <div className="panel"><div className="faint">queue is empty</div></div>}
    </>
  )
}
