import { ChevronIcon, ICONS } from './icons.jsx'

// Left activity bar — compact product navigation, expandable into a labelled
// sidebar. Tooltip via native title attr when collapsed; active state = the
// single signal color.
export default function ActivityBar({ views, active, badges, onSelect, expanded, onToggleExpanded }) {
  return (
    <aside className={`actbar ${expanded ? 'expanded' : ''}`}>
      <div className="actbar-mark" title="noirdeck.dev">
        <span>n</span>
        <em>d</em>
      </div>
      {expanded && (
        <div className="actbar-wordmark">
          <span>
            noir<em>deck</em>
          </span>
          <small>build studio</small>
        </div>
      )}
      <nav className="actbar-nav" aria-label="Primary">
        {views.map(([key, label], i) => {
          const Icon = ICONS[key]
          const count = badges[key] || 0
          // only the first ten views get digit shortcuts (1–9 then 0);
          // view 11+ (help) is reachable by click/palette only
          const digit = i < 10 ? (i + 1) % 10 : null
          const isOn = active === key
          return (
            <button
              type="button"
              key={key}
              className={isOn ? 'on' : ''}
              title={expanded ? undefined : digit === null ? label : `${label} (${digit})`}
              aria-label={count > 0 ? `${label}, ${count} pending` : label}
              aria-current={isOn ? 'page' : undefined}
              onClick={() => onSelect(key)}
            >
              <span className="actbar-icon">{Icon && <Icon aria-hidden="true" focusable="false" />}</span>
              {expanded && <span className="actbar-label">{label}</span>}
              {count > 0 && (
                <span className="actbar-badge" aria-hidden="true">
                  {count > 99 ? '99+' : count}
                </span>
              )}
              {expanded && count === 0 && digit !== null && <kbd className="actbar-key">{digit}</kbd>}
            </button>
          )
        })}
      </nav>
      {/* Settings sits below the rail, not in it — everything the daily loop
          doesn't need lives behind here, one click away rather than competing
          for a slot. Digit 0 opens it. */}
      <nav className="actbar-nav actbar-foot" aria-label="Settings">
        <button
          type="button"
          className={active === 'settings' ? 'on' : ''}
          title={expanded ? undefined : 'Settings (0)'}
          aria-label="Settings"
          aria-current={active === 'settings' ? 'page' : undefined}
          onClick={() => onSelect('settings')}
        >
          <span className="actbar-icon">
            <ICONS.settings aria-hidden="true" focusable="false" />
          </span>
          {expanded && <span className="actbar-label">Settings</span>}
          {expanded && <kbd className="actbar-key">0</kbd>}
        </button>
      </nav>
      <button
        type="button"
        className="actbar-expand"
        title={expanded ? 'Collapse sidebar (Ctrl+B)' : 'Expand sidebar (Ctrl+B)'}
        aria-label={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
        aria-expanded={expanded}
        onClick={onToggleExpanded}
      >
        <ChevronIcon className={expanded ? 'flip' : ''} aria-hidden="true" focusable="false" />
        {expanded && <span>collapse</span>}
      </button>
    </aside>
  )
}
