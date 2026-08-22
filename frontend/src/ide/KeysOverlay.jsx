import { useRef, useState } from 'react'
import { CLAUDE_TABS } from './claudeRef.js'
import { useFocusTrap } from './useFocusTrap.js'

// Quick-keys menu: "?" opens it. App tab = noirdeck's own keys;
// the other tabs are the full Claude Code reference (session keys, slash
// commands, CLI). Rows copy their key/command to the clipboard.
const GLOBAL_KEYS = [
  ['Ctrl+K', 'command palette: skills, shortcuts, tips'],
  ['Ctrl+B', 'expand / collapse the sidebar'],
  ['Ctrl+`', 'show / hide the terminal panel'],
  ['1 – 0', 'jump between views'],
  ['?', 'this menu'],
  ['Esc', 'close overlays'],
]

const TAB_KEYS = ['app', ...CLAUDE_TABS.map((t) => t.key)]
const TAB_LABEL = { app: 'app', ...Object.fromEntries(CLAUDE_TABS.map((t) => [t.key, t.title])) }

export default function KeysOverlay({ open, views, onClose, onSelect }) {
  const [tab, setTab] = useState('app')
  const [q, setQ] = useState('')
  const [copied, setCopied] = useState(null)
  const panelRef = useRef(null)
  const tabRefs = useRef({})
  useFocusTrap(panelRef, open)
  if (!open) return null

  const copy = (text) => {
    try {
      navigator.clipboard.writeText(text)
    } catch {
      /* clipboard unavailable */
    }
    setCopied(text)
    setTimeout(() => setCopied(null), 1100)
  }
  const match = ([k, d]) => !q || (k + ' ' + d).toLowerCase().includes(q.toLowerCase())
  const activeTab = CLAUDE_TABS.find((t) => t.key === tab)

  const gotoTab = (key) => {
    setTab(key)
    tabRefs.current[key]?.focus()
  }
  const onTabsKeyDown = (e) => {
    const idx = TAB_KEYS.indexOf(tab)
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      gotoTab(TAB_KEYS[(idx + 1) % TAB_KEYS.length])
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      gotoTab(TAB_KEYS[(idx - 1 + TAB_KEYS.length) % TAB_KEYS.length])
    } else if (e.key === 'Home') {
      e.preventDefault()
      gotoTab(TAB_KEYS[0])
    } else if (e.key === 'End') {
      e.preventDefault()
      gotoTab(TAB_KEYS[TAB_KEYS.length - 1])
    }
  }

  return (
    <div className="keys-backdrop" onClick={onClose}>
      <div
        className="keys-panel"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Quick keys"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="keys-headrow">
          <div className="keys-head" id="keys-head">
            quick keys
          </div>
          <div className="keys-tabs" role="tablist" aria-labelledby="keys-head" onKeyDown={onTabsKeyDown}>
            {TAB_KEYS.map((key) => (
              <button
                type="button"
                key={key}
                ref={(el) => {
                  tabRefs.current[key] = el
                }}
                role="tab"
                id={`keys-tab-${key}`}
                aria-selected={tab === key}
                aria-controls="keys-tabpanel"
                tabIndex={tab === key ? 0 : -1}
                className={tab === key ? 'on' : ''}
                data-autofocus={tab === key ? true : undefined}
                onClick={() => setTab(key)}
              >
                {TAB_LABEL[key]}
              </button>
            ))}
          </div>
        </div>
        {tab !== 'app' && (
          <input
            className="keys-filter"
            value={q}
            placeholder="filter…"
            autoFocus
            aria-label={`Filter ${TAB_LABEL[tab]} reference`}
            onChange={(e) => setQ(e.target.value)}
          />
        )}
        <div id="keys-tabpanel" role="tabpanel" aria-labelledby={`keys-tab-${tab}`}>
          {tab === 'app' ? (
            <div className="keys-cols">
              <div>
                <div className="keys-sec" id="keys-sec-global">
                  global
                </div>
                <div role="list" aria-labelledby="keys-sec-global">
                  {GLOBAL_KEYS.map(([k, desc]) => (
                    <div className="keys-row" role="listitem" key={k}>
                      <kbd>{k}</kbd>
                      <span>{desc}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="keys-sec" id="keys-sec-views">
                  views
                </div>
                <div role="list" aria-labelledby="keys-sec-views">
                  {views.map(([key, label], i) => (
                    <button
                      type="button"
                      className="keys-row link"
                      key={key}
                      onClick={() => {
                        onSelect(key)
                        onClose()
                      }}
                    >
                      {/* only the first ten views carry digit shortcuts */}
                      <kbd>{i < 10 ? (i + 1) % 10 : '·'}</kbd>
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="keys-scroll">
              {activeTab.items.filter(match).map(([k, desc]) => (
                <button
                  type="button"
                  className="keys-row link wide"
                  key={k}
                  title="click to copy"
                  onClick={() => copy(k)}
                >
                  <kbd>{k}</kbd>
                  <span>{desc}</span>
                  {copied === k && (
                    <em className="keys-copied" role="status" aria-live="polite">
                      copied ✓
                    </em>
                  )}
                </button>
              ))}
              {activeTab.items.filter(match).length === 0 && <div className="keys-empty">nothing matches "{q}"</div>}
            </div>
          )}
        </div>
        <div className="keys-foot">
          {tab === 'app'
            ? 'terminal panes keep their own keys: the other tabs here are the full Claude Code reference'
            : 'click a row to copy it · CLI tab verified against the installed claude 2.1.229'}
        </div>
      </div>
    </div>
  )
}
