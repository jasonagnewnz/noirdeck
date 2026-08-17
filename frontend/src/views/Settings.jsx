import { useData } from '../api.js'
import { THEMES } from '../ide/themes.js'
import { ViewHead } from '../ui.jsx'

// Everything the daily loop doesn't need. These are not lesser features — they
// are lower-frequency ones, and putting them here keeps the rail honest about
// what you actually reach for. Each still has its own #hash and works as a
// direct link or bookmark.
const ADVANCED = [
  {
    hash: '#design',
    name: 'Design',
    blurb: 'Propose visual directions for a project, compare them side by side, then apply one.',
  },
  {
    hash: '#skills',
    name: 'Helpers',
    blurb: 'Every skill installed for your assistant, with what triggers it.',
  },
  {
    hash: '#memories',
    name: 'Knowledge',
    blurb: 'Your memory notes across every project, plus the tidy-up that finds duplicates and dead links.',
  },
  {
    hash: '#quality',
    name: 'Checks',
    blurb: 'Repo health across the fleet, and the local-model pass that proposes small improvements.',
  },
]

export default function Settings({ bump, theme, onSetTheme }) {
  const { data: health } = useData('/health', bump)
  const { data: runtimes } = useData('/workspace/runtimes', bump)
  const claude = runtimes?.runners?.find((r) => r.id === 'claude')

  return (
    <>
      <ViewHead
        title="Settings"
        helpId="settings"
        hint="The less-used tools, and the switches you set once and forget."
      />

      <div className="panel">
        <h2>More tools</h2>
        <p className="sechint">
          Moved out of the sidebar to keep it to the things you use every session. Everything here still works as a
          direct link.
        </p>
        <div className="settings-grid">
          {ADVANCED.map((item) => (
            <a className="settings-card" href={item.hash} key={item.hash}>
              <b>{item.name}</b>
              <span className="dim">{item.blurb}</span>
            </a>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2>Appearance</h2>
        <p className="sechint">
          Applies instantly and is remembered on this machine. Every theme is checked for readable contrast.
        </p>
        <label className="settings-row" htmlFor="theme-select">
          <span>Theme</span>
          <select id="theme-select" value={theme} onChange={(e) => onSetTheme(e.target.value)}>
            {THEMES.map((t) => (
              <option key={t.key} value={t.key}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <p className="faint">{THEMES.find((t) => t.key === theme)?.blurb}</p>
      </div>

      <div className="panel">
        <h2>Automation</h2>
        <p className="sechint">
          Nothing runs on its own until you arm it, and every arming expires. Turn things on from the task list, where
          you can see what they would do.
        </p>
        <div style={{ marginBottom: 8 }}>
          <span className="faint">background work: </span>
          {health?.mining_armed ? (
            <span className="pill running">note-finding armed</span>
          ) : (
            <span className="pill">note-finding off</span>
          )}{' '}
          {health?.overnight_armed ? (
            <span className="pill running">overnight armed</span>
          ) : (
            <span className="pill">overnight off</span>
          )}
        </div>
        <a className="act ghost" href="#queue">
          arm or disarm in Tasks →
        </a>
      </div>

      <div className="panel">
        <h2>Assistants</h2>
        <p className="sechint">Which assistants this machine can run, and the models each one offers.</p>
        {!runtimes && <div className="loading">loading</div>}
        <ul className="tight">
          {(runtimes?.runners || []).map((r) => (
            <li key={r.id}>
              <b>{r.label}</b>{' '}
              {r.available ? (
                <span className="dim">— {(r.models || []).join(', ') || 'no models listed'}</span>
              ) : (
                <span className="faint">— not installed</span>
              )}
            </li>
          ))}
        </ul>
        {claude?.default_model && (
          <p className="faint" style={{ marginTop: 6 }}>
            Default for new sessions: <code>{claude.default_model}</code>
          </p>
        )}
      </div>

      <div className="panel">
        <h2>About</h2>
        <ul className="tight">
          <li>
            <span className="dim">version</span> <code>{health?.version || '—'}</code>
          </li>
          <li>
            <span className="dim">assistant folder</span> <code>{health?.claude_dir || '—'}</code>
          </li>
        </ul>
        <p className="faint" style={{ marginTop: 6 }}>
          Backups, and exactly what they copy, are on the home page.
        </p>
      </div>
    </>
  )
}
