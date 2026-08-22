import { useEffect, useState } from 'react'
import {
  compactDateTime,
  FRONTEND_BUILT_AT,
  FRONTEND_COMMIT,
  FRONTEND_LOADED_AT,
  FRONTEND_VERSION,
  isoDateTime,
} from '../buildInfo.js'
import { KITS } from './appearance.js'
import { getJSON } from './ideApi.js'

// Bottom status bar: live state, decision counts, active build count
// (self-polled), the ⌘K launcher, and build identity for both frontend/backend
// so stale bundles are obvious.
export default function StatusBar({
  live,
  overview,
  onOpenPalette,
  onOpenKeys,
  appearance,
  onSetDial,
  dockOpen,
  onToggleDock,
}) {
  const [sessionCount, setSessionCount] = useState(null)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      getJSON('/workspace')
        .then((rows) => alive && setSessionCount(Array.isArray(rows) ? rows.length : 0))
        .catch(() => {
          /* leave last-known value */
        })
    load()
    const t = setInterval(load, 15000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  useEffect(() => {
    let alive = true
    const load = () =>
      getJSON('/health')
        .then((d) => alive && setHealth(d))
        .catch(() => {
          /* leave last-known health */
        })
    load()
    const t = setInterval(load, 60000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const [vault, setVault] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () =>
      getJSON('/vault')
        .then((d) => alive && setVault(d))
        .catch(() => {
          /* leave last-known */
        })
    load()
    const t = setInterval(load, 10 * 60 * 1000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])
  const vaultAgeH = vault?.last_verified ? (Date.now() - new Date(vault.last_verified).getTime()) / 3600000 : null
  const vaultState = !vault
    ? null
    : !vault.configured
      ? ['off', 'vault off']
      : vaultAgeH === null
        ? ['warn', 'vault: no verified backup yet']
        : vaultAgeH <= 48
          ? ['ok', `vault ✓ ${vaultAgeH < 1 ? '<1h' : `${Math.round(vaultAgeH)}h`}`]
          : ['warn', `vault ! ${Math.round(vaultAgeH / 24)}d since verified backup`]

  const proposalsPending = overview?.proposals_pending || 0
  const queueCounts = overview?.queue || {}
  const queueActive = (queueCounts.queued || 0) + (queueCounts.blocked || 0) + (queueCounts.running || 0)
  const frontendStamp = compactDateTime(FRONTEND_BUILT_AT)
  const apiStamp = compactDateTime(health?.server_started_at)
  const versionLabel = [
    `ui v${FRONTEND_VERSION} ${frontendStamp}`,
    health?.version ? `api v${health.version} ${apiStamp}` : 'api offline',
  ].join(' · ')
  const versionTitle = [
    `Frontend version: ${FRONTEND_VERSION}`,
    `Frontend built: ${isoDateTime(FRONTEND_BUILT_AT)}`,
    `Frontend loaded: ${isoDateTime(FRONTEND_LOADED_AT)}`,
    FRONTEND_COMMIT ? `Frontend commit: ${FRONTEND_COMMIT}` : null,
    health?.version ? `Backend version: ${health.version}` : 'Backend version: offline',
    `Backend started: ${isoDateTime(health?.server_started_at)}`,
    `Backend now: ${isoDateTime(health?.server_now)}`,
    health?.frontend_dir ? `Backend frontend dir: ${health.frontend_dir}` : null,
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <div className="statusbar">
      <span className="sb-item" role="status" aria-live="polite" title="local event stream">
        <span className={live ? 'dot live' : 'dot'} aria-hidden="true" />
        {live ? 'live' : 'offline'}
      </span>
      <span className="sb-sep" aria-hidden="true" />
      <span className="sb-item" title="changes waiting for your decision">
        review <b className={proposalsPending > 0 ? 'sb-accent' : ''}>{proposalsPending}</b>
      </span>
      <span className="sb-item" title="background tasks: queued + blocked + running">
        tasks <b className={queueActive > 0 ? 'sb-accent' : ''}>{queueActive}</b>
      </span>
      <span className="sb-item" title="active live build sessions">
        active <b>{sessionCount === null ? '—' : sessionCount}</b>
      </span>
      {vaultState && vaultState[0] !== 'off' && (
        <span className="sb-item" role="status" aria-live="polite" title="offsite backup: last verified restore">
          <b className={vaultState[0] === 'warn' ? 'sb-accent' : ''}>{vaultState[1]}</b>
        </span>
      )}
      <span className="sb-spacer" />
      <button
        type="button"
        className={`sb-kbd${dockOpen ? ' is-on' : ''}`}
        onClick={onToggleDock}
        aria-pressed={!!dockOpen}
        title="Terminal panel (Ctrl+`)"
      >
        Terminal
      </button>
      {/* The kit is the one appearance dial worth a permanent slot. Mode,
          density and text size live in Settings with the rest of them. */}
      <select
        className="sb-theme"
        aria-label="Interface kit"
        value={appearance?.kit ?? 'carbon'}
        onChange={(e) => onSetDial?.('kit', e.target.value)}
      >
        {KITS.map((kit) => (
          <option key={kit.key} value={kit.key} title={kit.blurb}>
            {kit.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="sb-kbd"
        onClick={onOpenKeys}
        title="Quick keys (?)"
        aria-label="Open quick keys help"
      >
        ?
      </button>
      <button
        type="button"
        className="sb-kbd"
        onClick={onOpenPalette}
        title="Command palette (Ctrl/Cmd+K)"
        aria-label="Open command palette"
      >
        ⌘K
      </button>
      <span className="sb-version" title={versionTitle}>
        noirdeck.dev · {versionLabel}
      </span>
    </div>
  )
}
