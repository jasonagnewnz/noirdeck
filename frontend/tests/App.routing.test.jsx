// The hash router is hand-rolled (no library): the part of the hash before the
// colon names the view, unknown hashes fall back to overview, and hashchange —
// not component state — is the source of truth for back/forward.
import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.jsx'

beforeEach(() => {
  // Views fetch on mount; a forever-pending fetch holds every view in its
  // loading state, which is all routing assertions need.
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise(() => {}))
  )
})

const heading = (name) => screen.findByRole('heading', { level: 1, name })

describe('hash routing', () => {
  it('renders the view named by the hash', async () => {
    window.location.hash = '#queue'
    render(<App />)
    expect(await heading('Tasks')).toBeInTheDocument()
  })

  it('only the part before the colon names the view (#help:queue → Help)', async () => {
    window.location.hash = '#help:queue'
    render(<App />)
    expect(await heading('Guide')).toBeInTheDocument()
  })

  it('falls back to overview on an unknown hash', async () => {
    window.location.hash = '#no-such-view'
    render(<App />)
    // Overview holds its heading until /overview data lands; with fetch
    // pending, its loading marker is the view's identity.
    expect(await screen.findByText('getting your projects ready')).toBeInTheDocument()
  })

  it('follows hashchange events (browser back/forward)', async () => {
    window.location.hash = '#queue'
    render(<App />)
    expect(await heading('Tasks')).toBeInTheDocument()
    await act(async () => {
      window.location.hash = '#help'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(await heading('Guide')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 1, name: 'Tasks' })).not.toBeInTheDocument()
  })
})

// The rail was trimmed to the daily loop. The risk in hiding a view is hiding
// it *away* — these pin that the moved views are still fully reachable.
describe('primary rail vs settings', () => {
  // exact match, not a prefix regex
  const railButton = (name) => screen.queryByRole('button', { name })

  it('keeps the rail to the daily loop plus settings', async () => {
    window.location.hash = '#overview'
    render(<App />)
    await screen.findByText('getting your projects ready')

    for (const name of ['Home', 'Build Live', 'Builds', 'Tasks', 'Review', 'History', 'Settings']) {
      expect(railButton(name)).toBeInTheDocument()
    }
    // the four moved views no longer occupy a slot
    for (const name of ['Design', 'Skills', 'Memories', 'Checks', 'Guide']) {
      expect(railButton(name)).not.toBeInTheDocument()
    }
  })

  it('still routes to a moved view by its hash', async () => {
    window.location.hash = '#memories'
    render(<App />)
    // Knowledge holds its heading until /memories lands; with fetch pending,
    // its loading marker is the view's identity (same as Overview above).
    expect(await screen.findByText('reading memory namespaces')).toBeInTheDocument()
  })

  it('settings lists every moved view as a link', async () => {
    window.location.hash = '#settings'
    render(<App />)
    expect(await heading('Settings')).toBeInTheDocument()
    for (const [name, hash] of [
      ['Design', '#design'],
      ['Helpers', '#skills'],
      ['Knowledge', '#memories'],
      ['Checks', '#quality'],
    ]) {
      expect(screen.getByRole('link', { name: new RegExp(name) })).toHaveAttribute('href', hash)
    }
  })
})

// ⛔ THE INVARIANT THAT WAS MISSING. Six of twelve nav items used to call the same
// thing two different names — click "Knowledge", land on "Memories"; click "Tasks",
// land on "Run later". Nothing caught it because each half was individually
// correct. Pin the RELATIONSHIP, not the strings: whatever the rail says, the page
// it opens must say the same word.
describe('one word per concept', () => {
  const RAIL = ['Home', 'Build Live', 'Builds', 'Tasks', 'Review', 'History']

  it.each(RAIL)('the rail label "%s" matches the heading of the view it opens', async (label) => {
    window.location.hash = ''
    render(<App />)
    const button = await screen.findByRole('button', { name: label })
    await act(async () => button.click())
    // Home is the only one allowed to differ: its H1 is the product hero, not a
    // view title. Everything else must echo its own rail label exactly.
    if (label === 'Home') return
    expect(await screen.findByRole('heading', { level: 1, name: label })).toBeInTheDocument()
  })
})

// Deleting from the rail must not delete the destination. The Guide left the daily
// loop because a manual in primary navigation is the UI admitting it needs one —
// but it is still a first-class view and must stay reachable by hash, or "demoted"
// silently became "removed".
describe('demoted, not deleted', () => {
  it('the Guide is still reachable by its own hash', async () => {
    window.location.hash = '#help'
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Guide' })).toBeInTheDocument()
  })
})
