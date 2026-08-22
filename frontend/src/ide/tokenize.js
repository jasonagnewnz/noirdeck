// Minimal hand-rolled tokenizer for read-only syntax highlighting.
// No new runtime dependency (zero-egress: nothing fetched from a CDN, nothing
// npm-installed): a handful of per-language regexes, evaluated client-side.
//
// Token types map to CSS classes in styles.css that resolve to the five tokens
// the contrast contract (ops/check-contrast.mjs) guarantees at 4.5:1 or better
// on every surface, in every kit: --text, --text-2, --text-3, --accent and
// --danger-text. --border-strong, --danger and --success are documented there as
// non-text UI (borders, fills, the live dot) with no small-text guarantee, so
// they are deliberately not used to colour a token here.

const LANGS = {
  python:
    /(?<comment>#[^\n]*)|(?<string>(?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))|(?<number>\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(?<keyword>\b(?:False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b)/gm,

  js: /(?<comment>\/\/[^\n]*|\/\*[\s\S]*?\*\/)|(?<string>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^\\`])*`)|(?<number>\b0[xX][0-9a-fA-F]+\b|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(?<keyword>\b(?:break|case|catch|class|const|continue|debugger|default|delete|do|else|export|extends|finally|for|from|function|if|import|in|instanceof|let|new|of|return|static|super|switch|this|throw|try|typeof|var|void|while|with|yield|async|await|true|false|null|undefined|interface|type|enum|implements|private|protected|public|readonly|namespace|declare|as)\b)/gm,

  json: /(?<string>"(?:\\.|[^"\\\n])*")|(?<number>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(?<keyword>\b(?:true|false|null)\b)/g,

  markdown:
    /(?<heading>^#{1,6}[^\n]*)|(?<string>```[\s\S]*?```|`[^`\n]*`)|(?<keyword>\*\*[^\n]*?\*\*|__[^\n]*?__|\*[^\n*]+?\*)/gm,
}

const EXT_LANG = {
  py: 'python',
  pyw: 'python',
  js: 'js',
  jsx: 'js',
  mjs: 'js',
  cjs: 'js',
  ts: 'js',
  tsx: 'js',
  json: 'json',
  md: 'markdown',
  markdown: 'markdown',
}

export function langForPath(path) {
  const ext = (path.split('.').pop() || '').toLowerCase()
  return EXT_LANG[ext] || null
}

// Tokenizes the whole file in one pass, then splits into per-line token
// arrays so the existing line-number gutter rendering doesn't have to change.
// A token's text can embed newlines (block comments, triple-quoted strings,
// fenced code): those are split into per-line pieces here rather than in the
// regex, so gutter numbering can never drift from the raw content's line count.
export function tokenizeLines(content, path) {
  const lang = langForPath(path)
  const re = lang && LANGS[lang]
  if (!re) return content.split('\n').map((text) => [{ type: 'plain', text }])

  re.lastIndex = 0
  const tokens = []
  let cursor = 0
  let match
  // biome-ignore lint/suspicious/noAssignInExpressions: standard regex exec-loop idiom
  while ((match = re.exec(content))) {
    if (match.index > cursor) tokens.push({ type: 'plain', text: content.slice(cursor, match.index) })
    const type = Object.keys(match.groups).find((k) => match.groups[k] !== undefined)
    tokens.push({ type, text: match[0] })
    cursor = match.index + match[0].length
    if (match[0].length === 0) re.lastIndex += 1 // guard against zero-width matches
  }
  if (cursor < content.length) tokens.push({ type: 'plain', text: content.slice(cursor) })

  const lines = [[]]
  for (const tok of tokens) {
    tok.text.split('\n').forEach((part, i) => {
      if (i > 0) lines.push([])
      if (part) lines[lines.length - 1].push({ type: tok.type, text: part })
    })
  }
  return lines
}
