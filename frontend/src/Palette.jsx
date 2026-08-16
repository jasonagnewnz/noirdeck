import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { PALETTE_SHORTCUTS } from './ide/claudeRef.js'
import { useFocusTrap } from './ide/useFocusTrap.js'

// Shortcut content is shared with the "?" quick-keys menu (ide/claudeRef.js) —
// one source of truth for the whole Claude Code reference.
const SHORTCUTS = PALETTE_SHORTCUTS

const TIPS = [
  'Quick keys: 1–0 jump between views, Ctrl+B toggles the sidebar, ? shows the cheat sheet.',
  'Use plan mode before big or irreversible changes — review the plan before code lands.',
  'Queue overnight tasks in noirdeck so the pipeline runs unattended while you sleep.',
  'Open a session with /context-prime instead of reading the whole tree cold.',
  'Paste screenshots straight into the prompt with Ctrl+V for visual bugs and mockups.',
  'Use git worktrees to run parallel sessions on one repo without them treading on each other.',
  'Say "think hard" (or "think harder") to trigger extended thinking on a genuinely hard problem.',
  'Fan a big sweep out to subagents that return conclusions, not file dumps — keep the main thread thin.',
  'Land the work and write a memory note before the context window fills, then /clear.',
]

const KIND_LABEL = { skill: 'skill', shortcut: 'shortcut', tip: 'tip' }

function matches(query, ...fields) {
  if (!query) return true
  const needle = query.toLowerCase()
  return fields.some((f) => (f || '').toLowerCase().includes(needle))
}

