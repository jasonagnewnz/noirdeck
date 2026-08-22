import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'
import GuidedCard, { FRIENDLY, STEPS } from './guided/GuidedCard.jsx'
import GuidedIntake from './guided/GuidedIntake.jsx'

// Attention-first ordering: things waiting on the operator, then things moving,
// then the rest: a returning user's question is always "does anything need me?"
const RANK = { awaiting_plan: 0, blocked: 0, attention: 0, running: 1, queued: 1 }
const sortBuilds = (builds) => [...builds].sort((a, b) => (RANK[a.status] ?? 2) - (RANK[b.status] ?? 2) || b.id - a.id)

// A phase can log several attempts (failed tries then the successful one):
// judge it by its best outcome, not its first attempt.
const phaseOutcome = (log, phase) => {
  const entries = log.filter((l) => l.phase === phase)
  if (!entries.length) return null
  return entries.find((l) => l.status === 'done') || entries[entries.length - 1]
}

const fmtMin = (s) => (s < 90 ? `${s}s` : `${Math.round(s / 60)}m`)

// Stepper for a non-gated (expert) build: same visual language as the guided
// card: quiet ✓ chips for done, a live pill for the active phase, dashed chips
// for not-yet.
function PhaseStepper({ b }) {
  return (
    <ul aria-label="Build progress" className="stepper">
      {STEPS.map(([key]) => {
        const entry = phaseOutcome(b.log, key)
        if (entry && entry.status === 'done') {
          return (
            <li key={key} className="chip" aria-label={`${key}: finished`}>
              ✓ {key} {fmtMin(entry.seconds)}
            </li>
          )
        }
        if (b.phase === key && b.status === 'running') {
          return (
            <li key={key} className="pill running" aria-label={`${key}: happening now`}>
              {key}…
            </li>
          )
        }
        if (entry) {
          return (
            <li key={key} className="pill blocked" aria-label={`${key}: stuck`}>
              {key}: stuck
            </li>
          )
        }
        return (
          <li key={key} className="chip pending" aria-label={`${key}: not started yet`}>
            {key}
          </li>
        )
      })}
      {b.tokens_out > 0 && <span className="faint">{(b.tokens_out / 1000).toFixed(0)}k tok</span>}
    </ul>
  )
}

// Try-it preview: if a finished build produced a static web entry point, let the
// operator USE it right here. The iframe is sandboxed (no same-origin), so the
// previewed code has no authority over the noirdeck API.
function TryIt({ b }) {
  const finished = b.status === 'done' || b.status === 'attention'
  const [inf, setInf] = useState(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!finished) return undefined
    let alive = true
    api(`/preview-info/${b.name}`)
      .then((d) => alive && setInf(d))
      .catch(() => {
        /* non-web build: no preview, no noise */
      })
    return () => {
      alive = false
    }
  }, [finished, b.name])
  if (!finished || !inf?.available) return null
  return (
    <div style={{ marginTop: 10 }}>
      <button type="button" className="act" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? 'close the preview' : 'try it: see it working'}
      </button>
      {open && (
        <iframe
          className="tryit"
          sandbox="allow-scripts"
          title={`Preview of ${b.name}`}
          src={`/api/preview/${b.name}/`}
        />
      )}
    </div>
  )
}

function ExpertCard({ b, refresh, openWorkspace }) {
  const [open, setOpen] = useState(false)
  const [statusText, pillClass] = FRIENDLY[b.status] || [b.status, b.status]
  const cancel = async () => {
    await api(`/builds/${b.id}/cancel`, { body: {} })
    refresh()
  }
  const resume = async () => {
    await api(`/builds/${b.id}/resume`, { body: {} })
    refresh()
  }
  return (
    <>
      <h2>
        #{b.id}: <b>{b.name}</b> <span className={`pill ${pillClass}`}>{statusText}</span>
      </h2>
      <PhaseStepper b={b} />
      {b.question && <div className="kickoff">The builder asks: {b.question}</div>}
      <div className="btnrow">
        <button type="button" className="act ghost" onClick={() => setOpen(!open)}>
          {open ? 'hide log' : 'phase log'}
        </button>
        <button type="button" className="act ghost" onClick={() => openWorkspace({ project: b.name })}>
          open in workspace
        </button>
        {(b.status === 'running' || b.status === 'queued') && (
          <button type="button" className="act ghost" onClick={cancel}>
            stop this build
          </button>
        )}
        {(b.status === 'blocked' || b.status === 'cancelled' || b.status === 'attention') && (
          <button type="button" className="act" onClick={resume}>
            continue this build
          </button>
        )}
      </div>
      {open && (
        <div className="mono-block" style={{ marginTop: 8 }}>
          {b.log
            .map((l) => `[${l.phase} · ${l.model} · ${l.seconds}s · qa:${l.qa_overall}]\n${l.summary}\n\n`)
            .join('') || 'no phases completed yet'}
        </div>
      )}
    </>
  )
}

