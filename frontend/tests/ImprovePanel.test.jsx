import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ImprovePanel from '../src/views/ImprovePanel.jsx'

// Per-path fetch mock: ImprovePanel loads /api/improve and /api/fleet on mount.
const respond = (payload) => ({ ok: true, json: async () => payload })

const IMPROVE = {
  armed: true,
  model: 'coder:7b',
  model_available: true,
  models: [],
  repos: [{ id: 1, project: 'duly', enabled: true, model: null }],
  changes: [],
}
const FLEET = [
  { name: 'duly', branch: 'main' },
  { name: 'wordtally', branch: 'dev' },
]

let calls
beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url, opts) => {
      calls.push([url, opts])
      if (url === '/api/fleet') return Promise.resolve(respond(FLEET))
      if (url.startsWith('/api/improve/')) return Promise.resolve(respond({ ok: true }))
      return Promise.resolve(respond(IMPROVE))
    })
  )
})

const change = (over = {}) => ({
  id: 7,
  project: 'wordtally',
  kind: 'docstrings',
  target_file: 'cli.py',
  status: 'proposed',
  branch: 'improve/x',
  summary: 'tidy docstrings',
  tests: 'passed',
  diff: '--- a\n+++ b',
  created_at: '2026-08-16T10:00:00',
  ...over,
})

describe('ImprovePanel', () => {
  it('fail-closed: run now is disabled while disarmed, and says why', async () => {
    IMPROVE.armed = false
    render(<ImprovePanel bump={0} />)
    const run = await screen.findByRole('button', { name: 'run now' })
    expect(run).toBeDisabled()
    expect(run.title).toMatch(/disarmed/)
    IMPROVE.armed = true
  })

  it('run now is enabled when armed and the model is reachable', async () => {
    render(<ImprovePanel bump={0} />)
    expect(await screen.findByRole('button', { name: 'run now' })).toBeEnabled()
  })

  // The assertion that matters is unchanged: the user must be told which branch the
  // merge lands on, because it is the repo's CURRENT branch and not always main. Only
  // the MECHANISM changed — the branch is now named on the button and in the inline
  // confirmation, instead of inside a window.confirm nobody could style or read.
  it('the merge control names the repo CURRENT branch from fleet, not main', async () => {
    IMPROVE.changes = [change()]
    render(<ImprovePanel bump={0} />)
    // the branch is visible BEFORE any click
    const button = await screen.findByRole('button', { name: /merge into dev/i })
    fireEvent.click(button)
    // and again in the inline confirmation
    expect(await screen.findByText(/Merge into dev\?/i)).toBeInTheDocument()
    // declining must not post the merge
    fireEvent.click(await screen.findByRole('button', { name: 'No' }))
    expect(calls.some(([u]) => u === '/api/improve/changes/7')).toBe(false)
    IMPROVE.changes = []
  })

  it('confirmed merge posts the action to the change endpoint', async () => {
    IMPROVE.changes = [change()]
    render(<ImprovePanel bump={0} />)
    fireEvent.click(await screen.findByRole('button', { name: /merge into dev/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Yes' }))
    await screen.findByText('change #7 merged')
    const [, opts] = calls.find(([u]) => u === '/api/improve/changes/7')
    expect(JSON.parse(opts.body)).toEqual({ action: 'merge' })
    IMPROVE.changes = []
  })

  it('folds changes beyond the cap behind an "older" disclosure', async () => {
    IMPROVE.changes = Array.from({ length: 12 }, (_, i) => change({ id: i + 1, status: 'merged' }))
    render(<ImprovePanel bump={0} />)
    expect(await screen.findByText('2 older changes')).toBeInTheDocument()
    IMPROVE.changes = []
  })

  it('only unmapped fleet repos are offered for mapping', async () => {
    render(<ImprovePanel bump={0} />)
    const select = await screen.findByLabelText('Map a repo')
    const names = Array.from(select.options).map((o) => o.value)
    expect(names).toContain('wordtally')
    expect(names).not.toContain('duly')
  })
})
