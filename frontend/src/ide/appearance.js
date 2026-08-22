// Appearance: four independent dials over one token vocabulary.
//
// This module carries no colour. Palettes, shape and type live in styles.css
// under [data-kit] / [data-theme-mode] selectors, so the browser paints the
// correct kit on the first frame instead of waiting for the bundle. What lives
// here is the metadata, the stored selection, and the code that stamps it.
//
//   kit      carbon | fluent | claude    type, shape and the accent family
//   mode     dark | light | system       surface and text ramps only
//   density  comfortable | compact       row height and the spacing unit
//   scale    small | normal | large       base UI font size
//
// The dials are orthogonal, which is why three kits cover six palettes without
// six lists to keep in step. Density and scale are accessibility, not taste.
//
// Colour rules are enforced by ops/check-contrast.mjs in CI: a text token must
// clear its WCAG ratio on every surface, and --accent must be perceptually
// distinct from --danger. That second rule exists because an earlier set of
// themes let the accent be red, which made an alarm panel look like ordinary UI.

export const KITS = [
  {
    key: 'carbon',
    name: 'Carbon',
    blurb: 'Square corners, an eight-pixel grid, the tightest density of the three.',
  },
  {
    key: 'fluent',
    name: 'Fluent',
    blurb: 'Cool greys, layered depth, softly rounded. Familiar from Windows and Office.',
  },
  {
    key: 'claude',
    name: 'Claude',
    blurb: 'Warm neutrals and a clay accent. Calm rather than industrial.',
  },
]

export const MODES = [
  { key: 'system', name: 'Match system' },
  { key: 'dark', name: 'Dark' },
  { key: 'light', name: 'Light' },
]

// Density changes the two tokens that decide how much room a row takes. Every
// other measurement derives from them, so this is one dial, not a second theme.
export const DENSITIES = [
  { key: 'comfortable', name: 'Comfortable' },
  { key: 'compact', name: 'Compact' },
]

// Three named steps rather than a slider: a continuous value would have to be
// computed in JavaScript, and anything computed in JavaScript cannot be applied
// before the first paint.
export const SCALES = [
  { key: 'small', name: 'Small' },
  { key: 'normal', name: 'Normal' },
  { key: 'large', name: 'Large' },
]

export const DEFAULTS = { kit: 'carbon', mode: 'dark', density: 'comfortable', scale: 'normal' }

// One storage key per dial rather than one blob, so a value this build cannot
// read takes only its own dial down to the default.
export const STORAGE = {
  kit: 'nd.kit',
  mode: 'nd.mode',
  density: 'nd.density',
  scale: 'nd.scale',
}

export function findKit(key) {
  return KITS.find((k) => k.key === key) || KITS[0]
}

export function resolveMode(mode) {
  if (mode === 'dark' || mode === 'light') return mode
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

// Every read is defended twice: a private-mode browser throws on access, and a
// value written by an older build may name a kit that no longer exists.
export function loadAppearance() {
  const read = (name, fallback) => {
    try {
      return localStorage.getItem(STORAGE[name]) ?? fallback
    } catch {
      return fallback
    }
  }
  const kit = read('kit', DEFAULTS.kit)
  const mode = read('mode', DEFAULTS.mode)
  const density = read('density', DEFAULTS.density)
  const scale = read('scale', DEFAULTS.scale)
  return {
    kit: KITS.some((k) => k.key === kit) ? kit : DEFAULTS.kit,
    mode: MODES.some((m) => m.key === mode) ? mode : DEFAULTS.mode,
    density: DENSITIES.some((d) => d.key === density) ? density : DEFAULTS.density,
    scale: SCALES.some((s) => s.key === scale) ? scale : DEFAULTS.scale,
  }
}

export function saveAppearance(next) {
  for (const [name, key] of Object.entries(STORAGE)) {
    if (next[name] === undefined) continue
    try {
      localStorage.setItem(key, String(next[name]))
    } catch {
      // A browser refusing storage still gets the appearance it asked for for
      // the life of the tab. Only the memory of the choice is lost.
    }
  }
}

// Stamps the selection onto <html>. Four attributes, no colours and no
// arithmetic, which is exactly what lets the inline script in index.html do the
// same job before the bundle has loaded. Returns the resolved selection, since
// 'system' mode is only decided here.
export function applyAppearance(selection) {
  const { kit: kitKey, mode, density, scale } = { ...DEFAULTS, ...selection }
  const kit = findKit(kitKey)
  const resolved = resolveMode(mode)
  const root = document.documentElement

  root.setAttribute('data-kit', kit.key)
  root.setAttribute('data-theme-mode', resolved)
  root.setAttribute('data-density', density)
  root.setAttribute('data-scale', scale)
  root.style.colorScheme = resolved

  return { kit: kit.key, mode, resolvedMode: resolved, density, scale }
}
