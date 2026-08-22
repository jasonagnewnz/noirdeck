import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  applyAppearance,
  DEFAULTS,
  DENSITIES,
  findKit,
  KITS,
  loadAppearance,
  MODES,
  resolveMode,
  SCALES,
  STORAGE,
  saveAppearance,
} from '../src/ide/appearance.js'

const read = (rel) => readFileSync(join(process.cwd(), rel), 'utf8')
const css = read('src/styles.css')

// Biome formats the stylesheet and normalises attribute selectors to double
// quotes, so these look for the selector rather than for one spelling of it.
const hasSelector = (...pairs) => {
  const body = pairs.map(([attr, value]) => `\\[data-${attr}=["']${value}["']\\]`).join('')
  return new RegExp(`:root${body}\\s*\\{`).test(css)
}

beforeEach(() => {
  localStorage.clear()
  const root = document.documentElement
  for (const attr of ['data-kit', 'data-theme-mode', 'data-density', 'data-scale']) root.removeAttribute(attr)
  root.style.colorScheme = ''
})

describe('the dials and the stylesheet agree', () => {
  // The dials are inert unless the stylesheet has a selector for every value
  // they can take. Nothing else in the build notices when it does not.
  it('has a stylesheet block for every kit, in both modes', () => {
    for (const kit of KITS) {
      expect(hasSelector(['kit', kit.key]), `no base block for ${kit.key}`).toBe(true)
      for (const mode of ['dark', 'light']) {
        expect(hasSelector(['kit', kit.key], ['theme-mode', mode]), `no ${kit.key} ${mode} palette`).toBe(true)
      }
    }
  })

  it('has a stylesheet block for every density other than the kit default', () => {
    for (const kit of KITS) {
      expect(hasSelector(['kit', kit.key], ['density', 'compact']), `no compact block for ${kit.key}`).toBe(true)
    }
    expect(DENSITIES.map((d) => d.key)).toEqual(['comfortable', 'compact'])
  })

  it('has a stylesheet block for every text size other than the default', () => {
    for (const scale of SCALES) {
      if (scale.key === DEFAULTS.scale) continue
      expect(hasSelector(['scale', scale.key]), `no block for text size ${scale.key}`).toBe(true)
    }
  })

  // index.html applies the appearance before the bundle loads, which only works
  // while it accepts exactly the values the module can produce.
  it('matches the allow-lists in the pre-paint script', () => {
    const html = read('index.html')
    for (const [dial, values] of [
      ['kit', KITS],
      ['mode', MODES],
      ['density', DENSITIES],
      ['scale', SCALES],
    ]) {
      const listed = html.match(new RegExp(`${dial}: \\[([^\\]]+)\\]`))
      expect(listed, `${dial} allow-list missing from index.html`).toBeTruthy()
      const keys = listed[1].match(/'([a-z]+)'/g).map((s) => s.replaceAll("'", ''))
      expect(keys.sort()).toEqual(values.map((v) => v.key).sort())
    }
  })

  it('carries no colour of its own', () => {
    const source = read('src/ide/appearance.js')
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})

describe('applyAppearance', () => {
  it('stamps the four dials on the document element', () => {
    applyAppearance({ kit: 'claude', mode: 'light', density: 'compact', scale: 'large' })
    const root = document.documentElement
    expect(root.getAttribute('data-kit')).toBe('claude')
    expect(root.getAttribute('data-theme-mode')).toBe('light')
    expect(root.getAttribute('data-density')).toBe('compact')
    expect(root.getAttribute('data-scale')).toBe('large')
    expect(root.style.colorScheme).toBe('light')
  })

  it('resolves system mode to a concrete mode', () => {
    const result = applyAppearance({ mode: 'system' })
    expect(['dark', 'light']).toContain(result.resolvedMode)
    expect(document.documentElement.getAttribute('data-theme-mode')).toBe(result.resolvedMode)
    // The stored preference survives resolution, or 'system' would become a
    // one-way door the moment it was applied.
    expect(result.mode).toBe('system')
  })

  it('falls back to the default kit rather than stamping an unknown one', () => {
    applyAppearance({ kit: 'no-such-kit' })
    expect(document.documentElement.getAttribute('data-kit')).toBe(DEFAULTS.kit)
  })
})

describe('stored selection', () => {
  it('round-trips through storage', () => {
    saveAppearance({ kit: 'fluent', mode: 'light', density: 'compact', scale: 'small' })
    expect(loadAppearance()).toEqual({ kit: 'fluent', mode: 'light', density: 'compact', scale: 'small' })
  })

  it('drops only the dial it cannot read, not the rest', () => {
    localStorage.setItem(STORAGE.kit, 'a-kit-from-an-older-build')
    localStorage.setItem(STORAGE.mode, 'light')
    const loaded = loadAppearance()
    expect(loaded.kit).toBe(DEFAULTS.kit)
    expect(loaded.mode).toBe('light')
  })

  it('returns the defaults when storage throws', () => {
    const real = Object.getOwnPropertyDescriptor(window, 'localStorage')
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('private browsing')
      },
    })
    try {
      expect(loadAppearance()).toEqual(DEFAULTS)
      expect(() => saveAppearance({ kit: 'claude' })).not.toThrow()
    } finally {
      Object.defineProperty(window, 'localStorage', real)
    }
  })
})

describe('helpers', () => {
  it('findKit never returns undefined', () => {
    expect(findKit('claude').key).toBe('claude')
    expect(findKit('nonsense').key).toBe(DEFAULTS.kit)
    expect(findKit(undefined).key).toBe(DEFAULTS.kit)
  })

  it('resolveMode passes explicit modes through untouched', () => {
    expect(resolveMode('dark')).toBe('dark')
    expect(resolveMode('light')).toBe('light')
  })
})
