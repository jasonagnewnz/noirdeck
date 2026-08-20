import { useEffect, useRef, useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ConfirmButton, ViewHead } from '../ui.jsx'

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
      await api('/arming', {
        body: {
          subsystem,
          hours: Number(form.hours) || 10,
          max_tasks: form.max_tasks ? Number(form.max_tasks) : null,
          max_tokens: form.max_tokens ? Number(form.max_tokens) : null,
        },
      })
    } catch (ex) {
      setErr(ex.message)
    }
    setRefresh((r) => r + 1)
  }
  const doRevoke = async (subsystem) => {
    setErr(null)
    try {
      await api(`/arming/${subsystem}`, { method: 'DELETE' })
    } catch (ex) {
      setErr(ex.message)
    }
    setRefresh((r) => r + 1)
  }
  const row = (sub) => {
    const c = data?.contracts?.[sub] || { live: false }
    const env = data?.env?.[sub]
    return (
      <div key={sub} className="ctlrow" style={{ padding: '5px 0' }}>
        <span style={{ minWidth: 80 }}>{sub}</span>
        <span className={`pill ${env ? 'done' : ''}`} title="NOIRDECK_*_ARMED env master flag">
          env {env ? 'on' : 'off'}
        </span>
        {c.live ? (
          <>
            <span className="chip hot">armed until {new Date(c.armed_until).toLocaleString()}</span>
            <span className="faint">
              tasks {c.used_tasks}
              {c.max_tasks ? `/${c.max_tasks}` : ''} · tokens {(c.used_tokens || 0).toLocaleString()}
              {c.max_tokens ? `/${c.max_tokens.toLocaleString()}` : ''}
            </span>
            <button type="button" className="act ghost" onClick={() => doRevoke(sub)}>
              disarm
            </button>
          </>
        ) : (
          <>
            <span className="faint">{c.armed_until && !c.revoked_at ? 'contract expired/spent' : 'disarmed'}</span>
            <button type="button" className="act ghost" onClick={() => doArm(sub)}>
              arm
            </button>
          </>
        )}
      </div>
    )
  }
  return (
    <details className="panel admin-fold">
      <summary>
        <span>Safety and spending controls</span>
        <b>contracts gate unattended work</b>
      </summary>
      <p className="sechint">
        Nothing runs unattended without a live contract: an expiry plus task and token budgets, double-gated with the
        env master flags. Contracts expire — re-arm here before tonight's run.
      </p>
      <div className="formrow" style={{ marginBottom: 8 }}>
        <div>
          <label className="fl" htmlFor="arm-hours">
            Hours
          </label>
          <input
            id="arm-hours"
            style={{ width: 70 }}
            value={form.hours}
            onChange={(e) => setForm({ ...form, hours: e.target.value })}
          />
        </div>
        <div>
          <label className="fl" htmlFor="arm-max-tasks">
            Max tasks
          </label>
          <input
            id="arm-max-tasks"
            style={{ width: 80 }}
            value={form.max_tasks}
            onChange={(e) => setForm({ ...form, max_tasks: e.target.value })}
            placeholder="∞"
          />
        </div>
        <div>
          <label className="fl" htmlFor="arm-max-tokens">
            Max tokens out
          </label>
          <input
            id="arm-max-tokens"
            style={{ width: 110 }}
            value={form.max_tokens}
            onChange={(e) => setForm({ ...form, max_tokens: e.target.value })}
            placeholder="∞"
          />
        </div>
        <span className="faint">these limits apply for as long as it stays on</span>
      </div>
      {row('overnight')}
      {row('mining')}
      {err && (
        <div className="err" role="alert">
          {err}
        </div>
      )}
    </details>
  )
}

