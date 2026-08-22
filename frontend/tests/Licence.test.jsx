import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LicencePanel } from '../src/views/Settings.jsx'

/**
 * The licence panel.
 *
 * ⛔ WHAT THIS PROTECTS (2026-08-22). There was no way to install a licence key.
 * POST /api/license existed and nothing in the interface called it, so the only
 * route was to craft the request by hand. It did not bite while Early Access
 * ships unlicensed and no key is needed, and it would have been a hard blocker
 * the day enforcement was switched on.
 *
 * The first test is the one that matters most and is the least obvious: the
 * status GET must not carry a request body. api() attaches one whenever any
 * options are passed, and fetch throws on a GET with a body, so the panel built
 * and passed a type check and would have failed the instant anyone opened it.
 */

const status = (extra = {}) => ({
  licensed: false,
  state: 'unlicensed',
  detail: 'No key installed.',
  ...extra,
})

let calls

beforeEach(() => {
  calls = []
  // ⛔ vi.stubGlobal, not a bare assignment. restoreAllMocks only restores spies
  // created with vi.spyOn, so `global.fetch = vi.fn()` leaks the stub into every
  // suite that runs after this one: these tests passed, and two unrelated ones
  // in another file started failing.
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init) => {
      calls.push({ url: String(url), init })
      const body = init?.body ? JSON.parse(init.body) : null
      if (String(url).endsWith('/api/license') && init?.method === 'POST') {
        if (body?.key === 'good-key') {
          return new Response(
            JSON.stringify(
              status({
                licensed: true,
                state: 'active',
                detail: 'Valid until 2027-08-22.',
                email: 'someone@example.com',
                plan: 'commercial',
                expires_at: '2027-08-22T00:00:00+00:00',
              })
            ),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          )
        }
        return new Response(JSON.stringify({ detail: 'signature does not match: key is not genuine' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (String(url).endsWith('/api/license')) {
        return new Response(JSON.stringify(status()), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      // Nothing else is rendered here; the panel owns its own fetch.
      return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const licenceGet = () => calls.find((c) => c.url.endsWith('/api/license') && c.init?.method !== 'POST')

describe('the licence panel', () => {
  it('reads the status without sending a request body', async () => {
    render(<LicencePanel />)
    await waitFor(() => expect(licenceGet()).toBeTruthy())
    // A GET carrying a body throws before it reaches the network.
    expect(licenceGet().init?.body).toBeUndefined()
  })

  it('shows what the server said about the current licence', async () => {
    render(<LicencePanel />)
    expect(await screen.findByText('No key installed.')).toBeInTheDocument()
  })

  it('installs a key and shows who it belongs to', async () => {
    render(<LicencePanel />)
    const field = await screen.findByLabelText('Key')
    await userEvent.type(field, 'good-key')
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))

    expect(await screen.findByText('someone@example.com')).toBeInTheDocument()
    expect(screen.getByText('Valid until 2027-08-22.')).toBeInTheDocument()
    // The field clears, so the next person to look at the screen cannot read it.
    expect(field).toHaveValue('')
  })

  it("surfaces the server's reason rather than a generic failure", async () => {
    render(<LicencePanel />)
    const field = await screen.findByLabelText('Key')
    await userEvent.type(field, 'forged')
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('signature does not match')
  })

  it('cannot submit an empty key', async () => {
    render(<LicencePanel />)
    await screen.findByLabelText('Key')
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
  })
})
