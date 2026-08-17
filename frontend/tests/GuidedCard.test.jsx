import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GuidedCard from '../src/views/guided/GuidedCard.jsx'

const build = (over = {}) => ({
  id: 3,
  name: 'wordtally',
  status: 'running',
  phase: 'build',
  log: [],
  plan_summary: '',
  question: null,
  acceptance: [],
  evidence: null,
  ...over,
})

let calls
beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url, opts) => {
      calls.push([url, opts])
      return Promise.resolve({ ok: true, json: async () => ({ ok: true }) })
    })
  )
})

const noop = () => {}

describe('GuidedCard stepper', () => {
  it('a retried-then-done phase reads as finished, not stuck (v0.18 fix)', () => {
    // The phase log carries every attempt; the chip must judge a phase by its
    // BEST outcome, not its first.
    const b = build({
      phase: 'build',
      log: [
        { phase: 'plan', status: 'failed', model: 'm', seconds: 1, qa_overall: '-', tokens: 0, summary: 's' },
        { phase: 'plan', status: 'done', model: 'm', seconds: 1, qa_overall: '-', tokens: 0, summary: 's' },
      ],
    })
    render(<GuidedCard b={b} refresh={noop} openWorkspace={noop} />)
    expect(screen.getByLabelText('Designing it — finished')).toBeInTheDocument()
    expect(screen.getByLabelText('Writing the code — happening now')).toBeInTheDocument()
  })

  it('a blocked build marks the active phase stuck and offers continue', () => {
    render(<GuidedCard b={build({ status: 'blocked', phase: 'test' })} refresh={noop} openWorkspace={noop} />)
    expect(screen.getByText('Needs your attention')).toBeInTheDocument()
    expect(screen.getByLabelText('Testing until it passes — stuck, needs your attention')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'continue this build' })).toBeInTheDocument()
  })

  it('a running build offers stop, not continue', () => {
    render(<GuidedCard b={build()} refresh={noop} openWorkspace={noop} />)
    expect(screen.getByRole('button', { name: 'stop this build' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'continue this build' })).not.toBeInTheDocument()
  })
})

describe('GuidedCard plan gate', () => {
  const gated = () => build({ status: 'awaiting_plan', phase: 'plan', plan_summary: 'Step 1. Step 2.' })

  it('approve posts the decision to the plan endpoint', async () => {
    const refresh = vi.fn()
    render(<GuidedCard b={gated()} refresh={refresh} openWorkspace={noop} />)
    fireEvent.click(screen.getByRole('button', { name: 'Approve — start building' }))
    await vi.waitFor(() => expect(refresh).toHaveBeenCalled())
    const [url, opts] = calls.find(([u]) => u === '/api/builds/3/plan')
    expect(url).toBe('/api/builds/3/plan')
    expect(JSON.parse(opts.body)).toEqual({ action: 'approve', feedback: '' })
  })

  it('request-changes needs feedback text before it can send', async () => {
    render(<GuidedCard b={gated()} refresh={noop} openWorkspace={noop} />)
    fireEvent.click(screen.getByRole('button', { name: 'Request changes' }))
    const send = screen.getByRole('button', { name: 'Send changes back' })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('What should change?'), { target: { value: 'smaller scope' } })
    expect(send).toBeEnabled()
    fireEvent.click(send)
    await vi.waitFor(() => expect(calls.some(([u]) => u === '/api/builds/3/plan')).toBe(true))
    const [, opts] = calls.find(([u]) => u === '/api/builds/3/plan')
    expect(JSON.parse(opts.body)).toEqual({ action: 'revise', feedback: 'smaller scope' })
  })
})

describe('GuidedCard acceptance evidence', () => {
  it('standard checks pass only when the evidence backs them', () => {
    const b = build({
      status: 'attention',
      phase: 'complete',
      acceptance: [
        { id: 'std-tests', kind: 'standard', text: 't' },
        { id: 'std-gates', kind: 'standard', text: 'g' },
        { id: 'std-run', kind: 'standard', text: 'r' },
      ],
      evidence: {
        tests: '35 passed',
        qa_overall: 'BLOCKER',
        commit_count: 4,
        commits: [],
        phases: [{ phase: 'test', status: 'done', seconds: 10, tokens: 1 }],
        // finish phase absent → std-run must read "needs a look"
      },
    })
    render(<GuidedCard b={b} refresh={noop} openWorkspace={noop} />)
    const rows = screen.getAllByText(/checked ✓|needs a look/)
    expect(rows.map((r) => r.textContent)).toEqual(['checked ✓', 'needs a look', 'needs a look'])
  })
})