export default function Palette({ open, onClose }) {
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const [skills, setSkills] = useState([])
  const [skillsError, setSkillsError] = useState(null)
  const [copiedKey, setCopiedKey] = useState(null)
  const panelRef = useRef(null)
  const listRef = useRef(null)
  const copyTimer = useRef(null)

  // Modal focus contract: move focus in, trap Tab inside, restore on close.
  useFocusTrap(panelRef, open)

  // Reset + (re)fetch skills every time the palette opens.
  useEffect(() => {
    if (!open) return
    setQuery('')
    setActiveIndex(0)
    setCopiedKey(null)
    let alive = true
    api('/skills')
      .then((data) => {
        if (alive) {
          setSkills(Array.isArray(data) ? data : [])
          setSkillsError(null)
        }
      })
      .catch((e) => {
        if (alive) setSkillsError(e.message || 'failed to load skills')
      })
    return () => {
      alive = false
    }
  }, [open])

  useEffect(() => () => clearTimeout(copyTimer.current), [])

  const sections = useMemo(() => {
    const skillItems = skills.map((s) => ({
      id: `skill:${s.dir || s.name}`,
      kind: 'skill',
      title: `/${s.name}`,
      subtitle: s.description || '',
      copyValue: `/${s.name}`,
    }))
    const shortcutItems = SHORTCUTS.map(([key, desc]) => ({
      id: `shortcut:${key}`,
      kind: 'shortcut',
      title: key,
      subtitle: desc,
      copyValue: key,
    }))
    const tipItems = TIPS.map((tip, i) => ({
      id: `tip:${i}`,
      kind: 'tip',
      title: tip,
      subtitle: '',
      copyValue: tip,
    }))
    return [
      { key: 'skills', label: 'Your skills', items: skillItems },
      { key: 'shortcuts', label: 'Claude Code shortcuts', items: shortcutItems },
      { key: 'tips', label: 'Quick tips', items: tipItems },
    ]
  }, [skills])

  const filteredSections = useMemo(
    () =>
      sections
        .map((s) => ({ ...s, items: s.items.filter((it) => matches(query, it.title, it.subtitle)) }))
        .filter((s) => s.items.length > 0),
    [sections, query]
  )

  const flat = useMemo(() => filteredSections.flatMap((s) => s.items), [filteredSections])
  const idxById = useMemo(() => {
    const m = new Map()
    flat.forEach((it, i) => {
      m.set(it.id, i)
    })
    return m
  }, [flat])

  useEffect(() => {
    setActiveIndex(0)
  }, [query])
  useEffect(() => {
    if (activeIndex >= flat.length) setActiveIndex(Math.max(0, flat.length - 1))
  }, [flat, activeIndex])

  useEffect(() => {
    if (!open) return
    const row = listRef.current?.querySelector(`[data-idx="${activeIndex}"]`)
    row?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, open])

  if (!open) return null

  const activate = async (item) => {
    if (!item) return
    try {
      await navigator.clipboard.writeText(item.copyValue)
      setCopiedKey(item.id)
      clearTimeout(copyTimer.current)
      copyTimer.current = setTimeout(() => setCopiedKey(null), 1100)
    } catch {
      // clipboard blocked (insecure context / permission denied) — fail quietly, no crash
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose?.()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, flat.length - 1))
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      activate(flat[activeIndex])
    }
  }

  return (
    <div
      className="jcp-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.()
      }}
      onKeyDown={onKeyDown}
    >
      <style>{`
        .jcp-backdrop {
          position: fixed; inset: 0; z-index: 999;
          background: rgba(6, 8, 7, 0.62);
          backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
          display: flex; align-items: flex-start; justify-content: center;
          padding-top: 12vh;
          animation: jcp-fade .12s ease both;
        }
        @keyframes jcp-fade { from { opacity: 0 } to { opacity: 1 } }
        @keyframes jcp-pop { from { opacity: 0; transform: translateY(-6px) scale(.98) } to { opacity: 1; transform: none } }
        .jcp-panel {
          width: 640px; max-width: 92vw; max-height: 70vh; display: flex; flex-direction: column;
          background: var(--panel, #15120f); border: 1px solid var(--line, #2c2620);
          box-shadow: 0 20px 60px rgba(0,0,0,0.6);
          font-family: var(--mono, ui-monospace, monospace);
          animation: jcp-pop .14s ease both;
        }
        .jcp-searchwrap { padding: 12px 14px; border-bottom: 1px solid var(--line, #2c2620); }
        .jcp-input {
          width: 100%; background: var(--bg-deep, #0a0807); border: 1px solid var(--line, #2c2620);
          color: var(--ink, #e6e3d8); font-family: inherit; font-size: 14px; padding: 9px 12px;
        }
        .jcp-input:focus { outline: none; border-color: var(--amber, #F0525E); }
        .jcp-list { overflow-y: auto; padding: 6px; }
        .jcp-section-label {
          font-size: 10px; text-transform: uppercase; letter-spacing: 0.14em;
          color: var(--ink-faint, #8a827a); padding: 8px 8px 4px;
        }
        .jcp-row {
          display: flex; align-items: center; gap: 8px; padding: 7px 8px; cursor: pointer;
          border-left: 2px solid transparent;
        }
        .jcp-row.on { background: var(--amber-soft, rgba(240,82,94,0.14)); border-left-color: var(--amber, #F0525E); }
        .jcp-row .jcp-title { color: var(--ink, #e6e3d8); font-size: 12.5px; flex-shrink: 0; }
        .jcp-row .jcp-subtitle {
          color: var(--ink-dim, #a89e92); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis;
          white-space: nowrap; flex: 1; min-width: 0;
        }
        .jcp-empty { color: var(--ink-faint, #8a827a); padding: 24px 8px; text-align: center; font-size: 12px; }
        .jcp-footer {
          display: flex; gap: 14px; padding: 8px 14px; border-top: 1px solid var(--line, #2c2620);
          color: var(--ink-faint, #8a827a); font-size: 10.5px; letter-spacing: 0.04em;
        }
      `}</style>
      <div className="jcp-panel" ref={panelRef} role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="jcp-searchwrap">
          <input
            className="jcp-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search skills, shortcuts, tips…"
            aria-label="Search skills, shortcuts, and tips"
            aria-autocomplete="list"
            aria-owns="jcp-listbox"
            aria-activedescendant={flat.length ? `jcp-opt-${activeIndex}` : undefined}
            data-autofocus
          />
          {skillsError && (
            <div className="err" role="alert" style={{ fontSize: 11, marginTop: 6 }}>
              skills: {skillsError}
            </div>
          )}
        </div>
        <div
          className="jcp-list"
          ref={listRef}
          id="jcp-listbox"
          role="listbox"
          aria-label="Search results"
          tabIndex={0}
        >
          {flat.length === 0 && <div className="jcp-empty">no matches</div>}
          {filteredSections.map((section) => (
            <div key={section.key}>
              <div className="jcp-section-label">{section.label}</div>
              {section.items.map((item) => {
                const idx = idxById.get(item.id)
                const isOn = idx === activeIndex
                return (
                  <div
                    key={item.id}
                    id={`jcp-opt-${idx}`}
                    data-idx={idx}
                    role="option"
                    aria-selected={isOn}
                    className={`jcp-row${isOn ? ' on' : ''}`}
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => activate(item)}
                  >
                    <span className={`chip${item.kind === 'skill' ? ' hot' : ''}`}>{KIND_LABEL[item.kind]}</span>
                    <span className="jcp-title">{item.title}</span>
                    {item.subtitle && <span className="jcp-subtitle">— {item.subtitle}</span>}
                    {copiedKey === item.id && (
                      <span className="pill done" role="status" aria-live="polite">
                        copied ✓
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
        <div className="jcp-footer">
          <span>↑↓ navigate</span>
          <span>⏎ copy</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  )
}
