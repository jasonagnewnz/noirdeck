import { useState } from 'react'
import { api, useData } from '../api.js'
import { ConfirmButton } from '../ui.jsx'

// Local models for someone who does not want to learn any of this.
//
// The whole panel obeys one rule: show ONE next step at a time. A settings screen
// that presents install, start, pull and configure simultaneously is how a person
// decides this feature is not for them. The backend decides which step is next
// (local_models._next_step); this just renders it and gets out of the way.
//
// Nothing destructive or expensive happens on a click alone: install downloads an
// executable and a pull is multiple gigabytes, so both confirm first and both say
// what they will cost before they do it.

export default function LocalModels({ bump }) {
  const [refresh, setRefresh] = useState(0)
  const { data, loading } = useData('/local-models', bump + refresh)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)
  const [msg, setMsg] = useState(null)
  const [showAll, setShowAll] = useState(false)

  const call = async (path, body, label) => {
    setBusy(label)
    setErr(null)
    setMsg(null)
    try {
      const out = await api(path, { body })
      if (out.performed === false && out.reason) setMsg(out.reason)
      else if (out.started === false && out.reason) setMsg(out.reason)
      else if (out.started) setMsg('Download started. It runs in the background: this page will show it when it lands.')
      else if (out.performed) setMsg(`Installed ${out.version ? `version ${out.version}` : 'successfully'}.`)
      else setMsg('Done.')
    } catch (e) {
      setErr(e.message)
    }
    setBusy(null)
    setRefresh((r) => r + 1)
  }

  if (loading) return <div className="loading">checking what this machine can run</div>
  if (!data) return null

  const { state: st, recommendations: recs, install_plan: plan, next_step: step } = data

  //These were two multi-sentence window.confirm dialogs: mine, written the day
  // before. The cost of each action (a download size, "no admin rights needed") now
  // sits in the panel where it is read BEFORE the click; the click itself is an
  // inline Yes/No. A paragraph inside a modal is not informed consent, it is a
  // paragraph nobody reads.
  const doStep = () => {
    if (step.action === 'install') call('/local-models/install', { confirm: true }, 'install')
    else if (step.action === 'serve') call('/local-models/serve', {}, 'serve')
    else if (step.action === 'pull' && step.tag) pull(recs.start_with)
  }

  const pull = (entry) => {
    if (!entry) return
    call('/local-models/pull', { tag: entry.tag, confirm: true }, `pull:${entry.tag}`)
  }

  return (
    <div className="panel">
      <h2>Local models</h2>
      <p className="sechint">
        A model that runs on this machine instead of a service. Slower and less capable than the hosted ones, and
        nothing you send it leaves your computer: which is the point. Used for the background improvement pass and
        available as a helper in Build Live.
      </p>

      {/* One step, stated plainly, with the reason it is the next one. */}
      <div className={`localmodel-step${step.action === 'ready' ? ' is-ready' : ''}`}>
        <div>
          <b>{step.headline}</b>
          <div className="dim">{step.detail}</div>
        </div>
        {step.action !== 'ready' && (
          <ConfirmButton
            className="act work-go"
            confirmLabel={step.action === 'install' ? 'Download and install?' : 'Start the download?'}
            disabled={!!busy || (step.action === 'install' && !plan.supported)}
            onConfirm={doStep}
          >
            {busy
              ? 'Working…'
              : step.action === 'install'
                ? 'Set it up'
                : step.action === 'serve'
                  ? 'Start it'
                  : `Download it${recs.start_with ? ` (${recs.start_with.download_gb} GB)` : ''}`}
          </ConfirmButton>
        )}
      </div>

      {step.action === 'install' && !plan.supported && (
        <div className="err" role="alert">
          There is no official Ollama build for this machine's processor type ({plan.arch}), so this cannot install it
          for you.
        </div>
      )}

      {msg && <div className="scanline">{msg}</div>}
      {err && (
        <div className="err" role="alert">
          {err}
        </div>
      )}

      {/* What this machine actually is. Stated because every recommendation below
          depends on it, and a recommendation whose basis is hidden is just an
          assertion. */}
      <div className="faint" style={{ marginTop: 10 }}>
        This machine: {recs.basis}.
        {st.installed
          ? ` Ollama ${st.version || ''} installed${st.user_local ? ' in your home folder' : ''}, server ${
              st.server_running ? 'running' : 'not running'
            }.`
          : ' Ollama is not installed.'}
      </div>

      {st.installed && st.server_running && st.models.length > 0 && (
        <>
          <div className="listhead">On this machine</div>
          {st.models.map((m) => (
            <div key={m.name} className="localmodel-row">
              <code>{m.name}</code>
              <span className="dim">{m.size_gb ? `${m.size_gb} GB` : ''}</span>
            </div>
          ))}
        </>
      )}

      {st.installed && st.server_running && (
        <>
          <div className="listhead">
            Suggested for your work
            <span className="dim">: you mostly work on {recs.work_kind === 'code' ? 'code' : 'a mix of things'}</span>
          </div>
          {(showAll ? recs.fits : recs.fits.slice(0, 3)).map((e) => (
            <div key={e.tag} className="localmodel-card">
              <div className="localmodel-card-head">
                <b>{e.label}</b>
                <code className="dim">{e.tag}</code>
                {e.already_pulled && <span className="chip">already here</span>}
              </div>
              <div className="dim">{e.good_for}</div>
              <div className="faint">{e.note}</div>
              {!e.already_pulled && (
                <ConfirmButton
                  className="act ghost"
                  confirmLabel={`Download ${e.download_gb} GB?`}
                  disabled={!!busy}
                  onConfirm={() => pull(e)}
                >
                  {busy === `pull:${e.tag}` ? 'Starting…' : `Download (${e.download_gb} GB)`}
                </ConfirmButton>
              )}
            </div>
          ))}
          {recs.fits.length > 3 && (
            <button type="button" className="act ghost" onClick={() => setShowAll((s) => !s)}>
              {showAll ? 'Show fewer' : `Show all ${recs.fits.length} that fit`}
            </button>
          )}

          {/* Shown, not hidden: knowing why something is absent prevents the
              "why isn't the good one listed" question, and prevents someone
              pulling a model that will swap and feel broken. */}
          {recs.out_of_reach.length > 0 && (
            <details className="work-advanced">
              <summary>
                Too big for this machine<span className="dim">: {recs.out_of_reach.length} not offered</span>
              </summary>
              {recs.out_of_reach.map((e) => (
                <div key={e.tag} className="localmodel-row">
                  <span>
                    <b>{e.label}</b> <code className="dim">{e.tag}</code>
                  </span>
                  <span className="faint">{e.note}</span>
                </div>
              ))}
            </details>
          )}
        </>
      )}

      {!st.installed && plan.supported && (
        <details className="work-advanced">
          <summary>
            What &ldquo;set it up&rdquo; will do<span className="dim">: no admin rights needed</span>
          </summary>
          <ol className="localmodel-steps">
            {plan.steps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
          <p className="faint">{plan.why_not_the_official_script}</p>
          {plan.manual_command && (
            <>
              <p className="faint">Or run this yourself in a terminal: it does exactly the same thing:</p>
              <pre className="finding-context">{plan.manual_command}</pre>
            </>
          )}
        </details>
      )}
    </div>
  )
}
