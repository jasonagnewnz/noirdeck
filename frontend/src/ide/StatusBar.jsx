import React, { useEffect, useState } from 'react'
import { getJSON } from './ideApi.js'
import { THEMES } from './themes.js'

// Bottom status bar — live SSE state, pending-proposals count, queue counts,
// active workspace session count (self-polled), the ⌘K launcher, version (live
// from the backend's own health check rather than a hardcoded string, so this
// bar can never drift out of sync with what's actually deployed).
export default function StatusBar({ live, overview, onOpenPalette, onOpenKeys, theme, onSetTheme }) {
  const [sessionCount, setSessionCount] = useState(null)
  const [version, setVersion] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () => getJSON('/workspace')
      .then((rows) => alive && setSessionCount(Array.isArray(rows) ? rows.length : 0))
      .catch(() => { /* leave last-known value */ })
    load()
    const t = setInterval(load, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  useEffect(() => {
    let alive = true
    getJSON('/health').then((d) => alive && setVersion(d.version)).catch(() => { /* leave blank */ })
    return () => { alive = false }
  }, [])

  const [vault, setVault] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => getJSON('/vault')
      .then((d) => alive && setVault(d)).catch(() => { /* leave last-known */ })
    load()
    const t = setInterval(load, 10 * 60 * 1000)
    return () => { alive = false; clearInterval(t) }
  }, [])
  const vaultAgeH = vault?.last_verified
    ? (Date.now() - new Date(vault.last_verified).getTime()) / 3600000 : null
  const vaultState = !vault ? null
    : !vault.configured ? ['off', 'vault off']
    : vaultAgeH === null ? ['warn', 'vault: no verified backup yet']
    : vaultAgeH <= 48 ? ['ok', `vault ✓ ${vaultAgeH < 1 ? '<1h' : Math.round(vaultAgeH) + 'h'}`]
    : ['warn', `vault ! ${Math.round(vaultAgeH / 24)}d since verified backup`]

  const proposalsPending = overview?.proposals_pending || 0
  const queueCounts = overview?.queue || {}
  const queueActive = (queueCounts.queued || 0) + (queueCounts.blocked || 0) + (queueCounts.running || 0)

  return (
    <div className="statusbar">
      <span className="sb-item" role="status" aria-live="polite">
        <span className={live ? 'dot live' : 'dot'} aria-hidden="true" />
        {live ? 'watching ~/.claude' : 'stream offline'}
      </span>
      <span className="sb-sep" aria-hidden="true" />
      <span className="sb-item" title="pending proposals">
        proposals <b className={proposalsPending > 0 ? 'sb-accent' : ''}>{proposalsPending}</b>
      </span>
      <span className="sb-item" title="overnight queue (queued + blocked + running)">
        queue <b className={queueActive > 0 ? 'sb-accent' : ''}>{queueActive}</b>
      </span>
      <span className="sb-item" title="active workspace sessions">
        sessions <b>{sessionCount === null ? '—' : sessionCount}</b>
      </span>
      {vaultState && vaultState[0] !== 'off' && (
        <span className="sb-item" role="status" aria-live="polite"
          title="offsite backup — last verified restore">
          <b className={vaultState[0] === 'warn' ? 'sb-accent' : ''}>{vaultState[1]}</b>
        </span>
      )}
      <span className="sb-spacer" />
      <select className="sb-theme" aria-label="Theme" value={theme}
        onChange={(e) => onSetTheme?.(e.target.value)}>
        {THEMES.map((t) => <option key={t.key} value={t.key} title={t.blurb}>{t.name}</option>)}
      </select>
      <button className="sb-kbd" onClick={onOpenKeys} title="Quick keys (?)" aria-label="Open quick keys help">?</button>
      <button className="sb-kbd" onClick={onOpenPalette} title="Command palette (Ctrl/Cmd+K)" aria-label="Open command palette">⌘K</button>
      <span className="sb-version">noirdeck{version ? ` v${version}` : ''}</span>
    </div>
  )
}
