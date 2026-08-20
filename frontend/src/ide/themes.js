// noirdeck built-in themes — the pro default plus the skins from the design-direction deck.
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
export const DEFAULT_THEME_KEY = 'mono-dark'

export const THEMES = [
  {
    key: 'mono-dark',
    name: 'Mono Dark',
    mode: 'dark',
    blurb: 'Black and white, one crimson signal. The starting UI.',
    tokens: {
      // Structure is pure greyscale so the single accent carries all the
      // meaning: if something is crimson, it wants you.
      '--bg': '#0b0b0b',
      '--bg-deep': '#060606',
      '--panel': '#111111',
      '--panel-2': '#171717',
      '--line': '#272727',
      '--line-soft': '#1d1d1d',
      '--ink': '#f4f4f4',
      '--ink-dim': '#a8a8a8',
      '--ink-faint': '#8c8c8c',
      '--amber': '#F0525E',
      '--amber-soft': 'rgba(240, 82, 94, 0.14)',
      '--teal': '#8B1A1A',
      '--red': '#CF1D1E',
      '--red-text': '#F25C67',
      '--green': '#8fbf8a',
      '--mono': MONO,
    },
  },
  {
    key: 'mono-light',
    name: 'Mono Light',
    mode: 'light',
    blurb: 'White paper, black type, crimson signal. Daylight and demos.',
    tokens: {
      '--bg': '#ffffff',
      '--bg-deep': '#f2f2f2',
      '--panel': '#fafafa',
      '--panel-2': '#f4f4f4',
      '--line': '#dddddd',
      '--line-soft': '#ebebeb',
      '--ink': '#111111',
      '--ink-dim': '#4d4d4d',
      '--ink-faint': '#616161',
      '--amber': '#8B1A1A',
      '--amber-soft': 'rgba(139, 26, 26, 0.10)',
      '--teal': '#8B1A1A',
      '--red': '#CF1D1E',
      '--red-text': '#A0121C',
      '--green': '#2f7d32',
      '--mono': MONO,
    },
  },
  // ⛔ NINE THEMES DELETED 2026-08-19: pro, noir, instrument, aurora, brutalist,
  // editorial, botanical, swiss, neo-material. Nobody asked for eleven skins, they cost
  // a contrast-checking script in CI to keep honest, and the multiplicity caused a real
  // defect — in two of them the ACCENT was red, so an alarm panel rendered
  // indistinguishable from ordinary UI until a screenshot caught it. One dark and one
  // light is the defensible set: light mode is an accessibility need, the rest were
  // taste. Any skin added back must justify its own contrast budget.
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
