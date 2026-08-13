import React, { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

// Matches the noirdeck :root tokens (styles.css). Real ANSI red/green
// stay functional colors (git diffs, test output) rather than being folded
// into the brand palette — only the accent-purpose slots (cursor/yellow,
// blue/cyan) go fully monochrome-crimson, per brand direction. Cursor/yellow
// use the AA-raised accent (--amber = #F0525E) for brand consistency, though
// note in the a11y report: xterm renders to <canvas>, so WCAG 1.4.3 text
// contrast doesn't strictly bind ANSI colors the way it does real DOM text.
const TERM_THEME = {
  background: '#0a0807', foreground: '#e6e3d8', cursor: '#F0525E',
  selectionBackground: 'rgba(240,82,94,0.25)',
  black: '#1c1815', brightBlack: '#8a827a',
  red: '#CF1D1E', brightRed: '#CF1D1E',
  green: '#7fbf6e', brightGreen: '#7fbf6e',
  yellow: '#F0525E', brightYellow: '#F0525E',
  blue: '#CF1D1E', brightBlue: '#CF1D1E',
  magenta: '#c792ea', brightMagenta: '#c792ea',
  cyan: '#CF1D1E', brightCyan: '#CF1D1E',
  white: '#e6e3d8', brightWhite: '#ffffff',
}

// A live PTY-over-WebSocket terminal. Behavior unchanged from the original
// Workspace.jsx implementation, plus an optional injectPrompt: once the socket
// is open, paste the given text into the PTY after a short settle delay (the
// remote Claude Code session needs a moment to be ready for input) — used by
// the project action strip to kick off a live "review structure" / "tidy"
// session without the backend needing a bespoke initial-prompt field.
export default function TermPane({ sid, injectPrompt }) {
  const holder = useRef(null)
  useEffect(() => {
    const term = new Terminal({
      fontFamily: 'ui-monospace, "Cascadia Code", "JetBrains Mono", Menlo, Consolas, monospace',
      fontSize: 13, theme: TERM_THEME, cursorBlink: true, scrollback: 5000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(holder.current)
    fit.fit()

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

    const ro = new ResizeObserver(() => {
      fit.fit()
      if (ws.readyState === 1) ws.send(JSON.stringify({ resize: [term.cols, term.rows] }))
    })
    ro.observe(holder.current)
    term.focus()
    return () => {
      if (injectTimer) clearTimeout(injectTimer)
      ro.disconnect(); sub.dispose(); ws.close(); term.dispose()
    }
  }, [sid])
  // role="application": this region owns raw keyboard input (it's a live PTY) —
  // tell assistive tech not to intercept keys the way it would in a normal
  // document, same convention VS Code's own integrated terminal uses.
  return <div className="termpane" ref={holder} role="application" aria-label="Terminal session" />
}
