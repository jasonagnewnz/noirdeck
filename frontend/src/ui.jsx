import { useEffect, useRef, useState } from 'react'

// Every view opens with the same anatomy: what this page IS (title), what it
// DOES (one-sentence hint), and a jump to its chapter in the Help manual.
// The link is a plain hash href: App's hashchange listener switches the view
// and the Help view scrolls itself to the matching section.
export function ViewHead({ title, hint, helpId }) {
  return (
    <div className="viewhead">
      <div className="viewhead-row">
        <h1>{title}</h1>
        {helpId && (
          <a className="headlink" href={`#help:${helpId}`}>
            how this works →
          </a>
        )}
      </div>
      {hint && <p>{hint}</p>}
    </div>
  )
}

/**
 * A destructive action that confirms IN PLACE.
 *
 *Replaces window.confirm, of which this app had nine. A browser dialog is
 * unstyleable, blocks the whole page, and: the real problem: invites a wall of
 * explanatory text that nobody reads. One of ours ran to four sentences. A
 * confirmation nobody reads is not a safety control, it is a speed bump with a
 * false conscience.
 *
 * This asks with a verb, not a paragraph: the button becomes "<verb>?" plus Yes,
 * and reverts on blur, Escape, or after a few seconds of being ignored. Anything
 * that genuinely needs explaining belongs beside the control where it can be read
 * before the click, never inside the click.
 */
export function ConfirmButton({ children, confirmLabel = 'Sure?', onConfirm, className = 'act', disabled, title }) {
  const [armed, setArmed] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    if (!armed) return undefined
    // Auto-disarm: an armed button left on screen is a trap for the next click.
    timer.current = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(timer.current)
  }, [armed])

  if (!armed) {
    return (
      <button type="button" className={className} disabled={disabled} title={title} onClick={() => setArmed(true)}>
        {children}
      </button>
    )
  }
  return (
    <span className="confirm-inline">
      <span className="confirm-q">{confirmLabel}</span>
      <button
        type="button"
        className="act warn"
        onClick={() => {
          setArmed(false)
          onConfirm()
        }}
      >
        Yes
      </button>
      <button type="button" className="act ghost" onClick={() => setArmed(false)}>
        No
      </button>
    </span>
  )
}
