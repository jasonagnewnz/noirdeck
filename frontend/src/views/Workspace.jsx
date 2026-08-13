import React, { useEffect, useRef, useState } from 'react'
import { api, useData } from '../api.js'
import { getJSON } from '../ide/ideApi.js'
import TermPane from '../ide/TermPane.jsx'
import FileExplorer from '../ide/FileExplorer.jsx'
import FileViewer from '../ide/FileViewer.jsx'
import ActionsBar from '../ide/ActionsBar.jsx'

export default function Workspace({ launch }) {
  const { data: fleet } = useData('/fleet', 0)
  const [sessions, setSessions] = useState([])
  const [active, setActive] = useState(null)
  const [project, setProject] = useState('')
  const [briefing, setBriefing] = useState(true)
  const [newRepo, setNewRepo] = useState('')
  const [err, setErr] = useState(null)
  const [fileTabs, setFileTabs] = useState([])
  const [injections, setInjections] = useState({})
  const [actionBusy, setActionBusy] = useState(false)
  const [explorerCollapsed, setExplorerCollapsed] = useState(false)
  const launched = useRef(null)

  const refresh = async () => {
    const rows = await api('/workspace')
    setSessions(rows)
    return rows
  }
  // on load, pick up an existing session's project so the IDE shell (explorer,
  // actions strip) has context even before the user touches the picker
  useEffect(() => {
    refresh().then((rows) => { if (rows.length && !project) setProject(rows[0].project) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const start = async (body) => {
    setErr(null)
    try {
      const r = await api('/workspace', { body })
      await refresh()
      setActive(r.id)
      return r
    } catch (e) { setErr(e.message); throw e }
  }

  // resume handed over from the Sessions view
  useEffect(() => {
    if (launch && launched.current !== launch) {
      launched.current = launch
      setProject(launch.project)
      start({ project: launch.project, resume_session_id: launch.resume })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [launch])

  const stop = async (sid) => {
    try { await fetch(`/api/workspace/${sid}`, { method: 'DELETE' }) } catch { /* gone */ }
    await refresh()
    if (active === sid) setActive(null)
  }

  const createRepo = async () => {
    setErr(null)
    try {
      await api('/workspace/repo', { body: { name: newRepo } })
      setProject(newRepo)
      setNewRepo('')
    } catch (e) { setErr(e.message) }
  }

  const openFileTab = async (entry) => {
    const id = `file:${project}:${entry.path}`
    if (fileTabs.some((t) => t.id === id)) { setActive(id); return }
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
      const r = await start({ project, briefing: false })
      setInjections((m) => ({ ...m, [r.id]: action.live }))
    } finally {
      setActionBusy(false)
    }
  }

  const queueOvernight = async (action) => {
    setErr(null)
    try {
      await api('/queue', { body: { project, title: action.label, prompt: action.overnight } })
    } catch (e) { setErr(e.message); throw e }
  }

  const activeSession = sessions.find((s) => s.id === active)
  const activeFile = fileTabs.find((t) => t.id === active)

  return (
    <>
      <div className="viewhead">
        <h1>Workspace</h1>
        <p>Real Claude Code sessions inside the platform — same auth, same skills, same memory.
          "With briefing" starts the session already knowing the project state.</p>
      </div>

      <div className="panel">
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 240 }}>
            <label className="fl" htmlFor="ws-project">Project</label>
            <select id="ws-project" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">— choose repo —</option>
              {(fleet || []).map((f) => <option key={f.path} value={f.name}>{f.name}</option>)}
            </select>
          </div>
          <label htmlFor="ws-briefing" style={{ display: 'flex', gap: 6, alignItems: 'center', paddingBottom: 7 }}>
            <input id="ws-briefing" type="checkbox" style={{ width: 'auto' }} checked={briefing}
              onChange={(e) => setBriefing(e.target.checked)} />
            <span className="dim">with briefing</span>
          </label>
          <button className="act" disabled={!project}
            onClick={() => start({ project, briefing })}>launch session</button>
          <span className="faint">or</span>
          <div style={{ minWidth: 200 }}>
            <label className="fl" htmlFor="ws-new-repo">New repo</label>
            <input id="ws-new-repo" value={newRepo} placeholder="name-of-new-project"
              onChange={(e) => setNewRepo(e.target.value)} />
          </div>
          <button className="act ghost" disabled={!newRepo} onClick={createRepo}>git init</button>
        </div>
        {err && <div className="err" role="alert">{err}</div>}
      </div>

      {project ? (
        <div className="ide">
          <FileExplorer project={project} onOpenFile={openFileTab}
            collapsed={explorerCollapsed} onToggleCollapse={() => setExplorerCollapsed((v) => !v)} />
          <div className="ide-main">
            <ActionsBar project={project} onLive={startLiveAction} onOvernight={queueOvernight} busy={actionBusy} />

            {(sessions.length > 0 || fileTabs.length > 0) && (
              <div className="tabstrip">
                {sessions.map((s) => (
                  // two sibling buttons, not a clickable span wrapping a nested button —
                  // <button> cannot contain another interactive element
                  <span key={s.id} className={`termtab ${active === s.id ? 'on' : ''}`}>
                    <button type="button" className="termtab-select"
                      aria-current={active === s.id ? 'true' : undefined}
                      onClick={() => { setActive(s.id); setProject(s.project) }}>
                      {s.project}{s.resumed ? ' (resumed)' : ''}
                    </button>
                    <button className="x" aria-label={`Close session tab: ${s.project}`}
                      onClick={(e) => { e.stopPropagation(); stop(s.id) }}>×</button>
                  </span>
                ))}
                {fileTabs.map((t) => (
                  <span key={t.id} className={`termtab filetab ${active === t.id ? 'on' : ''}`}>
                    <button type="button" className="termtab-select" title={`${t.project}/${t.path}`}
                      aria-current={active === t.id ? 'true' : undefined}
                      onClick={() => setActive(t.id)}>
                      {t.name}
                    </button>
                    <button className="x" aria-label={`Close file tab: ${t.name}`}
                      onClick={(e) => { e.stopPropagation(); closeFileTab(t.id) }}>×</button>
                  </span>
                ))}
              </div>
            )}

            <div className="tabbody">
              {activeSession && <TermPane key={activeSession.id} sid={activeSession.id} injectPrompt={injections[activeSession.id]} />}
              {activeFile && <FileViewer key={activeFile.id} tab={activeFile} />}
              {!activeSession && !activeFile && (
                <div className="tabbody-empty">
                  <div className="faint">no tab open — launch a session above, run an action, or open a file from the explorer</div>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="panel"><div className="faint">choose a project above to open its explorer and sessions</div></div>
      )}
    </>
  )
}
