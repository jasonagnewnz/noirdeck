import { useMemo, useState } from 'react'
import { buildIntent } from './intent.js'

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
  const route = ROUTE_COPY[intent.view] || ROUTE_COPY.workspace
  const who = intent.runner ? RUNNER_LABELS[intent.runner] || intent.runner : 'your usual helper'
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
        {/* Optional, and the placeholder says so: submit only needs a project. The
            old copy read as a requirement ("Try ...") which is why a second, simpler
            front door got built beside it. A `//` comment does not belong inside a JSX
            opening tag — it is not comment syntax there, and it only survived the
            build by luck. */}
        <input
          id="intent-query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Optional — say what you want, or just pick a project and go"
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

      {/* ⛔ FOUR MODE CARDS DELETED 2026-08-19. They offered the same four
          destinations as the bar directly above, which already routes by what you
          type — five front doors on one page is zero front doors. An earlier pass
          deleted a duplicate row of these and kept this one; keeping either was
          the error. The palette (⌘K) still reaches every mode for anyone who wants
          a menu. Do not add them back: if the bar cannot get someone started, fix
          the bar. */}
    </section>
  )
}
