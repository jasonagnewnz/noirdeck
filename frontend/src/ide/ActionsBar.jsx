import { useState } from 'react'
import { ACTIONS } from './prompts.js'

// Actions strip for the currently open project — a "live" run (opens a fresh
// terminal session and pastes the prompt in) and a ghost "later" run
// (queues it for unattended work). onLive/onOvernight are wired by the
// parent Workspace view to the real POST /api/workspace and POST /api/queue.
export default function ActionsBar({ project, runtime, model, onLive, onOvernight, busy }) {
  const [flash, setFlash] = useState(null)

  const runOvernight = async (action) => {
    try {
      await onOvernight(action)
      setFlash(`runs later: ${action.label}`)
      setTimeout(() => setFlash(null), 3000)
    } catch {
      /* parent surfaces the error */
    }
  }

  return (
    <div className="actionsbar">
      <span className="actionsbar-label">
        {project} · {runtime || 'Claude Code'}
        {model ? ` · ${model}` : ''}
      </span>
      <span className="actionsbar-buttons">
        {ACTIONS.map((a) => (
          <span key={a.key} className="actionsbar-pair">
            <button type="button" className="act" disabled={busy} onClick={() => onLive(a)}>
              {a.label}
            </button>
            <button
              type="button"
              className="act ghost sm"
              disabled={busy}
              title={`Run "${a.label}" later`}
              onClick={() => runOvernight(a)}
            >
              later
            </button>
          </span>
        ))}
      </span>
      {flash && (
        <span className="actionsbar-flash" role="status" aria-live="polite">
          {flash}
        </span>
      )}
    </div>
  )
}