export default function Builds({ openWorkspace }) {
  const [builds, setBuilds] = useState(null)
  const [mode, setMode] = useState('guided') // guided (default) | expert
  const [intakeOpen, setIntakeOpen] = useState(null) // null = auto: open only when no builds yet
  const [form, setForm] = useState({ name: '', prompt: '' })
  const [err, setErr] = useState(null)
  const sorted = sortBuilds(builds || [])
  const [buildPage, buildPager] = usePager(sorted, 10)

  const refresh = async () => {
    try {
      setBuilds(await api('/builds'))
    } catch {
      /* transient; next poll retries */
    }
  }
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [])

  const showIntake = intakeOpen ?? (builds !== null && builds.length === 0)
  const needsYou = sorted.filter((b) => (RANK[b.status] ?? 2) === 0).length
  const active = sorted.filter((b) => (RANK[b.status] ?? 2) === 1).length

  const start = async (e) => {
    e.preventDefault()
    setErr(null)
    try {
      await api('/builds', { body: form })
      setForm({ name: '', prompt: '' })
      setIntakeOpen(false)
      await refresh()
    } catch (ex) {
      setErr(ex.message)
    }
  }

  const onGuidedCreated = async (id) => {
    setIntakeOpen(false)
    await refresh()
    requestAnimationFrame(() => {
      document.getElementById(`build-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  return (
    <>
      <ViewHead
        title="Builds"
        helpId="builds"
        hint="Describe what you want and it gets built for you: a plan you approve first, then the code is written, tested and double-checked by a second reviewer: with plain proof of what was done at the end. Nothing ships without you."
      />

      <div className="panel toolbar">
        <button type="button" className="act" aria-expanded={showIntake} onClick={() => setIntakeOpen(!showIntake)}>
          {showIntake ? 'close' : '+ start a build'}
        </button>
        {builds !== null && builds.length > 0 && (
          <span className="dim">
            {builds.length} build{builds.length === 1 ? '' : 's'}
            {needsYou > 0 && (
              <>
                {' '}
                ·{' '}
                <b className="attn">
                  {needsYou} need{needsYou === 1 ? 's' : ''} you
                </b>
              </>
            )}
            {active > 0 && <> · {active} in progress</>}
          </span>
        )}
      </div>

      {showIntake && (
        <div className="panel">
          <h2>Start a build</h2>
          <p className="sechint">
            Guided asks a few plain-English questions and parks at a plan for your approval before any code is written;
            Expert takes a full written brief and runs straight through.
          </p>
          <div role="group" aria-label="How would you like to start" className="btnrow" style={{ marginBottom: 4 }}>
            <button
              type="button"
              className={mode === 'guided' ? 'act' : 'act ghost'}
              aria-pressed={mode === 'guided'}
              onClick={() => setMode('guided')}
            >
              Guided: answer a few questions
            </button>
            <button
              type="button"
              className={mode === 'expert' ? 'act' : 'act ghost'}
              aria-pressed={mode === 'expert'}
              onClick={() => setMode('expert')}
            >
              Expert: write the brief yourself
            </button>
          </div>

          <div className="form-col">
            {mode === 'guided' ? (
              <GuidedIntake onCreated={onGuidedCreated} />
            ) : (
              <>
                <form onSubmit={start}>
                  <label className="fl" htmlFor="build-name">
                    New repo name
                  </label>
                  <input
                    id="build-name"
                    value={form.name}
                    required
                    placeholder="my-new-product"
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                  />
                  <label className="fl" htmlFor="build-prompt">
                    The full brief: write it like a proper product spec
                  </label>
                  <textarea
                    id="build-prompt"
                    rows={7}
                    value={form.prompt}
                    required
                    placeholder="What it is, who it's for, the features, the data it holds, how you'll know it works. The more complete the brief, the fewer assumptions the pipeline logs."
                    onChange={(e) => setForm({ ...form, prompt: e.target.value })}
                  />
                  <div style={{ marginTop: 10 }}>
                    <button className="act" type="submit">
                      Build it
                    </button>
                  </div>
                </form>
                {err && (
                  <div className="err" role="alert">
                    {err}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {sorted.length > 0 && (
        <div className="listhead">
          Your builds · <b>{sorted.length}</b>{' '}
          <span className="faint" style={{ textTransform: 'none', letterSpacing: 0 }}>
            : the ones needing you first
          </span>
        </div>
      )}
      {buildPage.map((b) => (
        <div className="panel" key={b.id} id={`build-${b.id}`}>
          {b.gated ? (
            <GuidedCard b={b} refresh={refresh} openWorkspace={openWorkspace} />
          ) : (
            <ExpertCard b={b} refresh={refresh} openWorkspace={openWorkspace} />
          )}
          <TryIt b={b} />
        </div>
      ))}
      {buildPager && <div className="panel">{buildPager}</div>}
      {builds !== null && builds.length === 0 && !showIntake && (
        <div className="panel">
          <div className="faint">No builds yet: press “+ start a build” above.</div>
        </div>
      )}
    </>
  )
}
