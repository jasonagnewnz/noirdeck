import { useState } from 'react'
import { ago, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ViewHead } from '../ui.jsx'

export default function Skills({ bump }) {
  const { data: skills } = useData('/skills', bump)
  const { data: agents } = useData('/agents', bump)
  const [q, setQ] = useState('')
  const ql = q.toLowerCase()
  const match = (s) => !ql || s.name.toLowerCase().includes(ql) || (s.description || '').toLowerCase().includes(ql)
  const fSkills = (skills || []).filter(match)
  const fAgents = (agents || []).filter(match)
  const [skillPage, skillPager] = usePager(fSkills, 50)
  const [agentPage, agentPager] = usePager(fAgents, 50)
  return (
    <>
      <ViewHead
        title="Skills"
        helpId="skills"
        hint="The installed capability surface: what a session can already do without re-prompting. Read-only inventory: new skills arrive through the Proposals view."
      />
      <div className="panel">
        <h2>Search</h2>
        <p className="sechint">One filter across both tables below: matches name or description.</p>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="filter skills and agents…"
          aria-label="Filter skills and agents"
        />
      </div>
      <div className="panel">
        <h2>
          Skills: <b>{fSkills.length}</b>
        </h2>
        <p className="sechint">Reusable procedures a session can invoke as /name: the estate's how-to knowledge.</p>
        <table>
          <caption className="visually-hidden">Installed skills</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Description</th>
              <th scope="col">Model</th>
              <th scope="col" className="num">
                Updated
              </th>
            </tr>
          </thead>
          <tbody>
            {skillPage.map((s) => (
              <tr key={s.dir}>
                <td style={{ whiteSpace: 'nowrap' }}>/{s.name}</td>
                <td className="dim clip" title={s.description}>
                  {s.description}
                </td>
                <td className="faint">{s.model || '—'}</td>
                <td className="dim num">{ago(s.mtime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {skillPager}
      </div>
      <div className="panel">
        <h2>
          Agents: <b>{fAgents.length}</b>
        </h2>
        <p className="sechint">Specialist subagents a session can delegate to, each with its own tool allowance.</p>
        <table>
          <caption className="visually-hidden">Installed subagents</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Description</th>
              <th scope="col">Tools</th>
            </tr>
          </thead>
          <tbody>
            {agentPage.map((a) => (
              <tr key={a.file}>
                <td style={{ whiteSpace: 'nowrap' }}>{a.name}</td>
                <td className="dim clip" title={a.description}>
                  {a.description}
                </td>
                <td className="faint clip" style={{ maxWidth: 180 }}>
                  {a.tools || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {agentPager}
      </div>
    </>
  )
}
