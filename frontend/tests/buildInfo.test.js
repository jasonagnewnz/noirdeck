import { describe, expect, it } from 'vitest'
import { compactDateTime, isoDateTime } from '../src/buildInfo.js'

describe('build info timestamps', () => {
  it('formats a local compact date-time stamp', () => {
    expect(compactDateTime('2026-08-16T04:05:06.000Z')).toMatch(/2026-08-16 \d{2}:\d{2}:\d{2}/)
  })

  it('keeps full ISO timestamps for diagnostics', () => {
    expect(isoDateTime('2026-08-16T04:05:06.000Z')).toBe('2026-08-16T04:05:06.000Z')
    expect(isoDateTime('not-a-date')).toBe('unknown')
  })
})