export default function Queue({ bump, launch }) {
  const [refresh, setRefresh] = useState(0)
  const { data: tasks } = useData('/queue', bump + refresh)
  const [taskPage, taskPager] = usePager(tasks || [], 10)
  const { data: fleet } = useData('/fleet', bump)
  const { data: runtime } = useData('/workspace/runtimes', bump + refresh)
  const [form, setForm] = useState({ project: '', title: '', prompt: '', weight: '', runner: 'claude', model: '' })
  const [answers, setAnswers] = useState({})
  const [err, setErr] = useState(null)
  const [notice, setNotice] = useState(null)
  const defaultsLoaded = useRef(false)
  const launched = useRef(null)
  const runners = runtime?.runners || []
  const selectedRunner = runners.find((r) => r.id === form.runner)

  useEffect(() => {
    if (runtime?.defaults && !defaultsLoaded.current) {
      defaultsLoaded.current = true
      setForm((f) => ({ ...f, runner: runtime.defaults.runner || 'claude', model: runtime.defaults.model || '' }))
    }
  }, [runtime])

  useEffect(() => {
    if (launch?.view !== 'queue' || launched.current === launch.id) return
    launched.current = launch.id
    setForm((f) => ({
      ...f,
      project: launch.project || f.project,
      title: launch.title || launch.prompt || f.title,
      prompt: launch.prompt || f.prompt,
      runner: launch.runner || f.runner,
      model: launch.model || f.model,
    }))
  }, [launch])

  const submit = async (e) => {
    e.preventDefault()
    setErr(null)
    try {
      await api('/queue', { body: { ...form, weight: form.weight || null, model: form.model || null } })
      setForm({ ...form, project: form.project, title: '', prompt: '', weight: '' })
      setRefresh((r) => r + 1)
    } catch (ex) {
      setErr(ex.message)
    }
  }
  const act = async (path, body = {}) => {
    setErr(null)
    try {
      await api(path, { body })
    } catch (ex) {
      setErr(ex.message)
    }
    setRefresh((r) => r + 1)
  }

  // The consequence is printed beside the button, not inside a dialog. Confirming
  // is one inline click; the outcome (resumed conversation vs fresh session) is
  // reported after, where it is actually actionable.
  const takeOver = async (t) => {
    setErr(null)
    try {
      const out = await api(`/queue/${t.id}/takeover`)
      setNotice(
        out.resumed_conversation
          ? `Task #${t.id} is yours — its conversation is open in Build Live.`
          : `Task #${t.id} stopped, but no transcript was found: Build Live opened a FRESH session in the same repo, so its context did not carry over.`
      )
      window.location.hash = '#workspace'
    } catch (ex) {
      setErr(ex.message)
    }
    setRefresh((r) => r + 1)
  }

  return (
    <>
      <ViewHead
        title="Tasks"
        helpId="queue"
        hint="Send work off without opening a live session. Pick where, who, and how deep; anything uncertain comes back as a question."
      />

      <div className="panel">
        <h2>Run a task later</h2>
        <p className="sechint">
          Write the outcome like a good ticket. Choose a specific model only when the job needs one.
        </p>
        <form onSubmit={submit}>
          <div className="formrow">
            <div style={{ minWidth: 240 }}>
              <label className="fl" htmlFor="queue-project">
                Project
              </label>
              <select
                id="queue-project"
                value={form.project}
                onChange={(e) => setForm({ ...form, project: e.target.value })}
                required
              >
                <option value="">— choose project —</option>
                {(fleet || []).map((f) => (
                  <option key={f.path} value={f.name}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ minWidth: 210 }}>
              <label className="fl" htmlFor="queue-runner">
                Who
              </label>
              <select
                id="queue-runner"
                value={form.runner}
                onChange={(e) => setForm({ ...form, runner: e.target.value })}
              >
                {(runners.length ? runners : [{ id: 'claude', label: 'Claude Code' }]).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                    {r.queue_available === false ? ' (not found)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ minWidth: 220 }}>
              <label className="fl" htmlFor="queue-model">
                Model, optional
              </label>
              <input
                id="queue-model"
                list={`queue-models-${form.runner}`}
                value={form.model}
                placeholder={selectedRunner?.default_model ? `auto/default ${selectedRunner.default_model}` : 'auto'}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              />
              <datalist id={`queue-models-${form.runner}`}>
                {(selectedRunner?.models || []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
          </div>
          <label className="fl" htmlFor="queue-title">
            What
          </label>
          <input
            id="queue-title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            required
            placeholder="e.g. Add retry/backoff to the Datto sync"
          />
          <label className="fl" htmlFor="queue-prompt">
            Outcome
          </label>
          <textarea
            id="queue-prompt"
            rows={4}
            value={form.prompt}
            onChange={(e) => setForm({ ...form, prompt: e.target.value })}
            required
            placeholder="What should be different when this is done?"
          />
          <label className="fl" htmlFor="queue-weight">
            Depth
          </label>
          <select
            id="queue-weight"
            value={form.weight}
            style={{ maxWidth: 420 }}
            onChange={(e) => setForm({ ...form, weight: e.target.value })}
          >
            <option value="">auto — routed from the task text</option>
            <option value="light">light — one session, cheapest</option>
            <option value="heavy">heavy — plan first, then build, then a check pass</option>
          </select>
          <div style={{ marginTop: 10 }}>
            <button className="act" type="submit">
              run later
            </button>
          </div>
        </form>
        {err && (
          <div className="err" role="alert">
            {err}
          </div>
        )}
      </div>

      {/* Takeover reports its outcome here rather than in an alert(): whether the
          task's conversation carried over is the one thing you need to know, and it
          is only useful once the action has happened. */}
      {notice && (
        <div className="scanline" role="status">
          {notice}
        </div>
      )}

      <ArmPanel bump={bump} />

      {(tasks || []).length > 0 && (
        <div className="listhead">
          Later · <b>{(tasks || []).length}</b>
        </div>
      )}
      {taskPager && <div className="panel">{taskPager}</div>}
      {taskPage.map((t) => (
        <div className="panel" key={t.id}>
          <h2>
            #{t.id} — <b>{t.title}</b> <span className={`pill ${t.status}`}>{t.status}</span>
          </h2>
          <div className="faint" style={{ marginBottom: 6 }}>
            {t.project.split('/').pop()} · who {t.runner || 'claude'} · model {t.model || 'auto'} · path{' '}
            {t.agent_type || 'auto'}
            {t.weight ? ` · ${t.weight}${t.weight === 'heavy' ? ' (staged)' : ''}` : ''}
            {t.tokens_out ? ` · ${t.tokens_out.toLocaleString()} tok out` : ''}
          </div>
          {t.verdict && (
            <div className="mono-block" style={{ maxHeight: 120 }}>
              {t.verdict}
            </div>
          )}
          {t.status === 'blocked' && (
            <div style={{ marginTop: 8 }}>
              <div className="kickoff">Q: {t.question}</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <input
                  placeholder="your answer — re-queues the task"
                  value={answers[t.id] || ''}
                  aria-label={`Answer for task #${t.id}: ${t.title}`}
                  onChange={(e) => setAnswers({ ...answers, [t.id]: e.target.value })}
                />
                <button
                  type="button"
                  className="act"
                  onClick={() => act(`/queue/${t.id}/answer`, { answer: answers[t.id] || '' })}
                >
                  answer
                </button>
                <ConfirmButton
                  className="act ghost"
                  confirmLabel="Cancel it?"
                  onConfirm={() => act(`/queue/${t.id}/cancel`)}
                >
                  cancel
                </ConfirmButton>
              </div>
            </div>
          )}
          {t.status === 'queued' && (
            <div style={{ marginTop: 8 }}>
              <button type="button" className="act ghost" onClick={() => act(`/queue/${t.id}/cancel`)}>
                cancel
              </button>
            </div>
          )}
          {t.status === 'running' && (
            <div style={{ marginTop: 8 }}>
              <ConfirmButton confirmLabel="Stop the run and take it?" onConfirm={() => takeOver(t)}>
                Take over this task
              </ConfirmButton>
              <div className="faint" style={{ marginTop: 4 }}>
                Stops the unattended run now and opens its conversation in a terminal you can type into. Any turn still
                in progress is lost.
              </div>
            </div>
          )}
          {t.status === 'claimed' && (
            <div className="faint" style={{ marginTop: 8 }}>
              You took this over{t.claimed_at ? ` at ${t.claimed_at.slice(11, 16)}` : ''} — it is yours now, so the
              runner will not touch it again.
            </div>
          )}
        </div>
      ))}
      {(tasks || []).length === 0 && (
        <div className="panel">
          <div className="faint">nothing waiting to run later</div>
        </div>
      )}
    </>
  )
}
