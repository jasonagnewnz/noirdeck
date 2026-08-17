// WCAG 2.1 contrast check for the theme tokens in frontend/src/ide/themes.js.
//
// The contract, restated from that file: on each of --bg / --bg-deep / --panel
// / --panel-2, --ink must reach 7:1 and --ink-dim / --ink-faint / --amber /
// --red-text must reach 4.5:1. --teal / --red / --green are non-text UI and
// carry no small-text guarantee.
//
// Run: node ops/check-contrast.mjs   (exit 1 on any failure)
import { readFileSync } from 'node:fs'

const SRC = new URL('../frontend/src/ide/themes.js', import.meta.url)

const srgb = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const lum = (hex) => {
  const h = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

const BACKGROUNDS = ['--bg', '--bg-deep', '--panel', '--panel-2']
const RULES = [
  ['--ink', 7],
  ['--ink-dim', 4.5],
  ['--ink-faint', 4.5],
  ['--amber', 4.5],
  ['--red-text', 4.5],
]

// Parse the token blocks without importing (the module is ESM-in-Vite land).
const text = readFileSync(SRC, 'utf8')
const themes = []
for (const m of text.matchAll(/key:\s*'([^']+)'[\s\S]*?tokens:\s*\{([\s\S]*?)\n\s{4}\},/g)) {
  const tokens = {}
  for (const t of m[2].matchAll(/'(--[a-z0-9-]+)':\s*'([^']+)'/g)) tokens[t[1]] = t[2]
  themes.push({ key: m[1], tokens })
}

let failures = 0
for (const { key, tokens } of themes) {
  const bad = []
  for (const bgName of BACKGROUNDS) {
    const bg = tokens[bgName]
    if (!bg || !bg.startsWith('#')) continue
    for (const [fgName, min] of RULES) {
      const fg = tokens[fgName]
      if (!fg || !fg.startsWith('#')) continue
      const r = ratio(fg, bg)
      if (r < min) bad.push(`${fgName} on ${bgName} = ${r.toFixed(2)}:1 (need ${min})`)
    }
  }
  if (bad.length) {
    failures += bad.length
    console.error(`FAIL ${key}`)
    for (const b of bad) console.error(`       ${b}`)
  } else {
    console.log(`pass ${key}`)
  }
}
console.log(`\n${themes.length} themes checked, ${failures} violations`)
process.exit(failures ? 1 : 0)
