// Colour contract for the appearance kits in frontend/src/styles.css.
//
// Two rules, both enforced here because neither survives being eyeballed.
//
// 1. CONTRAST (WCAG 2.1, relative luminance). On every surface token, --text
//    reaches 7:1 and --text-2 / --text-3 / --accent / --danger-text reach 4.5:1.
//    --border-strong, --danger, --warning and --success are non-text UI and
//    carry no small-text guarantee.
//
// 2. SIGNAL SEPARATION. --accent must be perceptually distinct from both
//    --danger and --danger-text.
//    Eleven themes shipped before this rule existed and two of them set the
//    accent to red, so an alarm panel rendered indistinguishable from ordinary
//    UI until a screenshot caught it. Distance is CIE76 dE in Lab, which is
//    coarse but entirely adequate for "are these two the same colour".
//
// Run: node ops/check-contrast.mjs   (exit 1 on any violation)
import { readFileSync } from 'node:fs'

const SRC = new URL('../frontend/src/styles.css', import.meta.url)

const linear = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const rgb = (hex) => {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => Number.parseInt(h.slice(i, i + 2), 16) / 255)
}
const luminance = (hex) => {
  const [r, g, b] = rgb(hex).map(linear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const ratio = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (hi + 0.05) / (lo + 0.05)
}

// sRGB -> CIE Lab, D65. Only used for the signal-separation rule.
const lab = (hex) => {
  const [r, g, b] = rgb(hex).map(linear)
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  const [fx, fy, fz] = [f(x), f(y), f(z)]
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
}
const deltaE = (a, b) => {
  const [l1, a1, b1] = lab(a)
  const [l2, a2, b2] = lab(b)
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2)
}

const SURFACES = ['--surface-0', '--surface-sunken', '--surface-1', '--surface-2']
const TEXT_RULES = [
  ['--text', 7],
  ['--text-2', 4.5],
  ['--text-3', 4.5],
  ['--accent', 4.5],
  ['--danger-text', 4.5],
]
const MIN_SIGNAL_DISTANCE = 25

// Read straight out of the stylesheet, because the stylesheet is where the
// colours actually are. A kit that renders is a kit that gets checked.
const source = readFileSync(SRC, 'utf8')
const palettes = []
// Quote style is the formatter's business, not this script's.
for (const block of source.matchAll(
  /:root\[data-kit=["']([a-z]+)["']\]\[data-theme-mode=["'](dark|light)["']\]\s*\{([^}]*)\}/g
)) {
  const tokens = {}
  for (const decl of block[3].matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) tokens[decl[1]] = decl[2].trim()
  palettes.push({ name: `${block[1]} ${block[2]}`, tokens })
}

if (!palettes.length) {
  console.error('FAIL no palettes parsed from styles.css: the parser and the stylesheet have drifted')
  process.exit(1)
}

let violations = 0
for (const { name, tokens } of palettes) {
  const bad = []

  for (const surfaceName of SURFACES) {
    const surface = tokens[surfaceName]
    if (!surface?.startsWith('#')) continue
    for (const [textName, min] of TEXT_RULES) {
      const text = tokens[textName]
      if (!text?.startsWith('#')) continue
      const r = ratio(text, surface)
      if (r < min) bad.push(`${textName} on ${surfaceName} = ${r.toFixed(2)}:1 (need ${min})`)
    }
  }

  // Both, and --danger-text is the one that matters most: --danger is a fill or
  // a border, but an alarm HEADING is painted with --danger-text, so that is the
  // colour a reader actually compares against the accent. Checking only --danger
  // passed a palette whose alarm heading sat dE 14.8 from its accent.
  const accent = tokens['--accent']
  for (const name of ['--danger', '--danger-text']) {
    const other = tokens[name]
    if (!accent?.startsWith('#') || !other?.startsWith('#')) continue
    const distance = deltaE(accent, other)
    if (distance < MIN_SIGNAL_DISTANCE) {
      bad.push(`--accent ${accent} is only dE ${distance.toFixed(1)} from ${name} ${other} (need ${MIN_SIGNAL_DISTANCE})`)
    }
  }

  if (bad.length) {
    violations += bad.length
    console.error(`FAIL ${name}`)
    for (const line of bad) console.error(`       ${line}`)
  } else {
    console.log(`pass ${name}`)
  }
}

console.log(`\n${palettes.length} palettes checked, ${violations} violations`)
process.exit(violations ? 1 : 0)
