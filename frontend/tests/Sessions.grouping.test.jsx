// History search collapses near-identical prompts into one row each. The
// default matters: a habit typed 56 times must arrive as ONE row, expandable,
// not as 56 rows the reader has to scroll past.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Sessions from '../src/views/Sessions.jsx'

const GROUPED = {
  total: 4,
  collapsed: 2,
  groups: [
    {
      key: 'deploy the website',
      display: 'deploy the website',
      count: 1,
      projects: ['site'],
      last_ts: 4000,
      first_ts: 4000,
      items: [{ display: 'deploy the website', project: '/p/site', ts: 4000 }],
      truncated: false,
    },
    {
      key: 'commit these changes',
      display: 'commit these changes',
      count: 3,
      projects: ['a', 'b'],
      last_ts: 3000,
      first_ts: 1000,
      items: [
        { display: 'commit these changes', project: '/p/a', ts: 3000 },
        { display: 'Commit these changes.', project: '/p/b', ts: 2000 },
        { display: 'commit  these   changes', project: '/p/a', ts: 1000 },
      ],
      truncated: false,
    },
  ],
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url) => {
      const body = String(url).includes('/history/search') ? GROUPED : []
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
    })
  )
})

const runSearch = async (user) => {
  await user.type(screen.getByLabelText('Search prompt history'), 'commit')
  await user.click(screen.getByRole('button', { name: 'search' }))
}

describe('grouped prompt history', () => {
  it('shows one row per group, collapsed, with the repeat count', async () => {
    const user = userEvent.setup()
    render(<Sessions bump={0} openWorkspace={() => {}} />)
    await runSearch(user)

    const toggle = await screen.findByRole('button', { expanded: false })
    expect(within(toggle).getByText('×3')).toBeInTheDocument()
    // the three variants are folded away until asked for
    expect(screen.queryByText('Commit these changes.')).not.toBeInTheDocument()
  })

  it('says how much noise it folded away', async () => {
    const user = userEvent.setup()
    render(<Sessions bump={0} openWorkspace={() => {}} />)
    await runSearch(user)
    expect(await screen.findByText(/4 prompts in 2 groups/)).toBeInTheDocument()
    expect(screen.getByText(/2 repeats folded in/)).toBeInTheDocument()
  })

  it('expands a group to its individual prompts on demand', async () => {
    const user = userEvent.setup()
    render(<Sessions bump={0} openWorkspace={() => {}} />)
    await runSearch(user)

    const before = screen.getAllByRole('row').length
    await user.click(await screen.findByRole('button', { expanded: false }))
    expect(await screen.findByText('Commit these changes.')).toBeInTheDocument()
    // all three members appear as their own rows
    expect(screen.getAllByRole('row')).toHaveLength(before + 3)
    expect(screen.getByRole('button', { expanded: true })).toBeInTheDocument()
  })

  it('a one-off prompt gets a plain row, not a pointless toggle', async () => {
    const user = userEvent.setup()
    render(<Sessions bump={0} openWorkspace={() => {}} />)
    await runSearch(user)
    await screen.findByText('deploy the website')
    // only the ×3 group is expandable
    expect(screen.getAllByRole('button', { expanded: false })).toHaveLength(1)
  })
})
