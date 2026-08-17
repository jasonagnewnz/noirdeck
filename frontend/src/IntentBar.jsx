import { useMemo, useState } from 'react'
import { buildIntent, QUICK_INTENTS } from './intent.js'

const RUNNER_LABELS = {
  claude: 'Claude',
  codex: 'Codex',
  ollama: 'Local',
  grok: 'Grok',
}

const ROUTE_COPY = {
  workspace: { surface: 'Live build', when: 'now', mode: 'guided live' },
  queue: { surface: 'Background task', when: 'later', mode: 'hands-off' },
  design: { surface: 'Design studio', when: 'preview first', mode: 'visual round' },
  overview: { surface: 'Ask Noirdeck', when: 'read-only', mode: 'answer' },
}

export default function IntentBar({ fleet = [], onIntent }) {
  const [project, setProject] = useState('')
  const [query, setQuery] = useState('')
  const intent = useMemo(() => buildIntent(query, project, fleet), [query, project, fleet])
  const primaryProject = project || fleet[0]?.name || ''
  const sourceProject = fleet.find((repo) => repo.name !== primaryProject)?.name || primaryProject
  const route = ROUTE_COPY[intent.view] || ROUTE_COPY.workspace
  const who = intent.runner ? RUNNER_LABELS[intent.runner] || intent.runner : 'your usual helper'
  const demoPaths = useMemo(
    () => [
      {
        key: 'live',
        label: 'Build with me',
        detail: 'Start in a project with a useful first brief.',
        disabled: !primaryProject,
        intent: buildIntent(
          primaryProject ? `summarize ${primaryProject} and suggest the first safe improvement` : '',
          primaryProject,
          fleet
        ),
      },
      {
        key: 'later',
        label: 'Let it run',
        detail: 'Hand off a clear task and come back to the result.',
        disabled: !primaryProject,
        intent: buildIntent(
          primaryProject ? `run a task in ${primaryProject} later: improve the README quick start` : '',
          primaryProject,
          fleet
        ),
      },
      {
        key: 'ui',
        label: 'Improve the look',
        detail: 'Capture a style, choose a kit, compare previews.',
        disabled: !primaryProject,
        intent: buildIntent(
          primaryProject
            ? `capture design from ${sourceProject} and apply to ${primaryProject}`
            : 'capture design and apply a UI',
          primaryProject,
          fleet
        ),
      },
      {
        key: 'ask',
        label: 'Ask what needs work',
        detail: 'Get an answer without changing anything.',
        disabled: false,
        intent: buildIntent('which repos need attention right now?', '', fleet),
      },
    ],
    [fleet, primaryProject, sourceProject]
  )
  const needsProject = intent.kind !== 'ask'
  const canRun = !needsProject || intent.project

  const run = (next = intent) => {
    onIntent?.(next)
  }

  return (
    <section className="intent-hero reveal" aria-labelledby="intent-title">
      <div className="intent-copy">
        <span className="eyebrow">noirdeck.dev · build studio</span>
        <h1 id="intent-title">Build the thing you mean.</h1>
        <p>Describe the outcome. Noirdeck chooses the right helper, asks what matters, and keeps it reviewable.</p>
      </div>

      <form
        className="intent-command"
        onSubmit={(e) => {
          e.preventDefault()
          if (canRun) run()
        }}
      >
        <label className="visually-hidden" htmlFor="intent-project">
          Project
        </label>
        <select id="intent-project" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">Project</option>
          {fleet.map((repo) => (
            <option key={repo.path || repo.name} value={repo.name}>
              {repo.name}
            </option>
          ))}
        </select>

        <label className="visually-hidden" htmlFor="intent-query">
          What do you want to do?
        </label>
        <input
          id="intent-query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='Try "add payments to my booking app" or "make the dashboard feel premium"'
        />

        <button className="act intent-submit" type="submit" disabled={!canRun}>
          {intent.cta}
        </button>
      </form>

      <div className="intent-route" role="status" aria-live="polite">
        <div>
          <span>Project</span>
          <b>{intent.project || (needsProject ? 'choose project' : 'all projects')}</b>
        </div>
        <div>
          <span>Helper</span>
          <b>{who}</b>
        </div>
        <div>
          <span>Timing</span>
          <b>{route.when}</b>
        </div>
        <div>
          <span>Path</span>
          <b>{route.surface}</b>
        </div>
      </div>

      <div className="intent-actions">
        {QUICK_INTENTS.map((action) => (
          <button
            className="intent-action"
            key={action.kind}
            type="button"
            onClick={() => run({ ...buildIntent(action.prompt, project, fleet), ...action, project })}
          >
            <span>{action.label}</span>
            <small>{action.hint}</small>
          </button>
        ))}
      </div>

      <div className="happy-path">
        <span className="happy-kicker">Start here</span>
        {demoPaths.map((path) => (
          <button
            className="happy-step"
            key={path.key}
            type="button"
            disabled={path.disabled}
            onClick={() => run(path.intent)}
          >
            <b>{path.label}</b>
            <span>{path.detail}</span>
            <small>
              {path.intent.view === 'workspace' ? ROUTE_COPY.workspace.mode : ROUTE_COPY[path.intent.view]?.mode}
            </small>
          </button>
        ))}
      </div>
    </section>
  )
}
