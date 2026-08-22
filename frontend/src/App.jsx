import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useState } from 'react'
import { useData, useEvents } from './api.js'
import ActivityBar from './ide/ActivityBar.jsx'
import { applyAppearance, loadAppearance, saveAppearance } from './ide/appearance.js'
import KeysOverlay from './ide/KeysOverlay.jsx'
import StatusBar from './ide/StatusBar.jsx'
import Palette from './Palette.jsx'
import Builds from './views/Builds.jsx'
import Overview from './views/Overview.jsx'
import Proposals from './views/Proposals.jsx'
import Queue from './views/Queue.jsx'
import Sessions from './views/Sessions.jsx'

// What loads up front is the daily loop and nothing else.
//
// Workspace pulls in @xterm/xterm, a full terminal emulator and by a wide margin
// the heaviest dependency here. The advanced views are deferred for the opposite
// reason: they are individually small but collectively large, and most sessions
// open none of them. Help is the clearest case at roughly 2,500 words of manual
// that every visitor used to download whether or not they read it.
const Workspace = lazy(() => import('./views/Workspace.jsx'))
const BottomPanel = lazy(() => import('./ide/BottomPanel.jsx'))
const Design = lazy(() => import('./views/Design.jsx'))
const Help = lazy(() => import('./views/Help.jsx'))
const Memories = lazy(() => import('./views/Memories.jsx'))
const Quality = lazy(() => import('./views/Quality.jsx'))
const Secrets = lazy(() => import('./views/Secrets.jsx'))
const Settings = lazy(() => import('./views/Settings.jsx'))
const Skills = lazy(() => import('./views/Skills.jsx'))

// The rail carries the daily loop. Everything else is still a first-class view
// with its own #hash: it just isn't competing for attention in the sidebar.
// PRIMARY order is also the 1-9 digit-key order, so moving an entry between
// these two lists silently renumbers the shortcuts; update KeysOverlay's copy
// if you reorder.
const PRIMARY_VIEWS = [
  ['overview', 'Home', Overview],
  ['workspace', 'Build Live', Workspace],
  ['builds', 'Builds', Builds],
  ['queue', 'Tasks', Queue],
  ['proposals', 'Review', Proposals],
  ['sessions', 'History', Sessions],
]

// Reached from Settings, the palette, or a direct #hash: not from the rail.
//Guide moved OUT of the primary rail 2026-08-19. A manual in the daily-loop
// navigation is the UI admitting it needs one: 2,563 words of explanation sitting
// beside the seven things you actually do. Every view still links to its own
// chapter via "how this works", so it is one click from wherever the confusion
// happened: which is more useful than a permanent rail slot anyway. If the Guide
// starts getting heavy traffic again, fix the screen people arrive from.
const ADVANCED_VIEWS = [
  ['help', 'Guide', Help],
  ['design', 'Design', Design],
  ['skills', 'Skills', Skills],
  ['memories', 'Memories', Memories],
  ['quality', 'Checks', Quality],
  ['secrets', 'Credentials', Secrets],
]

const VIEWS = [...PRIMARY_VIEWS, ...ADVANCED_VIEWS, ['settings', 'Settings', Settings]]

const SIDEBAR_KEY = 'nd.sidebar'

const DOCK_KEY = 'nd.dockOpen'

// Read once, at module scope: the dock should come back at the size and state it
// was left in, not jump to them a frame after mount.
const DEFAULT_DOCK_HEIGHT = (() => {
  try {
    const stored = Number.parseInt(localStorage.getItem('nd.panelH'), 10)
    return Number.isFinite(stored) ? stored : 300
  } catch {
    return 300
  }
})()

const DOCK_OPEN_AT_START = (() => {
  try {
    return localStorage.getItem(DOCK_KEY) === '1'
  } catch {
    return false
  }
})()

