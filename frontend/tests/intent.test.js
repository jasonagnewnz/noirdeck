import { describe, expect, it } from 'vitest'
import { buildIntent } from '../src/intent.js'

const fleet = [
  { name: 'api', path: '/projects/api' },
  { name: 'old-site', path: '/projects/old-site' },
  { name: 'shop', path: '/projects/shop' },
]

describe('intent routing', () => {
  it('routes live coding with runner and repo', () => {
    const intent = buildIntent('fix login in api with codex', '', fleet)
    expect(intent.view).toBe('workspace')
    expect(intent.project).toBe('api')
    expect(intent.runner).toBe('codex')
  })

  it('routes detached task language to queue', () => {
    const intent = buildIntent('run a task in shop tonight with claude', '', fleet)
    expect(intent.view).toBe('queue')
    expect(intent.project).toBe('shop')
    expect(intent.runner).toBe('claude')
  })

  it('routes design capture and keeps the source project', () => {
    const intent = buildIntent('capture design from old-site and apply to shop', 'shop', fleet)
    expect(intent.view).toBe('design')
    expect(intent.project).toBe('shop')
    expect(intent.captureProject).toBe('old-site')
  })
})
