import { Fragment, useState } from 'react'
import { ago, api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'

export default function Sessions({ bump, openWorkspace }) {
  const { data: sessions, loading } = useData('/sessions?limit=400', bump)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)
  const [open, setOpen] = useState(() => new Set())
  const [sessPage, sessPager] = usePager(sessions || [])
  const [hitPage, hitPager] = usePager(hits?.groups || [])
  const search = async (e) => {
    e.preventDefault()
    if (q.length < 3) return setHits(null)
    setOpen(new Set()) // every new search starts collapsed
    setHits(await api(`/history/search?q=${encodeURIComponent(q)}`))
  }
  const toggle = (key) =>
    setOpen((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  return (
    <>
      <ViewHead
        title="History"
        helpId="sessions"
        hint='Every past task, plus "have I asked this before?" search over recorded prompts.'
      />

      <div className="panel">
        <h2>Search your prompt history</h2>
        <p className="sechint">
          Full-text search over every recorded prompt, in every project — find how you phrased it last time before
          asking again.
        </p>
        <form onSubmit={search} style={{ display: 'flex', gap: 8 }}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. wazuh decoder, invoice sync, deploy…"
            aria-label="Search prompt history"
          />
          <button className="act" type="submit">
            search
          </button>
        </form>
        {hits && (
          <>
            <p className="listhead">
              {hits.total} {hits.total === 1 ? 'prompt' : 'prompts'} in {hits.groups.length}{' '}
              {hits.groups.length === 1 ? 'group' : 'groups'}
              {hits.collapsed > 0 && <span className="dim"> — {hits.collapsed} repeats folded in</span>}
            </p>
            <table style={{ marginTop: 10 }}>
              <caption className="visually-hidden">
                Prompt history search results, near-identical prompts grouped
              </caption>
              <thead>
                <tr>
                  <th scope="col">Prompt</th>
                  <th scope="col">Project</th>
                  <th scope="col" className="num">
                    Last asked
                  </th>
                </tr>
              </thead>
              <tbody>
                {hitPage.map((g) => {
                  const expanded = open.has(g.key)
                  return (
                    <Fragment key={g.key}>
                      <tr>
                        <td className="clip">
                          {g.count > 1 ? (
                            <button
                              type="button"
                              className="act ghost rowtoggle"
                              aria-expanded={expanded}
                              onClick={() => toggle(g.key)}
                            >
                              <span aria-hidden="true">{expanded ? '−' : '+'}</span>
                              <span className="clip">{g.display}</span>
                              <span className="pill">{`×${g.count}`}</span>
                            </button>
                          ) : (
                            g.display
                          )}
                        </td>
                        <td className="dim">{g.projects.join(', ')}</td>
                        <td className="dim num">{ago(g.last_ts / 1000)}</td>
                      </tr>
                      {expanded &&
                        g.items.map((r) => (
                          <tr key={`${g.key}:${r.ts}`} className="subrow">
                            <td className="clip indent">{r.display}</td>
                            <td className="dim">{(r.project || '').split('/').pop()}</td>
                            <td className="dim num">{ago(r.ts / 1000)}</td>
                          </tr>
                        ))}
                      {expanded && g.truncated && (
                        <tr className="subrow">
                          <td className="faint indent" colSpan={3}>
                            showing the {g.items.length} most recent of {g.count}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
                {hits.groups.length === 0 && (
                  <tr>
                    <td className="faint">no matches</td>
                  </tr>
                )}
              </tbody>
            </table>
          </>
        )}
        {hits && hitPager}
      </div>

      <div className="panel">
        <h2>Recent sessions</h2>
        <p className="sechint">
          Newest first, across every project. "resume" reopens the session in the Workspace with its context intact; an
          "open loop" pill marks work that looks unfinished.
        </p>
        {loading && <div className="loading">loading</div>}
        <table>
          <caption className="visually-hidden">Recent Claude Code sessions across the estate</caption>
          <thead>
            <tr>
              <th scope="col">Task (first prompt)</th>
              <th scope="col">Project</th>
              <th scope="col">
                <span className="visually-hidden">Status</span>
              </th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
              <th scope="col" className="num">
                Last active
              </th>
            </tr>
          </thead>
          <tbody>
            {sessPage.map((s) => (
              <tr key={s.session_id}>
                <td className="clip" title={s.last_assistant}>
                  {s.first_prompt || <span className="faint">(system)</span>}
                </td>
                <td className="dim">{s.display}</td>
                <td>{s.open_loop && <span className="pill GAP">open loop</span>}</td>
                <td>
                  {s.display !== s.namespace && !s.namespace.includes('--claude-worktrees') && (
                    <button
                      type="button"
                      className="act ghost"
                      onClick={() => openWorkspace({ project: s.display, resume: s.session_id })}
                    >
                      resume
                    </button>
                  )}
                </td>
                <td className="dim num">{ago(s.mtime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sessPager}
      </div>
    </>
  )
}
