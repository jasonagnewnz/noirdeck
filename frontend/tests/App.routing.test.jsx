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
    expect(await heading('Run later')).toBeInTheDocument()
  })

  it('only the part before the colon names the view (#help:queue → Help)', async () => {
    window.location.hash = '#help:queue'
    render(<App />)
    expect(await heading('Help')).toBeInTheDocument()
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
    expect(await heading('Run later')).toBeInTheDocument()
    await act(async () => {
      window.location.hash = '#help'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(await heading('Help')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 1, name: 'Run later' })).not.toBeInTheDocument()
  })
})

// The rail was trimmed to the daily loop. The risk in hiding a view is hiding
// it *away* — these pin that the moved views are still fully reachable.
describe('primary rail vs settings', () => {
  // exact match, not a prefix regex — "Guide" is a prefix of "Guided Builds"
  const railButton = (name) => screen.queryByRole('button', { name })

  it('keeps the rail to the daily loop plus settings', async () => {
    window.location.hash = '#overview'
    render(<App />)
    await screen.findByText('getting your projects ready')

    for (const name of ['Home', 'Build Live', 'Guided Builds', 'Tasks', 'Review', 'History', 'Guide', 'Settings']) {
      expect(railButton(name)).toBeInTheDocument()
    }
    // the four moved views no longer occupy a slot
    for (const name of ['Design', 'Helpers', 'Knowledge', 'Checks']) {
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
