import { FitAddon } from '@xterm/addon-fit'
import { WebglAddon } from '@xterm/addon-webgl'
import { Terminal } from '@xterm/xterm'
import { useCallback, useEffect, useRef, useState } from 'react'
import '@xterm/xterm/css/xterm.css'

// Matches the noirdeck :root tokens (styles.css). Real ANSI red/green
// stay functional colors (git diffs, test output) rather than being folded
// into the brand palette — only the accent-purpose slots (cursor/yellow,
// blue/cyan) go fully monochrome-crimson, per brand direction. Cursor/yellow
// use the AA-raised accent (--amber = #F0525E) for brand consistency, though
// note in the a11y report: xterm renders to <canvas>, so WCAG 1.4.3 text
// contrast doesn't strictly bind ANSI colors the way it does real DOM text.
const TERM_THEME = {
  background: '#0a0807',
  foreground: '#e6e3d8',
  cursor: '#F0525E',
  selectionBackground: 'rgba(240,82,94,0.25)',
  black: '#1c1815',
  brightBlack: '#8a827a',
  red: '#CF1D1E',
  brightRed: '#CF1D1E',
  green: '#7fbf6e',
  brightGreen: '#7fbf6e',
  yellow: '#F0525E',
  brightYellow: '#F0525E',
  blue: '#CF1D1E',
  brightBlue: '#CF1D1E',
  magenta: '#c792ea',
  brightMagenta: '#c792ea',
  cyan: '#CF1D1E',
  brightCyan: '#CF1D1E',
  white: '#e6e3d8',
  brightWhite: '#ffffff',
}

// Read `count` lines of buffer text starting at absolute line `start`.
// translateToString(true) trims trailing whitespace per row; we then strip
// trailing blank lines so an export doesn't carry a screenful of padding.
// NOTE: a full-screen TUI (Claude Code, vim) runs in xterm's ALTERNATE buffer,
// which by design has NO scrollback — there "whole session" and "current
// screen" both return just the visible screen. That is inherent to alt-screen
// mode, not a bug: the history simply does not exist to copy.
function readBufferText(term, start, count) {
  const buf = term.buffer.active
  const lines = []
  for (let i = 0; i < count; i++) {
    const line = buf.getLine(start + i)
    lines.push(line ? line.translateToString(true) : '')
  }
  return lines.join('\n').replace(/\n+$/, '') + '\n'
}

