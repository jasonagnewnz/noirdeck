// noirdeck built-in themes — the 8 skins from the design-direction deck.
//
// Every theme is a full set of the :root tokens from styles.css; App.jsx writes
// them onto document.documentElement.style so every view resnaps instantly.
// `mode` ('dark' | 'light') is stamped as data-theme-mode on <html> and gates
// the dark-only atmosphere (scanline overlay, vignette gradients, heavy panel
// shadows) in styles.css. `key` is stamped as data-theme for per-theme CSS hooks.
//
// CONTRAST CONTRACT (WCAG 2.1 relative luminance, verified by script — do not
// eyeball edits to these values): on each of --bg / --bg-deep / --panel /
// --panel-2: --ink >= 7:1, --ink-dim / --ink-faint / --amber / --red-text
// >= 4.5:1. --teal / --red / --green are non-text UI (borders, fills, the live
// dot) and carry no small-text guarantee — same rule as the noir default.

const MONO = 'ui-monospace, "Cascadia Code", "JetBrains Mono", "Fira Code", "SF Mono", Menlo, Consolas, monospace'

export const THEME_STORAGE_KEY = 'nd.theme'
export const DEFAULT_THEME_KEY = 'noir'

export const THEMES = [
  {
    key: 'noir',
    name: 'Noir',
    mode: 'dark',
    blurb: 'Warm blacks + blood-crimson signal. The house default.',
    tokens: {
      '--bg': '#0f0c09',
      '--bg-deep': '#0a0807',
      '--panel': '#15120f',
      '--panel-2': '#1c1815',
      '--line': '#2c2620',
      '--line-soft': '#221d18',
      '--ink': '#e6e3d8',
      '--ink-dim': '#a89e92',
      '--ink-faint': '#8a827a',
      '--amber': '#F0525E',
      '--amber-soft': 'rgba(240, 82, 94, 0.14)',
      '--teal': '#8B1A1A',
      '--red': '#CF1D1E',
      '--red-text': '#F25C67',
      '--green': '#7fbf6e',
      '--mono': MONO,
    },
  },
  {
    key: 'instrument',
    name: 'Instrument',
    mode: 'dark',
    blurb: 'Graphite ground, signal-amber accent. The original skin.',
    tokens: {
      '--bg': '#101312',
      '--bg-deep': '#0b0d0c',
      '--panel': '#161a18',
      '--panel-2': '#1d211f',
      '--line': '#2a302d',
      '--line-soft': '#232825',
      '--ink': '#e6e8e3',
      '--ink-dim': '#a5aba4',
      '--ink-faint': '#8a9089',
      '--amber': '#e8a13d',
      '--amber-soft': 'rgba(232, 161, 61, 0.14)',
      '--teal': '#3f7f74',
      '--red': '#cf4d3a',
      '--red-text': '#ff8a75',
      '--green': '#7fbf6e',
      '--mono': MONO,
    },
  },
  {
    key: 'aurora',
    name: 'Aurora',
    mode: 'dark',
    blurb: 'Deep-space blue-black, soft neon cyan with violet undertones.',
    tokens: {
      '--bg': '#0a0e1a',
      '--bg-deep': '#070a13',
      '--panel': '#101728',
      '--panel-2': '#151e33',
      '--line': '#273250',
      '--line-soft': '#1e2740',
      '--ink': '#e3e9f8',
      '--ink-dim': '#a4b0cd',
      '--ink-faint': '#8b95b4',
      '--amber': '#58d3e8',
      '--amber-soft': 'rgba(88, 211, 232, 0.14)',
      '--teal': '#8b7ff0',
      '--red': '#e0507a',
      '--red-text': '#ff85a8',
      '--green': '#6ee7a0',
      '--mono': MONO,
    },
  },
  {
    key: 'brutalist',
    name: 'Brutalist',
    mode: 'dark',
    blurb: 'Near-black concrete, off-white ink, safety-orange accent.',
    tokens: {
      '--bg': '#121212',
      '--bg-deep': '#0b0b0b',
      '--panel': '#1a1a1a',
      '--panel-2': '#212121',
      '--line': '#3a3a3a',
      '--line-soft': '#2b2b2b',
      '--ink': '#f2f0eb',
      '--ink-dim': '#b2b0aa',
      '--ink-faint': '#969490',
      '--amber': '#ff7a1a',
      '--amber-soft': 'rgba(255, 122, 26, 0.14)',
      '--teal': '#6e6e6e',
      '--red': '#e03616',
      '--red-text': '#ff8a66',
      '--green': '#7fbf6e',
      '--mono': MONO,
    },
  },
  {
    key: 'editorial',
    name: 'Editorial',
    mode: 'light',
    blurb: 'Ivory paper, near-black ink, a single bronze accent.',
    tokens: {
      '--bg': '#f6f1e7',
      '--bg-deep': '#ece5d4',
      '--panel': '#fbf8f0',
      '--panel-2': '#f0e9da',
      '--line': '#d5cbb6',
      '--line-soft': '#e1d9c7',
      '--ink': '#211a11',
      '--ink-dim': '#57503f',
      '--ink-faint': '#6b6350',
      '--amber': '#8f5219',
      '--amber-soft': 'rgba(143, 82, 25, 0.12)',
      '--teal': '#7a6a4f',
      '--red': '#b3261e',
      '--red-text': '#a1221b',
      '--green': '#2e7d32',
      '--mono': MONO,
    },
  },
  {
    key: 'botanical',
    name: 'Botanical',
    mode: 'light',
    blurb: 'Warm paper, deep-green accent, humanist calm.',
    tokens: {
      '--bg': '#f7f3e8',
      '--bg-deep': '#ede7d8',
      '--panel': '#fcfaf1',
      '--panel-2': '#f0ecdd',
      '--line': '#d2cdb8',
      '--line-soft': '#e0dcc9',
      '--ink': '#1f261c',
      '--ink-dim': '#4a5443',
      '--ink-faint': '#5d6753',
      '--amber': '#3e6b41',
      '--amber-soft': 'rgba(62, 107, 65, 0.12)',
      '--teal': '#8a6f3d',
      '--red': '#a63a2a',
      '--red-text': '#97301f',
      '--green': '#2e7d32',
      '--mono': MONO,
    },
  },
  {
    key: 'swiss',
    name: 'Swiss',
    mode: 'light',
    blurb: 'Pure white, near-black ink, one strong red. Zero ornament.',
    tokens: {
      '--bg': '#ffffff',
      '--bg-deep': '#f4f4f4',
      '--panel': '#ffffff',
      '--panel-2': '#f7f7f7',
      '--line': '#d8d8d8',
      '--line-soft': '#e9e9e9',
      '--ink': '#141414',
      '--ink-dim': '#3f3f3f',
      '--ink-faint': '#5a5a5a',
      '--amber': '#d6001c',
      '--amber-soft': 'rgba(214, 0, 28, 0.10)',
      '--teal': '#767676',
      '--red': '#c30017',
      '--red-text': '#b8001a',
      '--green': '#1b7a2e',
      '--mono': MONO,
    },
  },
  {
    key: 'neo-material',
    name: 'Neo-Material',
    mode: 'dark',
    blurb: 'Soft dark slate, tactile elevation, muted indigo accent.',
    tokens: {
      '--bg': '#171922',
      '--bg-deep': '#10121a',
      '--panel': '#1d2029',
      '--panel-2': '#242834',
      '--line': '#353b4c',
      '--line-soft': '#2b3040',
      '--ink': '#e4e7f0',
      '--ink-dim': '#a7aec3',
      '--ink-faint': '#8b93ab',
      '--amber': '#8fa0f0',
      '--amber-soft': 'rgba(143, 160, 240, 0.14)',
      '--teal': '#4d5c8f',
      '--red': '#e05561',
      '--red-text': '#ff8a94',
      '--green': '#7fd39a',
      '--mono': MONO,
    },
  },
]

export function loadThemeKey() {
  try {
    const k = localStorage.getItem(THEME_STORAGE_KEY)
    return THEMES.some((t) => t.key === k) ? k : DEFAULT_THEME_KEY
  } catch {
    return DEFAULT_THEME_KEY
  }
}

// Writes the theme's tokens onto <html> and stamps data-theme / data-theme-mode.
// Pure DOM, no React — callable before first paint (App uses useLayoutEffect).
export function applyTheme(key) {
  const theme = THEMES.find((t) => t.key === key) || THEMES[0]
  const root = document.documentElement
  for (const [prop, value] of Object.entries(theme.tokens)) {
    root.style.setProperty(prop, value)
  }
  root.setAttribute('data-theme', theme.key)
  root.setAttribute('data-theme-mode', theme.mode)
  return theme
}
