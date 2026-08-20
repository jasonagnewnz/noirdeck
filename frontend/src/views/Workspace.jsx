import { useCallback, useEffect, useRef, useState } from 'react'
import { api, useData } from '../api.js'
import ActionsBar from '../ide/ActionsBar.jsx'
import ConsultPanel from '../ide/ConsultPanel.jsx'
import FileExplorer from '../ide/FileExplorer.jsx'
import FileViewer from '../ide/FileViewer.jsx'
import { getJSON } from '../ide/ideApi.js'
import TermPane from '../ide/TermPane.jsx'
import { ConfirmButton } from '../ui.jsx'

const FOCUS_KEY = 'nd.workspace.focus'

export default function Workspace({ launch }) {
  const { data: fleet } = useData('/fleet', 0)
  const { data: runtime } = useData('/workspace/runtimes', 0)
  const [sessions, setSessions] = useState([])
  const [paused, setPaused] = useState([])
  const [active, setActive] = useState(null)
  const [project, setProject] = useState('')
  const [briefing, setBriefing] = useState(true)
  const [runner, setRunner] = useState('claude')
  const [model, setModel] = useState('')
  const [sourceRunner, setSourceRunner] = useState('claude')
  const [sourceModel, setSourceModel] = useState('')
  const [knowledge, setKnowledge] = useState(null)
  const [useKnowledge, setUseKnowledge] = useState(false)
  const [methodAdvisor, setMethodAdvisor] = useState(false)
  const [methodSuggestion, setMethodSuggestion] = useState(null)
  const [methodDismissed, setMethodDismissed] = useState(false)
  const [detached, setDetached] = useState({ title: '', prompt: '', weight: '' })
  const [takeover, setTakeover] = useState({ runner: '', model: '', closeSource: false })
  const [newRepo, setNewRepo] = useState('')
  const [err, setErr] = useState(null)
  const [notice, setNotice] = useState(null)
  const [fileTabs, setFileTabs] = useState([])
  const [injections, setInjections] = useState({})
  const [actionBusy, setActionBusy] = useState(false)
  const [taskBusy, setTaskBusy] = useState(false)
  const [takeoverBusy, setTakeoverBusy] = useState(false)
  const [methodBusy, setMethodBusy] = useState(false)
  const [explorerCollapsed, setExplorerCollapsed] = useState(false)
  // Focus mode hides the two setup panels so the terminal takes the whole page.
  // The panels are hidden in CSS, never unmounted — unmounting would throw away
  // whatever the user has already typed into the start and background forms.
  // Collapsed by DEFAULT. The setup panels are a wall of controls you need once
  // to start a session and never again; the terminal is what you came for.
  // Only an explicit '0' expands them — an absent preference means collapsed.
  const [focusMode, setFocusMode] = useState(() => {
    try {
      return localStorage.getItem(FOCUS_KEY) !== '0'
    } catch (_e) {
      return true
    }
  })
  const toggleFocus = useCallback(() => {
    setFocusMode((v) => {
      const next = !v
      try {
        localStorage.setItem(FOCUS_KEY, next ? '1' : '0')
      } catch (_e) {
        /* private mode — the preference just does not persist */
      }
      return next
    })
  }, [])
  const launched = useRef(null)
  const defaultsLoaded = useRef(false)

  const runners = runtime?.runners || []
  const selectedRunner = runners.find((r) => r.id === runner)
  const sourceRunnerMeta = runners.find((r) => r.id === sourceRunner)
  const activeSession = sessions.find((s) => s.id === active)
  const activeFile = fileTabs.find((t) => t.id === active)
  const takeoverRunner =
    takeover.runner || runners.find((r) => r.live && r.id !== activeSession?.runner)?.id || runner || 'claude'
  const selectedTakeoverRunner = runners.find((r) => r.id === takeoverRunner)

  useEffect(() => {
    if (runtime?.defaults && !defaultsLoaded.current) {
      defaultsLoaded.current = true
      setRunner(runtime.defaults.runner || 'claude')
      setModel(runtime.defaults.model || '')
      setSourceRunner(runtime.defaults.knowledge_source_runner || 'claude')
      setSourceModel(runtime.defaults.knowledge_source_model || '')
      setMethodAdvisor(!!runtime.defaults.method_advisor)
      setTakeover((t) => ({ ...t, runner: runtime.defaults.runner || 'claude' }))
    }
  }, [runtime])

  // biome-ignore lint/correctness/useExhaustiveDependencies: the selected project is the reset signal for method suggestions.
  useEffect(() => {
    setMethodDismissed(false)
    setMethodSuggestion(null)
  }, [project])

  useEffect(() => {
    if (!methodAdvisor || !project || methodDismissed) {
      setMethodSuggestion(null)
      setMethodBusy(false)
      return undefined
    }
    let alive = true
    const prompt = `${detached.title}\n${detached.prompt}`.trim()
    setMethodBusy(true)
    const timer = setTimeout(() => {
      api('/workspace/method', { body: { project, prompt } })
        .then((suggestion) => alive && setMethodSuggestion(suggestion))
        .catch(() => alive && setMethodSuggestion(null))
        .finally(() => alive && setMethodBusy(false))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [methodAdvisor, project, detached.title, detached.prompt, methodDismissed])

  const refresh = async () => {
    const rows = await api('/workspace')
    setSessions(rows)
    try {
      setPaused(await api('/workspace/paused'))
    } catch {
      setPaused([])
    }
    return rows
  }
  // on load, pick up an existing session's project so the IDE shell (explorer,
  // actions strip) has context even before the user touches the picker
  // biome-ignore lint/correctness/useExhaustiveDependencies: initial refresh seeds the project once on mount
  useEffect(() => {
    refresh().then((rows) => {
      if (rows.length && !project) setProject(rows[0].project)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const start = async (body) => {
    setErr(null)
    try {
      const r = await api('/workspace', { body })
      await refresh()
      setActive(r.id)
      return r
    } catch (e) {
      setErr(e.message)
      throw e
    }
  }

  // resume handed over from the Sessions view
  // biome-ignore lint/correctness/useExhaustiveDependencies: launch handoff should fire once per launch object
  useEffect(() => {
    if (launch && launched.current !== launch) {
      launched.current = launch
      if (launch.runner) setRunner(launch.runner)
      if (launch.model) setModel(launch.model)
      if (launch.project) setProject(launch.project)
      if (launch.resume) {
        start({
          project: launch.project,
          resume_session_id: launch.resume,
          runner: launch.runner || runner,
          model: launch.model || model || null,
        }).catch(() => {})
        return
      }
      if (launch.view === 'workspace' && launch.project) {
        start({
          project: launch.project,
          briefing,
          runner: launch.runner || runner,
          model: launch.model || model || null,
          knowledge_pack_id: useKnowledge && knowledge ? knowledge.id : null,
        })
          .then((session) => {
            if (launch.prompt) {
              setInjections((m) => ({ ...m, [session.id]: launch.prompt }))
            }
          })
          .catch(() => {})
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [launch, runner, model, briefing])

  const stop = async (sid) => {
    try {
      await fetch(`/api/workspace/${sid}`, { method: 'DELETE' })
    } catch {
      /* gone */
    }
    await refresh()
    if (active === sid) setActive(null)
  }

  // pause records the claude conversation id then stops the PTY — the machine
  // can be fully shut down and the conversation resumed later from this view
  const pause = async (sid) => {
    setErr(null)
    try {
      await api(`/workspace/${sid}/pause`, { body: {} })
      await refresh()
      if (active === sid) setActive(null)
    } catch (e) {
      setErr(e.message)
    }
  }

  const resumePaused = async (p) => {
    setErr(null)
    try {
      const r = await api(`/workspace/paused/${p.id}/resume`, { body: {} })
      setProject(p.project)
      await refresh()
      setActive(r.id)
    } catch (e) {
      setErr(e.message)
    }
  }

  // Discarding loses the ability to resume that transcript. The confirmation is
  // inline on the button (ConfirmButton) and the consequence is printed in the
  // panel caption, where it can be read before the click rather than inside it.
  const discardPaused = async (p) => {
    setErr(null)
    try {
      await api(`/workspace/paused/${p.id}`, { method: 'DELETE' })
      await refresh()
    } catch (e) {
      setErr(e.message)
    }
  }

  const createRepo = async () => {
    setErr(null)
    try {
      await api('/workspace/repo', { body: { name: newRepo } })
      setProject(newRepo)
      setNewRepo('')
    } catch (e) {
      setErr(e.message)
    }
  }

  const saveDefaults = async () => {
    setErr(null)
    setNotice(null)
    try {
      await api('/workspace/defaults', {
        body: {
          runner,
          model: model || null,
          knowledge_source_runner: sourceRunner,
          knowledge_source_model: sourceModel || null,
          method_advisor: methodAdvisor,
        },
      })
      setNotice('default tool saved')
    } catch (e) {
      setErr(e.message)
    }
  }

  const prepareKnowledgeFor = async ({
    project: targetProject,
    sourceRunner: fromRunner,
    sourceModel: fromModel,
    targetRunner,
    targetModel,
  }) => {
    if (!targetProject) return null
    setErr(null)
    setNotice(null)
    try {
      const pack = await api('/workspace/knowledge', {
        body: {
          project: targetProject,
          source_runner: fromRunner,
          source_model: fromModel || null,
          target_runner: targetRunner,
          target_model: targetModel || null,
        },
      })
      setKnowledge(pack)
      setUseKnowledge(true)
      setNotice(`handoff ready for ${pack.target_runner}`)
      return pack
    } catch (e) {
      setErr(e.message)
      return null
    }
  }

  const prepareKnowledge = () =>
    prepareKnowledgeFor({
      project,
      sourceRunner,
      sourceModel,
      targetRunner: runner,
      targetModel: model,
    })

  const useSuggestedMethod = async () => {
    if (!methodSuggestion) return
    setRunner(methodSuggestion.runner)
    setModel(methodSuggestion.model || '')
    setSourceRunner(methodSuggestion.source_runner || 'claude')
    setSourceModel(methodSuggestion.source_model || '')
    if (methodSuggestion.use_handoff) {
      await prepareKnowledgeFor({
        project,
        sourceRunner: methodSuggestion.source_runner || 'claude',
        sourceModel: methodSuggestion.source_model || '',
        targetRunner: methodSuggestion.runner,
        targetModel: methodSuggestion.model || '',
      })
    } else {
      setNotice(`method set to ${methodSuggestion.runner_label}`)
    }
  }

  const openFileTab = async (entry) => {
    const id = `file:${project}:${entry.path}`
    if (fileTabs.some((t) => t.id === id)) {
      setActive(id)
      return
    }
    setFileTabs((t) => [...t, { id, kind: 'file', project, path: entry.path, name: entry.name, loading: true }])
    setActive(id)
    try {
      const data = await getJSON(`/file/${project}?path=${encodeURIComponent(entry.path)}`)
      setFileTabs((t) => t.map((x) => (x.id === id ? { ...x, ...data, loading: false } : x)))
    } catch (e) {
      setFileTabs((t) => t.map((x) => (x.id === id ? { ...x, loading: false, error: e.message } : x)))
    }
  }

  const closeFileTab = (id) => {
    setFileTabs((t) => t.filter((x) => x.id !== id))
    if (active === id) setActive(null)
  }

  // project action strip: "live" opens a plain session and pastes the prompt
  // into the PTY once connected (see TermPane's injectPrompt); "overnight"
  // queues the same intent, phrased for an unattended run
  const startLiveAction = async (action) => {
    if (!project) return
    setActionBusy(true)
    try {
      const r = await start({ project, briefing: false, runner, model: model || null })
      const prompt = useKnowledge && knowledge ? `${knowledge.body}\n\nTASK:\n${action.live}` : action.live
      setInjections((m) => ({ ...m, [r.id]: prompt }))
    } finally {
      setActionBusy(false)
    }
  }

  const queueOvernight = async (action) => {
    setErr(null)
    try {
      await api('/queue', {
        body: {
          project,
          title: action.label,
          prompt: action.overnight,
          runner,
          model: model || null,
          knowledge_pack_id: useKnowledge && knowledge ? knowledge.id : null,
        },
      })
    } catch (e) {
      setErr(e.message)
      throw e
    }
  }

  const queueDetached = async (e) => {
    e.preventDefault()
    if (!project) return
    setTaskBusy(true)
    setErr(null)
    setNotice(null)
    try {
      await api('/queue', {
        body: {
          project,
          title: detached.title,
          prompt: detached.prompt,
          weight: detached.weight || null,
          runner,
          model: model || null,
          knowledge_pack_id: useKnowledge && knowledge ? knowledge.id : null,
        },
      })
      setDetached({ title: '', prompt: '', weight: '' })
      setNotice('run-later task ready')
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setTaskBusy(false)
    }
  }

  const takeoverActiveSession = async () => {
    if (!activeSession) return
    setTakeoverBusy(true)
    setErr(null)
    setNotice(null)
    try {
      const r = await api(`/workspace/${activeSession.id}/takeover`, {
        body: {
          runner: takeoverRunner,
          model: takeover.model || null,
          close_source: takeover.closeSource,
        },
      })
      setProject(r.project)
      await refresh()
      setActive(r.id)
      setNotice(`session taken over by ${r.runner}${r.model ? `/${r.model}` : ''}`)
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setTakeoverBusy(false)
    }
  }

  return (
    // Collapse only once a project is chosen. The picker lives inside the
    // collapsible deck, so collapsing with nothing selected would hide the only
    // control that can un-hide it.
    <div className={`workspace-view${focusMode && project ? ' is-focus' : ''}`}>
      <div className="viewhead work-collapsible">
        <h1>Build Live</h1>
        <p>Choose the project and helper. Switch tools without rebuilding context.</p>
      </div>

      <div className="panel work-deck work-collapsible">
        <div className="work-deck-head">
          <div>
            <h2>Start building</h2>
            <p className="sechint">Work live, run in the background, or hand off from another model.</p>
          </div>
          <span className="chip hot">
            {runners.length ? runners.filter((r) => r.live !== false).length : 1} tool
            {(runners.length ? runners.filter((r) => r.live !== false).length : 1) === 1 ? '' : 's'} ready
          </span>
        </div>
        {/* ⛔ This block used to be ONE row carrying eight controls at equal visual
            weight: project, helper, model, two checkboxes, "build with me",
            "remember", a new-project field and its button. The effect was that
            "pick a repo and start working" had no obvious single answer — the
            primary action looked like just another option. Primary path is now one
            field and one button; everything else is a closed disclosure. */}
        <div className="work-primary">
          <div className="work-primary-field">
            <label className="fl" htmlFor="ws-project">
              Project
            </label>
            <select id="ws-project" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">— choose project —</option>
              {(fleet || []).map((f) => (
                <option key={f.path} value={f.name}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>
          {/* The label names the repo once chosen, so the button says what it will
              actually do rather than leaving you to infer it. */}
          <button
            type="button"
            className="act work-go"
            disabled={!project || selectedRunner?.live === false}
            onClick={() =>
              start({
                project,
                briefing,
                runner,
                model: model || null,
                knowledge_pack_id: useKnowledge && knowledge ? knowledge.id : null,
              })
            }
          >
            {project ? `Start working on ${project}` : 'Choose a project above'}
          </button>
        </div>

        <details className="work-advanced">
          <summary>
            Options
            <span className="dim">
              {' — '}
              {selectedRunner?.ide_label || selectedRunner?.label || 'Claude'}
              {model ? `, ${model}` : ''}
              {briefing ? ', brief first' : ''}
            </span>
          </summary>
          <div className="formrow">
            <div style={{ minWidth: 210 }}>
              <label className="fl" htmlFor="ws-runner">
                Helper
              </label>
              <select id="ws-runner" value={runner} onChange={(e) => setRunner(e.target.value)}>
                {(runners.length ? runners : [{ id: 'claude', ide_label: 'Claude IDE', label: 'Claude Code' }]).map(
                  (r) => (
                    <option key={r.id} value={r.id}>
                      {r.ide_label || r.label}
                      {r.live === false ? ' (not found)' : ''}
                    </option>
                  )
                )}
              </select>
            </div>
            <div style={{ minWidth: 220 }}>
              <label className="fl" htmlFor="ws-model">
                Model, optional
              </label>
              <input
                id="ws-model"
                list={`ws-models-${runner}`}
                value={model}
                placeholder={selectedRunner?.default_model ? `default ${selectedRunner.default_model}` : 'tool default'}
                onChange={(e) => setModel(e.target.value)}
              />
              <datalist id={`ws-models-${runner}`}>
                {(selectedRunner?.models || []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
            <label htmlFor="ws-briefing" style={{ display: 'flex', gap: 6, alignItems: 'center', paddingBottom: 7 }}>
              <input
                id="ws-briefing"
                type="checkbox"
                style={{ width: 'auto' }}
                checked={briefing}
                onChange={(e) => setBriefing(e.target.checked)}
              />
              <span className="dim">brief first</span>
            </label>
            <label className="toggleline" htmlFor="ws-method-advisor">
              <input
                id="ws-method-advisor"
                type="checkbox"
                checked={methodAdvisor}
                onChange={(e) => setMethodAdvisor(e.target.checked)}
              />
              <span>suggest method</span>
            </label>
            <button type="button" className="act ghost" onClick={saveDefaults}>
              remember these
            </button>
          </div>
        </details>

        <details className="work-advanced">
          <summary>
            Start a brand-new project<span className="dim"> — creates the folder and git-inits it</span>
          </summary>
          <div className="formrow">
            <div style={{ minWidth: 200 }}>
              <label className="fl" htmlFor="ws-new-repo">
                New project name
              </label>
              <input
                id="ws-new-repo"
                value={newRepo}
                placeholder="name-of-new-project"
                onChange={(e) => setNewRepo(e.target.value)}
              />
            </div>
            <button type="button" className="act" disabled={!newRepo} onClick={createRepo}>
              create project
            </button>
          </div>
        </details>
        <div className="formrow work-handoff-row">
          <div style={{ minWidth: 210 }}>
            <label className="fl" htmlFor="ws-source-runner">
              Handoff from
            </label>
            <select id="ws-source-runner" value={sourceRunner} onChange={(e) => setSourceRunner(e.target.value)}>
              {(runners.length ? runners : [{ id: 'claude', label: 'Claude Code' }]).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <div style={{ minWidth: 220 }}>
            <label className="fl" htmlFor="ws-source-model">
              Source model, optional
            </label>
            <input
              id="ws-source-model"
              list={`ws-source-models-${sourceRunner}`}
              value={sourceModel}
              placeholder={
                sourceRunnerMeta?.default_model ? `default ${sourceRunnerMeta.default_model}` : 'source default'
              }
              onChange={(e) => setSourceModel(e.target.value)}
            />
            <datalist id={`ws-source-models-${sourceRunner}`}>
              {(sourceRunnerMeta?.models || []).map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </div>
          <button type="button" className="act ghost" disabled={!project} onClick={prepareKnowledge}>
            prepare handoff
          </button>
          {knowledge && (
            <label
              htmlFor="ws-use-knowledge"
              style={{ display: 'flex', gap: 6, alignItems: 'center', paddingBottom: 7 }}
            >
              <input
                id="ws-use-knowledge"
                type="checkbox"
                style={{ width: 'auto' }}
                checked={useKnowledge}
                onChange={(e) => setUseKnowledge(e.target.checked)}
              />
              <span className="dim">include handoff #{knowledge.id}</span>
            </label>
          )}
        </div>
        {methodAdvisor && project && !methodDismissed && (methodSuggestion || methodBusy) && (
          <div className="method-card" role="status" aria-live="polite">
            {methodSuggestion ? (
              <>
                <div className="method-card-main">
                  <span className="method-kicker">Memory + preferences</span>
                  <b>{methodSuggestion.title}</b>
                  <p>{methodSuggestion.question}</p>
                  <div className="method-reasons">
                    {methodSuggestion.reasons.map((reason) => (
                      <span key={reason}>{reason}</span>
                    ))}
                  </div>
                  {methodSuggestion.memory_hints.length > 0 && (
                    <div className="method-memory">
                      {methodSuggestion.memory_hints.slice(0, 4).map((hint) => (
                        <span className="chip" key={`${hint.namespace}:${hint.name}`} title={hint.description}>
                          {hint.name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="method-actions">
                  <button className="act" type="button" disabled={methodBusy} onClick={useSuggestedMethod}>
                    use method
                  </button>
                  <button className="act ghost" type="button" onClick={() => setMethodDismissed(true)}>
                    different
                  </button>
                </div>
              </>
            ) : (
              <span className="faint">checking previous methods…</span>
            )}
          </div>
        )}
        {selectedRunner?.live === false && (
          <div className="faint" style={{ marginTop: 8 }}>
            {selectedRunner.label} is configured, but its CLI is not on this machine yet.
          </div>
        )}
        {notice && (
          <div className="kickoff" role="status" style={{ marginTop: 8 }}>
            {notice}
          </div>
        )}
        {err && (
          <div className="err" role="alert">
            {err}
          </div>
        )}
        {paused.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <span className="dim">paused — survives shutdowns, resume any time: </span>
            {paused.map((p) => (
              <span key={p.id} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', marginRight: 10 }}>
                <span className="chip">{p.project}</span>
                <span className="faint">
                  {p.runner || 'claude'}
                  {p.model ? `/${p.model}` : ''}
                </span>
                <span className="faint">{(p.paused_at || '').slice(0, 16)}</span>
                <button type="button" className="act ghost sm" onClick={() => resumePaused(p)}>
                  resume
                </button>
                <ConfirmButton
                  className="act ghost sm"
                  confirmLabel="Discard? cannot be resumed after"
                  title={`Remove this paused ${p.project} session from the list. Nothing is killed — the process ended when it was paused — but its transcript can no longer be resumed.`}
                  onConfirm={() => discardPaused(p)}
                >
                  discard
                </ConfirmButton>
              </span>
            ))}
          </div>
        )}
      </div>

      {project && (
        <div className="panel work-detached work-collapsible">
          <h2>Run in the background</h2>
          <p className="sechint">Send code-ready work to the selected helper without keeping a live build open.</p>
          <form onSubmit={queueDetached}>
            <div className="formrow">
              <div style={{ minWidth: 240, flex: 1 }}>
                <label className="fl" htmlFor="ws-task-title">
                  What
                </label>
                <input
                  id="ws-task-title"
                  value={detached.title}
                  onChange={(e) => setDetached({ ...detached, title: e.target.value })}
                  required
                  placeholder="e.g. Add model picker to Work"
                />
              </div>
              <div style={{ minWidth: 210 }}>
                <label className="fl" htmlFor="ws-task-effort">
                  Depth
                </label>
                <select
                  id="ws-task-effort"
                  value={detached.weight}
                  onChange={(e) => setDetached({ ...detached, weight: e.target.value })}
                >
                  <option value="">auto</option>
                  <option value="light">light</option>
                  <option value="heavy">heavy staged</option>
                </select>
              </div>
              <button className="act" type="submit" disabled={taskBusy || !detached.title || !detached.prompt}>
                run later
              </button>
            </div>
            <label className="fl" htmlFor="ws-task-prompt">
              Outcome
            </label>
            <textarea
              id="ws-task-prompt"
              rows={3}
              value={detached.prompt}
              onChange={(e) => setDetached({ ...detached, prompt: e.target.value })}
              required
              placeholder="What should be different when this is done?"
            />
          </form>
        </div>
      )}

      {project && (
        <div className="work-focusbar">
          {focusMode && <span className="work-focusbar-title">{project}</span>}
          <button
            type="button"
            className="act ghost sm"
            onClick={toggleFocus}
            aria-pressed={focusMode}
            title={
              focusMode
                ? 'Show the start and background panels again'
                : 'Hide the setup panels and give the terminal the whole page'
            }
          >
            {focusMode ? 'show controls' : 'full-page terminal'}
          </button>
        </div>
      )}

      {project ? (
        <div className="ide">
          <FileExplorer
            project={project}
            onOpenFile={openFileTab}
            collapsed={explorerCollapsed}
            onToggleCollapse={() => setExplorerCollapsed((v) => !v)}
          />
          <div className="ide-main">
            <ActionsBar
              project={project}
              runtime={selectedRunner?.label || runner}
              model={model}
              onLive={startLiveAction}
              onOvernight={queueOvernight}
              busy={actionBusy}
            />

            {activeSession && (
              <div className="takeoverbar">
                <span className="takeoverbar-label">
                  {activeSession.runner || 'claude'}
                  {activeSession.model ? `/${activeSession.model}` : ''} active
                </span>
                <span className="faint">switch to</span>
                <select
                  className="takeover-select"
                  aria-label="Switch to tool"
                  value={takeoverRunner}
                  onChange={(e) => setTakeover({ ...takeover, runner: e.target.value })}
                >
                  {(runners.length ? runners : [{ id: 'claude', label: 'Claude Code', live: true }]).map((r) => (
                    <option key={r.id} value={r.id} disabled={r.live === false}>
                      {r.label}
                      {r.live === false ? ' (not found)' : ''}
                    </option>
                  ))}
                </select>
                <input
                  className="takeover-model"
                  list={`takeover-models-${takeoverRunner}`}
                  value={takeover.model}
                  placeholder={
                    selectedTakeoverRunner?.default_model ? `default ${selectedTakeoverRunner.default_model}` : 'model'
                  }
                  aria-label="Takeover model"
                  onChange={(e) => setTakeover({ ...takeover, model: e.target.value })}
                />
                <datalist id={`takeover-models-${takeoverRunner}`}>
                  {(selectedTakeoverRunner?.models || []).map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                <label className="takeover-close" htmlFor="takeover-close-source">
                  <input
                    id="takeover-close-source"
                    type="checkbox"
                    checked={takeover.closeSource}
                    onChange={(e) => setTakeover({ ...takeover, closeSource: e.target.checked })}
                  />
                  <span>close source</span>
                </label>
                <button
                  type="button"
                  className="act sm"
                  disabled={takeoverBusy || selectedTakeoverRunner?.live === false}
                  onClick={takeoverActiveSession}
                >
                  take over
                </button>
              </div>
            )}

            {(sessions.length > 0 || fileTabs.length > 0) && (
              <div className="tabstrip">
                {sessions.map((s) => (
                  // two sibling buttons, not a clickable span wrapping a nested button —
                  // <button> cannot contain another interactive element
                  <span key={s.id} className={`termtab ${active === s.id ? 'on' : ''}`}>
                    <button
                      type="button"
                      className="termtab-select"
                      aria-current={active === s.id ? 'true' : undefined}
                      onClick={() => {
                        setActive(s.id)
                        setProject(s.project)
                      }}
                      title={`${s.project} · ${s.runner || 'claude'}${s.model ? ` · ${s.model}` : ''}`}
                    >
                      {s.project}
                      {s.runner && s.runner !== 'claude' ? ` · ${s.runner}` : ''}
                      {s.resumed ? ' (resumed)' : ''}
                    </button>
                    <button
                      type="button"
                      className="x"
                      title="pause — safe to shut down, resume later"
                      aria-label={`Pause session: ${s.project} (survives shutdown)`}
                      onClick={(e) => {
                        e.stopPropagation()
                        pause(s.id)
                      }}
                    >
                      ⏸
                    </button>
                    <button
                      type="button"
                      className="x"
                      aria-label={`Close session tab: ${s.project}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        stop(s.id)
                      }}
                    >
                      ×
                    </button>
                  </span>
                ))}
                {fileTabs.map((t) => (
                  <span key={t.id} className={`termtab filetab ${active === t.id ? 'on' : ''}`}>
                    <button
                      type="button"
                      className="termtab-select"
                      title={`${t.project}/${t.path}`}
                      aria-current={active === t.id ? 'true' : undefined}
                      onClick={() => setActive(t.id)}
                    >
                      {t.name}
                    </button>
                    <button
                      type="button"
                      className="x"
                      aria-label={`Close file tab: ${t.name}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        closeFileTab(t.id)
                      }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="tabbody">
              {activeSession && (
                <TermPane key={activeSession.id} sid={activeSession.id} injectPrompt={injections[activeSession.id]} />
              )}
              {activeSession && (
                <ConsultPanel
                  key={`consult-${activeSession.id}`}
                  sessionId={activeSession.id}
                  runners={(runtime?.runners || []).filter((r) => r.available)}
                />
              )}
              {activeFile && <FileViewer key={activeFile.id} tab={activeFile} />}
              {!activeSession && !activeFile && (
                <div className="tabbody-empty">
                  <div className="faint">
                    no tab open — launch a session above, run an action, or open a file from the explorer
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="panel">
          <div className="faint">Choose a project to show files, live builds, and background controls.</div>
        </div>
      )}
    </div>
  )
}
