import { useState } from 'react'
import { ago, api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'

export default function Sessions({ bump, openWorkspace }) {
  const { data: sessions, loading } = useData('/sessions?limit=400', bump)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)
  const [sessPage, sessPager] = usePager(sessions || [])
  const [hitPage, hitPager] = usePager(hits || [])
  const search = async (e) => {
    e.preventDefault()
    if (q.length < 3) return setHits(null)
    setHits(await api(`/history/search?q=${encodeURIComponent(q)}`))
  }
  return (
    <>
      <ViewHead
        title="Sessions & history"
        helpId="sessions"
        hint='Every past task across the estate, and "have I asked this before?" search over all recorded prompts.'
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
          <table style={{ marginTop: 10 }}>
            <caption className="visually-hidden">Prompt history search results</caption>
            <thead>
              <tr>
                <th scope="col">Prompt</th>
                <th scope="col">Project</th>
                <th scope="col" className="num">
                  When
                </th>
              </tr>
            </thead>
            <tbody>
              {hitPage.map((r, i) => (
                <tr key={i}>
                  <td className="clip">{r.display}</td>
                  <td className="dim">{(r.project || '').split('/').pop()}</td>
                  <td className="dim num">{ago(r.ts / 1000)}</td>
                </tr>
              ))}
              {hits.length === 0 && (
                <tr>
                  <td className="faint">no matches</td>
                </tr>
              )}
            </tbody>
          </table>
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
