import React, { useState } from 'react'
import { ACTIONS } from './prompts.js'

// Actions strip for the currently open project — a "live" run (opens a fresh
// terminal session and pastes the prompt in) and a ghost "overnight" run
// (queues it for the unattended runner). onLive/onOvernight are wired by the
// parent Workspace view to the real POST /api/workspace and POST /api/queue.
export default function ActionsBar({ project, onLive, onOvernight, busy }) {
  const [flash, setFlash] = useState(null)

  const runOvernight = async (action) => {
    try {
      await onOvernight(action)
      setFlash(`queued: ${action.label}`)
      setTimeout(() => setFlash(null), 3000)
    } catch { /* parent surfaces the error */ }
  }

  return (
    <div className="actionsbar">
      <span className="actionsbar-label">{project}</span>
      <span className="actionsbar-buttons">
        {ACTIONS.map((a) => (
          <span key={a.key} className="actionsbar-pair">
            <button className="act" disabled={busy} onClick={() => onLive(a)}>{a.label}</button>
            <button className="act ghost sm" disabled={busy} title={`Queue "${a.label}" for the overnight runner`}
              onClick={() => runOvernight(a)}>overnight</button>
          </span>
        ))}
      </span>
      {flash && <span className="actionsbar-flash" role="status" aria-live="polite">{flash}</span>}
    </div>
  )
}
