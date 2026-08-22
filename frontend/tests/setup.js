import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom has no EventSource; useEvents() opens one on mount. A silent stub keeps
// the SSE seam inert: tests drive refetches through props, not the bus.
class FakeEventSource {
  constructor() {
    this.onopen = null
    this.onerror = null
    this.onmessage = null
  }
  close() {}
}
globalThis.EventSource = FakeEventSource

// jsdom has no scrollIntoView (Help's deep-link scroll uses it).
window.HTMLElement.prototype.scrollIntoView = () => {}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.location.hash = ''
})
