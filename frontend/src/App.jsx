import { lazy, Suspense, useEffect, useLayoutEffect, useState } from 'react'
import { useData, useEvents } from './api.js'
import ActivityBar from './ide/ActivityBar.jsx'
import KeysOverlay from './ide/KeysOverlay.jsx'
import StatusBar from './ide/StatusBar.jsx'
import { applyTheme, loadThemeKey, THEME_STORAGE_KEY } from './ide/themes.js'
import Palette from './Palette.jsx'
import Builds from './views/Builds.jsx'
import Design from './views/Design.jsx'
import Help from './views/Help.jsx'
import Memories from './views/Memories.jsx'
import Overview from './views/Overview.jsx'
import Proposals from './views/Proposals.jsx'
import Quality from './views/Quality.jsx'
import Queue from './views/Queue.jsx'
import Sessions from './views/Sessions.jsx'
import Skills from './views/Skills.jsx'

// Workspace pulls in @xterm/xterm (a full terminal emulator) — the heaviest
// dependency in the app by far. Deferring it keeps that weight out of the
// initial chunk for every session that never opens a terminal.
const Workspace = lazy(() => import('./views/Workspace.jsx'))

const VIEWS = [
  ['overview', 'Overview', Overview],
  ['workspace', 'Workspace', Workspace],
  ['builds', 'Builds', Builds],
  ['design', 'Design Studio', Design],
  ['sessions', 'Sessions', Sessions],
  ['skills', 'Skills + Agents', Skills],
  ['memories', 'Memories', Memories],
  ['proposals', 'Proposals', Proposals],
  ['queue', 'Overnight Queue', Queue],
  ['quality', 'Quality Gates', Quality],
  ['help', 'Help', Help],
]

const SIDEBAR_KEY = 'nd.sidebar'

// Views deep-link as #builds / #queue etc so refresh, bookmarks and the browser
// back button all keep your place — state alone loses it on every reload.
const viewFromHash = () => {
  // "#help:queue" = the help view, scrolled to its queue chapter — only the
  // part before the colon names the view; the suffix belongs to the view itself
  const k = window.location.hash.replace(/^#\/?/, '').split(':')[0]
  return VIEWS.some(([key]) => key === k) ? k : 'overview'
}

export default function App() {
  const [view, setViewState] = useState(viewFromHash)
  const setView = (k) => {
    setViewState(k)
    if (window.location.hash !== `#${k}`) window.location.hash = k
  }
  const [launch, setLaunch] = useState(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [keysOpen, setKeysOpen] = useState(false)
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === '1'
    } catch {
      return false
    }
  })
  const [theme, setTheme] = useState(loadThemeKey)
  // useLayoutEffect: tokens land on <html> before first paint, so a persisted
  // non-default theme never flashes noir on load
  useLayoutEffect(() => {
    applyTheme(theme)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      /* storage unavailable */
    }
  }, [theme])
  const openWorkspace = (payload) => {
    setLaunch(payload)
    setView('workspace')
  }
  const { live, bump } = useEvents()
  const { data: ov } = useData('/overview', bump)
  const Current = VIEWS.find(([k]) => k === view)[2]
  const badges = {
    proposals: ov?.proposals_pending || 0,
    queue: (ov?.queue?.blocked || 0) + (ov?.queue?.queued || 0),
    overview: ov?.open_loops?.length || 0,
  }

  const toggleSidebar = () => {
    setSidebarExpanded((prev) => {
      const next = !prev
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0')
      } catch {
        /* storage unavailable */
      }
      return next
    })
  }

  useEffect(() => {
    // browser back/forward — hashchange is the source of truth for the view
    const onHash = () => setViewState(viewFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    // unmodified keys (digits, "?") must never fire while the user is typing —
    // inputs, selects, contenteditable, and xterm's hidden helper textarea
    const typing = (e) => {
      const t = e.target
      if (!t) return false
      const tag = t.tagName
      return (
        tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable || !!t.closest?.('.termpane')
      )
    }
    const onKey = (e) => {
      const key = e.key.toLowerCase()
      if ((e.metaKey || e.ctrlKey) && key === 'k') {
        e.preventDefault()
        // only one modal traps focus at a time — opening one always closes the other
        setPaletteOpen((o) => {
          const next = !o
          if (next) setKeysOpen(false)
          return next
        })
        return
      }
      if ((e.metaKey || e.ctrlKey) && key === 'b') {
        // the terminal has its own Ctrl+B (Claude Code: background a running task) —
        // let a focused xterm keep it instead of stealing it for the sidebar toggle
        if (e.target?.closest?.('.termpane')) return
        e.preventDefault()
        toggleSidebar()
        return
      }
      if (e.key === 'Escape') {
        setPaletteOpen(false)
        setKeysOpen(false)
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e)) return
      if (e.key === '?') {
        e.preventDefault()
        setKeysOpen((o) => {
          const next = !o
          if (next) setPaletteOpen(false)
          return next
        })
        return
      }
      if (/^[0-9]$/.test(e.key)) {
        const idx = e.key === '0' ? 9 : Number(e.key) - 1
        if (idx < VIEWS.length) {
          e.preventDefault()
          setView(VIEWS[idx][0])
          setPaletteOpen(false)
          setKeysOpen(false)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="shell">
      <div className="shell-body">
        <ActivityBar
          views={VIEWS.map(([k, label]) => [k, label])}
          active={view}
          badges={badges}
          onSelect={setView}
          expanded={sidebarExpanded}
          onToggleExpanded={toggleSidebar}
        />
        <main className="main" id="main" tabIndex={-1}>
          <Suspense fallback={<div className="loading">loading…</div>}>
            <Current bump={bump} overview={ov} launch={launch} openWorkspace={openWorkspace} />
          </Suspense>
        </main>
      </div>
      <StatusBar
        live={live}
        overview={ov}
        theme={theme}
        onSetTheme={setTheme}
        onOpenPalette={() =>
          setPaletteOpen((o) => {
            const next = !o
            if (next) setKeysOpen(false)
            return next
          })
        }
        onOpenKeys={() =>
          setKeysOpen((o) => {
            const next = !o
            if (next) setPaletteOpen(false)
            return next
          })
        }
      />
      <Palette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <KeysOverlay
        open={keysOpen}
        views={VIEWS.map(([k, label]) => [k, label])}
        onClose={() => setKeysOpen(false)}
        onSelect={setView}
      />
    </div>
  )
}