// Views deep-link as #builds / #queue etc so refresh, bookmarks and the browser
// back button all keep your place: state alone loses it on every reload.
const viewFromHash = () => {
  // "#help:queue" = the help view, scrolled to its queue chapter: only the
  // part before the colon names the view; the suffix belongs to the view itself
  const k = window.location.hash.replace(/^#\/?/, '').split(':')[0]
  return VIEWS.some(([key]) => key === k) ? k : 'overview'
}

export default function App() {
  const [view, setViewState] = useState(viewFromHash)
  const setView = useCallback((k) => {
    setViewState(k)
    if (window.location.hash !== `#${k}`) window.location.hash = k
  }, [])
  const [launch, setLaunch] = useState(null)
  // The dock is the shell's own terminal. Build Live already fills the viewport
  // with one, so the dock stays out of its way there rather than running a
  // second emulator over the top of the first.
  const [dockOpen, setDockOpen] = useState(DOCK_OPEN_AT_START)
  const [dockHeight, setDockHeight] = useState(DEFAULT_DOCK_HEIGHT)
  const toggleDock = useCallback(() => {
    setDockOpen((open) => {
      try {
        localStorage.setItem(DOCK_KEY, open ? '0' : '1')
      } catch {
        // The panel still toggles; only the memory of it is lost.
      }
      return !open
    })
  }, [])
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [keysOpen, setKeysOpen] = useState(false)
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === '1'
    } catch {
      return false
    }
  })
  // index.html has already stamped the stored appearance before this component
  // exists, so this is not what prevents a flash. It is what keeps the DOM in
  // step once a dial is turned.
  const [appearance, setAppearance] = useState(loadAppearance)
  const setDial = useCallback((dial, value) => {
    setAppearance((current) => ({ ...current, [dial]: value }))
  }, [])
  useLayoutEffect(() => {
    applyAppearance(appearance)
    saveAppearance(appearance)
  }, [appearance])
  // 'Match system' has to keep matching after the system changes its mind.
  useEffect(() => {
    if (appearance.mode !== 'system' || !window.matchMedia) return undefined
    const query = window.matchMedia('(prefers-color-scheme: light)')
    const resync = () => applyAppearance(appearance)
    query.addEventListener('change', resync)
    return () => query.removeEventListener('change', resync)
  }, [appearance])
  const openWorkspace = (payload) => {
    setLaunch(payload)
    setView('workspace')
  }
  const runIntent = useCallback(
    (intent) => {
      const next = { ...intent, id: intent.id || `${Date.now()}-${Math.random().toString(16).slice(2)}` }
      setLaunch(next)
      setView(next.view || 'overview')
      setPaletteOpen(false)
      setKeysOpen(false)
    },
    [setView]
  )
  const { live, bump } = useEvents()
  const { data: ov } = useData('/overview', bump)
  const Current = VIEWS.find(([k]) => k === view)[2]
  const badges = {
    proposals: ov?.proposals_pending || 0,
    queue: (ov?.queue?.blocked || 0) + (ov?.queue?.queued || 0),
    overview: ov?.open_loops?.length || 0,
  }

  const toggleSidebar = useCallback(() => {
    setSidebarExpanded((prev) => {
      const next = !prev
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0')
      } catch {
        /* storage unavailable */
      }
      return next
    })
  }, [])

  useEffect(() => {
    // browser back/forward: hashchange is the source of truth for the view
    const onHash = () => setViewState(viewFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    // unmodified keys (digits, "?") must never fire while the user is typing:
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
        // only one modal traps focus at a time: opening one always closes the other
        setPaletteOpen((o) => {
          const next = !o
          if (next) setKeysOpen(false)
          return next
        })
        return
      }
      if ((e.metaKey || e.ctrlKey) && (key === '`' || key === '~')) {
        e.preventDefault()
        toggleDock()
        return
      }
      if ((e.metaKey || e.ctrlKey) && key === 'b') {
        // the terminal has its own Ctrl+B (Claude Code: background a running task):
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
        // digits address the rail only: 0 opens Settings, which has no slot
        if (e.key === '0') {
          e.preventDefault()
          setView('settings')
          setPaletteOpen(false)
          setKeysOpen(false)
          return
        }
        const idx = Number(e.key) - 1
        if (idx < PRIMARY_VIEWS.length) {
          e.preventDefault()
          setView(PRIMARY_VIEWS[idx][0])
          setPaletteOpen(false)
          setKeysOpen(false)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setView, toggleSidebar, toggleDock])

  return (
    <div className="shell">
      <div className="shell-body">
        <ActivityBar
          views={PRIMARY_VIEWS.map(([k, label]) => [k, label])}
          active={view}
          badges={badges}
          onSelect={setView}
          expanded={sidebarExpanded}
          onToggleExpanded={toggleSidebar}
        />
        {/* Build live owns the viewport: the terminal must fit exactly so the
            session scrolls inside xterm, never by scrolling the page under it. */}
        <main className={`main${view === 'workspace' ? ' main-flush' : ''}`} id="main" tabIndex={-1}>
          <Suspense fallback={<div className="loading">loading…</div>}>
            <Current
              bump={bump}
              overview={ov}
              launch={launch}
              openWorkspace={openWorkspace}
              onIntent={runIntent}
              appearance={appearance}
              onSetDial={setDial}
            />
          </Suspense>
        </main>
      </div>
      {dockOpen && view !== 'workspace' && (
        <Suspense fallback={null}>
          <BottomPanel
            height={dockHeight}
            onResize={setDockHeight}
            onClose={() => setDockOpen(false)}
            onOpenWorkspace={() => setView('workspace')}
          />
        </Suspense>
      )}
      <StatusBar
        live={live}
        overview={ov}
        appearance={appearance}
        onSetDial={setDial}
        dockOpen={dockOpen && view !== 'workspace'}
        onToggleDock={toggleDock}
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
      <Palette open={paletteOpen} onClose={() => setPaletteOpen(false)} onIntent={runIntent} />
      <KeysOverlay
        open={keysOpen}
        views={PRIMARY_VIEWS.map(([k, label]) => [k, label])}
        onClose={() => setKeysOpen(false)}
        onSelect={setView}
      />
    </div>
  )
}
