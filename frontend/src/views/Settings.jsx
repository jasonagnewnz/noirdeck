import { useData } from '../api.js'
import { DENSITIES, KITS, MODES, SCALES } from '../ide/appearance.js'
import { ViewHead } from '../ui.jsx'
import LocalModels from './LocalModels.jsx'

// Everything the daily loop doesn't need. These are not lesser features: they
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

function BackgroundWork({ bump }) {
  const { data } = useData('/scheduler', bump)
  if (!data) return null
  //Nothing in the UI reported this before. Arming expires silently BY DESIGN,
  // so "no tasks ran last night" and "the scheduler is not running at all" look
  // identical from the outside: and the second one is a fault, not a quiet night.
  return (
    <div className="panel">
      <h2>Background work</h2>
      <p className="sechint">
        Whether the recurring jobs are actually being run, and when each is next due. Arming contracts expire on
        purpose, so a job being due is not a promise it will do anything: but a scheduler that is off will never even
        try.
      </p>
      {/* The whole answer, first: a running scheduler with nothing armed runs
          nothing, and vice versa. The API computes will_run so this screen and the
          API can never disagree. */}
      <div style={{ marginBottom: 8 }}>
        {data.will_run ? (
          <span className="pill PASS">unattended work will run</span>
        ) : (
          <span className="pill GAP">nothing will run: {data.blocked_by}</span>
        )}
      </div>
      <div style={{ marginBottom: 8 }}>
        <span className="faint">scheduler: </span>
        {data.enabled ? (
          <span className="pill PASS">running in this process</span>
        ) : (
          <span className="pill GAP">not running here</span>
        )}{' '}
        <span className="dim">· {data.mode}</span>
      </div>
      <div style={{ marginBottom: 8 }}>
        <span className="faint">armed: </span>
        {Object.entries(data.contracts || {}).filter(([, c]) => c.live).length === 0 ? (
          <span className="dim">nothing</span>
        ) : (
          Object.entries(data.contracts || {})
            .filter(([, c]) => c.live)
            .map(([name, c]) => (
              <span key={name} className="pill PASS" style={{ marginRight: 6 }}>
                {name} until {(c.armed_until || '').slice(11, 16)}
              </span>
            ))
        )}
      </div>
      {!data.enabled && (
        <p className="faint">
          In a source checkout the systemd timers own the schedule instead, so this is expected. On an installed copy it
          means nothing recurring will run.
        </p>
      )}
      <table>
        <caption className="visually-hidden">Recurring jobs</caption>
        <tbody>
          {(data.jobs || []).map((j) => (
            <tr key={j.name}>
              <td>
                <code>{j.name}</code>
              </td>
              <td className="dim">{j.schedule}</td>
              <td className="faint">
                {j.next_due ? `next ${j.next_due.slice(0, 16).replace('T', ' ')}` : 'not scheduled here'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const DIALS = [
  { dial: 'kit', label: 'Kit', options: KITS },
  { dial: 'mode', label: 'Mode', options: MODES },
  { dial: 'density', label: 'Density', options: DENSITIES, hint: 'row height and spacing' },
  { dial: 'scale', label: 'Text size', options: SCALES },
]

export default function Settings({ bump, appearance, onSetDial }) {
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
          Four dials rather than a list of skins, because they are independent: any kit works in either mode, at either
          density, at any text size. Applies instantly, remembered on this machine, and every combination is checked for
          readable contrast before it ships.
        </p>
        {DIALS.map(({ dial, label, options, hint }) => (
          <label className="settings-row" key={dial} htmlFor={`appearance-${dial}`}>
            <span>
              {label}
              {hint && <small className="faint"> {hint}</small>}
            </span>
            <select
              id={`appearance-${dial}`}
              value={appearance?.[dial] ?? options[0].key}
              onChange={(e) => onSetDial(dial, e.target.value)}
            >
              {options.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>
        ))}
        <p className="faint">{KITS.find((k) => k.key === appearance?.kit)?.blurb}</p>
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

      <BackgroundWork bump={bump} />

      <LocalModels bump={bump} />

      <div className="panel">
        <h2>Assistants</h2>
        <p className="sechint">Which assistants this machine can run, and the models each one offers.</p>
        {!runtimes && <div className="loading">loading</div>}
        <ul className="tight">
          {(runtimes?.runners || []).map((r) => (
            <li key={r.id}>
              <b>{r.label}</b>{' '}
              {r.available ? (
                <span className="dim">· {(r.models || []).join(', ') || 'no models listed'}</span>
              ) : (
                <span className="faint">· not installed</span>
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
