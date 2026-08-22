import React, { useState } from 'react'
import { ago, api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'
import ImprovePanel from './ImprovePanel.jsx'

export default function Quality({ bump }) {
  const { data: board, loading } = useData('/qa', bump)
  const [open, setOpen] = useState(null)
  const [brief, setBrief] = useState(null)
  const [boardPage, boardPager] = usePager(board || [], 25)

  const openBriefing = async (project) => {
    setBrief({ loading: true, project })
    try {
      setBrief(await api(`/briefing/${project}`))
    } catch (e) {
      setBrief({ error: e.message, project })
    }
    // the briefing panel renders above the board: bring it into view
    requestAnimationFrame(() => {
      document.getElementById('qa-briefing')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  // never blank the whole view while the fleet sweep runs: the heading and
  // improver must render immediately; only the board table waits on /qa
  return (
    <>
      <ViewHead
        title="Checks"
        helpId="quality"
        hint="Is each repo actually ready? Every project in the fleet is scored against concrete readiness gates, and a local model quietly proposes small improvements you approve one by one."
      />

      {brief && (
        <div className="panel" id="qa-briefing">
          <h2>
            Briefing: <b>{brief.project}</b>
          </h2>
          <p className="sechint">
            A start-here card for picking this repo up: git state, recent sessions and follow-ons.
          </p>
          {brief.loading && <div className="loading">assembling</div>}
          {brief.error && (
            <div className="err" role="alert">
              {brief.error}
            </div>
          )}
          {brief.kickoff && (
            <>
              <div className="kickoff">{brief.kickoff}</div>
              <div style={{ marginTop: 10 }} className="dim">
                branch <b>{brief.git.branch}</b> · {brief.git.dirty_files} dirty ·{' '}
                {brief.git.has_upstream ? `${brief.git.unpushed_commits} unpushed` : 'no upstream'} · memory files:{' '}
                {brief.memory_files}
              </div>
              {(brief.follow_on || []).length > 0 && (
                <div style={{ marginTop: 10 }}>
                  {brief.follow_on.map((f, i) => (
                    <div key={i}>
                      <span className="chip hot">{f.kind}</span>{' '}
                      <span className="dim">
                        {f.detail}: {f.subject}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <table style={{ marginTop: 10 }}>
                <caption className="visually-hidden">Recent sessions for {brief.project}</caption>
                <tbody>
                  {brief.recent_sessions.map((s) => (
                    <tr key={s.session_id}>
                      <td className="clip">{s.first_prompt || <span className="faint">(system)</span>}</td>
                      <td>{s.open_loop && <span className="pill GAP">open loop</span>}</td>
                      <td className="dim num">{ago(s.mtime)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <div className="btnrow">
            <button type="button" className="act ghost" onClick={() => setBrief(null)}>
              close briefing
            </button>
          </div>
        </div>
      )}

      <div className="panel">
        <h2>Fleet quality board</h2>
        <p className="sechint">
          Every repo scored BLOCKER / GAP / PASS with evidence per gate. Click a row to expand its individual gates;
          "briefing" assembles the start-here card above.
        </p>
        {loading && <div className="loading">evaluating fleet gates</div>}
        {!loading && (
          <>
            <table>
              <caption className="visually-hidden">Quality gate status per project</caption>
              <thead>
                <tr>
                  <th scope="col">Project</th>
                  <th scope="col">Overall</th>
                  <th scope="col">Blockers / gaps</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {boardPage.map((p) => {
                  const blockers = p.gates.filter((g) => g.verdict === 'BLOCKER')
                  const gaps = p.gates.filter((g) => g.verdict === 'GAP')
                  return (
                    <React.Fragment key={p.path}>
                      {/* tabIndex+onKeyDown, not role="button": this stays a real table row so
                      screen readers keep the row/cell structure; Enter/Space still toggle it */}
                      <tr
                        className="row-open"
                        tabIndex={0}
                        aria-expanded={open === p.path}
                        aria-label={`Toggle gate detail for ${p.project}`}
                        onClick={() => setOpen(open === p.path ? null : p.path)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            setOpen(open === p.path ? null : p.path)
                          }
                        }}
                      >
                        <td>{p.project}</td>
                        <td>
                          <span className={`pill ${p.overall}`}>{p.overall}</span>
                        </td>
                        <td className="dim">
                          {blockers.length} blocker(s), {gaps.length} gap(s)
                        </td>
                        <td className="num">
                          <button
                            type="button"
                            className="act ghost"
                            onClick={(e) => {
                              e.stopPropagation()
                              openBriefing(p.project)
                            }}
                          >
                            briefing
                          </button>
                        </td>
                      </tr>
                      {open === p.path && (
                        <tr>
                          <td colSpan={4}>
                            <table>
                              <caption className="visually-hidden">Gates for {p.project}</caption>
                              <tbody>
                                {p.gates.map((g) => (
                                  <tr key={g.id}>
                                    <td style={{ width: 90 }}>
                                      <span className={`pill ${g.verdict}`}>{g.verdict}</span>
                                    </td>
                                    <td>{g.title}</td>
                                    <td className="dim">{g.evidence}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
            {boardPager}
          </>
        )}
      </div>

      <ImprovePanel bump={bump} />
    </>
  )
}
