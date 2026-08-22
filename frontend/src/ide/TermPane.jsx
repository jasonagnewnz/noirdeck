import { FitAddon } from '@xterm/addon-fit'
import { WebglAddon } from '@xterm/addon-webgl'
import { Terminal } from '@xterm/xterm'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import '@xterm/xterm/css/xterm.css'

function cssVar(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

// The terminal follows the active kit. ANSI red and green stay functional
// colours for diffs and test output; cursor, yellow, blue and cyan take the
// app's single signal colour so the PTY looks native in every kit.
//
// Fallbacks are the carbon dark values, matching the :root defaults in
// styles.css. They are reachable only if the stylesheet has not loaded, and an
// earlier set of them held colours from a palette that had been deleted, so a
// terminal in that state painted itself teal.
function readTermTheme() {
  const bg = cssVar('--surface-sunken', '#0d0d0d')
  const panel = cssVar('--surface-2', '#333333')
  const ink = cssVar('--text', '#f4f4f4')
  const inkFaint = cssVar('--text-3', '#a8a8a8')
  const accent = cssVar('--accent', '#78a9ff')
  const accentSoft = cssVar('--accent-soft', 'rgba(120, 169, 255, 0.16)')
  const red = cssVar('--danger', '#da1e28')
  const redText = cssVar('--danger-text', '#ff8389')
  const green = cssVar('--success', '#42be65')

  return {
    background: bg,
    foreground: ink,
    cursor: accent,
    selectionBackground: accentSoft,
    black: panel,
    brightBlack: inkFaint,
    red,
    brightRed: redText,
    green,
    brightGreen: green,
    yellow: accent,
    brightYellow: accent,
    blue: accent,
    brightBlue: accent,
    magenta: redText,
    brightMagenta: redText,
    cyan: accent,
    brightCyan: accent,
    white: ink,
    brightWhite: '#ffffff',
  }
}

// Read `count` lines of buffer text starting at absolute line `start`.
// translateToString(true) trims trailing whitespace per row; we then strip
// trailing blank lines so an export doesn't carry a screenful of padding.
// NOTE: a full-screen TUI (Claude Code, vim) runs in xterm's ALTERNATE buffer,
// which by design has NO scrollback: there "whole session" and "current
// screen" both return just the visible screen. That is inherent to alt-screen
// mode, not a bug: the history simply does not exist to copy.
function readBufferText(term, start, count) {
  const buf = term.buffer.active
  const lines = []
  for (let i = 0; i < count; i++) {
    const line = buf.getLine(start + i)
    lines.push(line ? line.translateToString(true) : '')
  }
  return `${lines.join('\n').replace(/\n+$/, '')}\n`
}

// A live PTY-over-WebSocket terminal. Behavior unchanged from the original
// Workspace.jsx implementation, plus an optional injectPrompt: once the socket
// is open, paste the given text into the PTY after a short settle delay (the
// remote Claude Code session needs a moment to be ready for input): used by
// the project action strip to kick off a live "review structure" / "tidy"
// session without the backend needing a bespoke initial-prompt field.
export default function TermPane({ sid, injectPrompt }) {
  const holder = useRef(null)
  const termRef = useRef(null)
  const [copied, setCopied] = useState(null) // 'screen' | 'session' | null
  // Scroll state drives the Top/Bottom controls. `alt` matters: a full-screen
  // TUI (Claude Code, vim) runs in xterm's ALTERNATE buffer, which has no
  // scrollback at all: so jumping is genuinely impossible there, and the
  // buttons say so rather than looking broken when a click does nothing.
  const [scroll, setScroll] = useState({ atTop: true, atBottom: true, alt: false, lines: 0 })

  // biome-ignore lint/correctness/useExhaustiveDependencies: reconnecting a PTY is keyed by sid; injectPrompt is a one-shot paste when the socket opens.
  useEffect(() => {
    const term = new Terminal({
      fontFamily: 'ui-monospace, "Cascadia Code", "JetBrains Mono", Menlo, Consolas, monospace',
      fontSize: 13,
      theme: readTermTheme(),
      cursorBlink: true,
      scrollback: 10000,
      // Snap to the bottom when the user types, but leave the view put while
      // they read scrollback and the PTY keeps writing: standard terminal feel.
      scrollOnUserInput: true,
    })
    termRef.current = term
    const themeObserver = new MutationObserver(() => {
      term.options.theme = readTermTheme()
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style', 'data-kit', 'data-theme-mode'],
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(holder.current)

    // Keep the scroll controls honest about where we actually are. viewportY is
    // the absolute buffer line at the top of the screen; baseY is that value
    // when scrolled fully down: so equality means "at the bottom".
    const syncScroll = () => {
      const buf = term.buffer.active
      setScroll({
        atTop: buf.viewportY === 0,
        atBottom: buf.viewportY >= buf.baseY,
        alt: buf.type === 'alternate',
        lines: buf.baseY,
      })
    }
    const scrollSub = term.onScroll(syncScroll)
    const writeSub = term.onWriteParsed(syncScroll)
    const bufSub = term.buffer.onBufferChange(syncScroll)
    syncScroll()

    // GPU renderer: the default DOM renderer ghosts and tears rows during fast
    // scroll. WebGL composites the whole grid per frame, so scrolling stays
    // clean. It can lose its GL context (tab backgrounded, driver reset, or
    // running headless): when that happens we dispose the addon and xterm
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
          if (ws.readyState === 1) ws.send(JSON.stringify({ in: `${injectPrompt}\n` }))
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
      themeObserver.disconnect()
      scrollSub.dispose()
      writeSub.dispose()
      bufSub.dispose()
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

  // Share what happened, not the session. Redacted server-side, and the response says
  // what was removed AND what a re-scan still found: so if something got through, the
  // warning appears BEFORE the file is in someone's inbox.
  const [sharing, setSharing] = useState(false)
  const shareSession = useCallback(async () => {
    setSharing(true)
    try {
      const out = await api(`/workspace/${sid}/share`, { body: { note: '' } })
      if (!out.safe_to_send) {
        window.alert(
          `Exported, but read it before sending:\n\nafter redaction the scanner still matched ` +
            `${out.residual_findings} possible credential(s) (${out.residual_detectors.join(', ')}).\n\n` +
            `Redaction matches known secret shapes: a password that looks like an ordinary word is not removed.`
        )
      }
      const blob = new Blob([out.markdown], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = out.filename
      a.click()
      URL.revokeObjectURL(url)
      setCopied(out.secrets_removed ? `shared − ${out.secrets_removed} secret(s) removed` : 'shared')
      setTimeout(() => setCopied(null), 2600)
    } catch (e) {
      window.alert(`Could not export: ${e.message}`)
    }
    setSharing(false)
  }, [sid])

  const copySession = useCallback(() => {
    const term = termRef.current
    if (!term) return
    // Whole buffer: scrollback + the live screen (buffer.length spans both).
    copyText(readBufferText(term, 0, term.buffer.active.length), 'session')
  }, [copyText])

  const scrollTop = useCallback(() => {
    const term = termRef.current
    if (term) term.scrollToTop()
  }, [])

  const scrollBottom = useCallback(() => {
    const term = termRef.current
    if (!term) return
    term.scrollToBottom()
    term.focus() // back to the bottom means back to typing
  }, [])

  // In the alternate buffer there is no history to move through, so both
  // controls are disabled with the reason in the tooltip. Otherwise Top is dead
  // only when already at the top, and Bottom only when already at the bottom.
  const noHistory = scroll.alt || scroll.lines === 0
  const jumpHint = scroll.alt
    ? 'The running program owns the full screen (alternate buffer), which keeps no scrollback: there is no history to jump through'
    : scroll.lines === 0
      ? 'Nothing has scrolled off screen yet'
      : null

  return (
    <div className="termpane-wrap">
      <div className="termpane-toolbar">
        {/* No role="group": each button already carries its own accessible name
            and tooltip, and a fieldset here would fight the toolbar layout. */}
        <div className="term-scroll-group">
          <button
            type="button"
            className="term-copy-btn"
            onClick={scrollTop}
            disabled={noHistory || scroll.atTop}
            title={jumpHint || 'Jump to the start of the scrollback'}
          >
            ↑ Top
          </button>
          <button
            type="button"
            className="term-copy-btn"
            onClick={scrollBottom}
            disabled={noHistory || scroll.atBottom}
            title={jumpHint || 'Jump to the live end of the session'}
          >
            ↓ Bottom
          </button>
          {!noHistory && !scroll.atBottom && (
            <span className="term-scroll-flag" title="The session is still writing below this point">
              scrolled back
            </span>
          )}
        </div>
        <div className="term-toolbar-spacer" />
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
          title="Copy everything, including what has scrolled off the top"
        >
          {copied === 'session' ? 'Copied ✓' : 'Copy session'}
        </button>
        {/* Share what happened, not the session: a redacted transcript file. Nothing is
            uploaded, no socket is opened and nobody is invited: see share.py. */}
        <button
          type="button"
          className="term-copy-btn"
          disabled={sharing}
          onClick={shareSession}
          title="Download a readable transcript of this session, with credentials redacted first. Nothing is uploaded and no session is opened to anyone."
        >
          {sharing ? 'Preparing…' : 'Share'}
        </button>
      </div>
      {/* role="application": this region owns raw keyboard input (it's a live
          PTY): tell assistive tech not to intercept keys the way it would in a
          normal document, same convention VS Code's own integrated terminal uses. */}
      <div className="termpane" ref={holder} role="application" aria-label="Terminal session" />
    </div>
  )
}