// A live PTY-over-WebSocket terminal. Behavior unchanged from the original
// Workspace.jsx implementation, plus an optional injectPrompt: once the socket
// is open, paste the given text into the PTY after a short settle delay (the
// remote Claude Code session needs a moment to be ready for input) — used by
// the project action strip to kick off a live "review structure" / "tidy"
// session without the backend needing a bespoke initial-prompt field.
export default function TermPane({ sid, injectPrompt }) {
  const holder = useRef(null)
  const termRef = useRef(null)
  const [copied, setCopied] = useState(null) // 'screen' | 'session' | null

  useEffect(() => {
    const term = new Terminal({
      fontFamily: 'ui-monospace, "Cascadia Code", "JetBrains Mono", Menlo, Consolas, monospace',
      fontSize: 13,
      theme: TERM_THEME,
      cursorBlink: true,
      scrollback: 10000,
      // Snap to the bottom when the user types, but leave the view put while
      // they read scrollback and the PTY keeps writing — standard terminal feel.
      scrollOnUserInput: true,
    })
    termRef.current = term
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(holder.current)

    // GPU renderer: the default DOM renderer ghosts and tears rows during fast
    // scroll. WebGL composites the whole grid per frame, so scrolling stays
    // clean. It can lose its GL context (tab backgrounded, driver reset, or
    // running headless) — when that happens we dispose the addon and xterm
    // silently falls back to the DOM renderer, which is slower but always
    // correct. Construction itself can throw where WebGL is unavailable, so the
    // whole thing is guarded: no renderer addon simply means the DOM path.
    let webgl = null
    try {
      webgl = new WebglAddon()
      webgl.onContextLoss(() => {
        if (webgl) {
          webgl.dispose()
          webgl = null
        }
      })
      term.loadAddon(webgl)
    } catch (_e) {
      webgl = null
    }

    // fit() throws if the container is 0×0, which happens while a pane is
    // animating in or hidden. Never let a resize tick crash the effect.
    const safeFit = () => {
      try {
        fit.fit()
      } catch (_e) {
        /* container not laid out yet */
      }
    }
    // First fit on the next frame, once the flex layout has resolved a height.
    const raf = requestAnimationFrame(safeFit)

    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/workspace/ws/${sid}`)
    ws.binaryType = 'arraybuffer'
    ws.onmessage = (ev) => term.write(new Uint8Array(ev.data))
    let injectTimer = null
    ws.onopen = () => {
      ws.send(JSON.stringify({ resize: [term.cols, term.rows] }))
      if (injectPrompt) {
        injectTimer = setTimeout(() => {
          if (ws.readyState === 1) ws.send(JSON.stringify({ in: injectPrompt + '\n' }))
        }, 3000)
      }
    }
    ws.onclose = () => term.write('\r\n\x1b[33m[session ended]\x1b[0m\r\n')
    const sub = term.onData((d) => ws.readyState === 1 && ws.send(JSON.stringify({ in: d })))

    // Debounce resize: a drag fires the observer dozens of times a second, and
    // refitting on every tick thrashes reflow and makes the viewport jump while
    // you scroll. Coalesce to one fit + one PTY resize once the drag settles.
    let resizeTimer = null
    const ro = new ResizeObserver(() => {
      if (resizeTimer) clearTimeout(resizeTimer)
      resizeTimer = setTimeout(() => {
        safeFit()
        if (ws.readyState === 1) ws.send(JSON.stringify({ resize: [term.cols, term.rows] }))
      }, 80)
    })
    ro.observe(holder.current)
    term.focus()
    return () => {
      cancelAnimationFrame(raf)
      if (resizeTimer) clearTimeout(resizeTimer)
      if (injectTimer) clearTimeout(injectTimer)
      ro.disconnect()
      sub.dispose()
      ws.close()
      if (webgl) webgl.dispose()
      term.dispose()
      termRef.current = null
    }
  }, [sid])

  const copyText = useCallback(async (text, which) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch (_e) {
      // clipboard API needs a secure context (https/localhost); fall back to
      // the legacy execCommand path so copy still works over plain http.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      ta.style.pointerEvents = 'none'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      try {
        document.execCommand('copy')
      } catch (_e2) {
        /* nothing more we can do */
      }
      document.body.removeChild(ta)
    }
    setCopied(which)
    setTimeout(() => setCopied(null), 1200)
    const term = termRef.current
    if (term) term.focus() // return focus so typing resumes after an export
  }, [])

  const copyScreen = useCallback(() => {
    const term = termRef.current
    if (!term) return
    // viewportY = absolute buffer line at the top of what's on screen right now,
    // so this exports exactly what the user is looking at, scrolled or not.
    copyText(readBufferText(term, term.buffer.active.viewportY, term.rows), 'screen')
  }, [copyText])

  const copySession = useCallback(() => {
    const term = termRef.current
    if (!term) return
    // Whole buffer: scrollback + the live screen (buffer.length spans both).
    copyText(readBufferText(term, 0, term.buffer.active.length), 'session')
  }, [copyText])

  return (
    <div className="termpane-wrap">
      <div className="termpane-toolbar">
        <button
          type="button"
          className="term-copy-btn"
          onClick={copyScreen}
          title="Copy the visible screen to the clipboard"
        >
          {copied === 'screen' ? 'Copied ✓' : 'Copy screen'}
        </button>
        <button
          type="button"
          className="term-copy-btn"
          onClick={copySession}
          title="Copy the whole session (scrollback + screen) to the clipboard"
        >
          {copied === 'session' ? 'Copied ✓' : 'Copy session'}
        </button>
      </div>
      {/* role="application": this region owns raw keyboard input (it's a live
          PTY) — tell assistive tech not to intercept keys the way it would in a
          normal document, same convention VS Code's own integrated terminal uses. */}
      <div className="termpane" ref={holder} role="application" aria-label="Terminal session" />
    </div>
  )
}
