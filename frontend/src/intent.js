const RUNNER_PATTERNS = [
  ['codex', /\bcodex\b|\bgpt[-\s]?5\b/i],
  ['claude', /\bclaude\b|\banthropic\b/i],
  ['ollama', /\bollama\b|\blocal model\b|\blocal\b/i],
  ['grok', /\bgrok\b/i],
]

const ACTION_PATTERNS = [
  {
    view: 'design',
    kind: 'design',
    label: 'Improve the look',
    cta: 'Style it',
    pattern: /\b(apply.*ui|ui|design|capture|restyle|theme|make it look|visual|frontend polish)\b/i,
  },
  {
    view: 'queue',
    kind: 'queue',
    label: 'Let it run',
    cta: 'Run it later',
    pattern: /\b(queue|overnight|detached|background|tonight|later|while I sleep|unattended|run .*task|ticket)\b/i,
  },
  {
    view: 'overview',
    kind: 'ask',
    label: 'Ask Noirdeck',
    cta: 'Ask',
    pattern: /\b(ask|which|what|where|why|how many|show me|find)\b/i,
  },
]

export const QUICK_INTENTS = [
  {
    kind: 'workspace',
    view: 'workspace',
    label: 'Build with me',
    cta: 'Start building',
    prompt: '',
    hint: 'Work side by side in the selected project.',
  },
  {
    kind: 'queue',
    view: 'queue',
    label: 'Run in background',
    cta: 'Draft the work',
    prompt: '',
    hint: 'Send a clear job off without staying in it.',
  },
  {
    kind: 'design',
    view: 'design',
    label: 'Make it beautiful',
    cta: 'Open design flow',
    prompt: '',
    hint: 'Use a kit or capture a look from another project.',
  },
  {
    kind: 'ask',
    view: 'overview',
    label: 'Ask what needs work',
    cta: 'Ask now',
    prompt: '',
    hint: 'Get a read-only answer from your projects.',
  },
]

function cleanTitle(query, fallback) {
  const text = (query || '').trim().replace(/\s+/g, ' ')
  if (!text) return fallback
  return text.length > 72 ? `${text.slice(0, 69)}...` : text
}

export function detectRunner(query = '') {
  const found = RUNNER_PATTERNS.find(([, pattern]) => pattern.test(query))
  return found?.[0] || null
}

export function findProject(query = '', fleet = []) {
  const lower = query.toLowerCase()
  return [...fleet]
    .sort((a, b) => b.name.length - a.name.length)
    .find((repo) => lower.includes(repo.name.toLowerCase()))?.name
}

export function findProjectAfterCue(query = '', fleet = [], cue = 'from') {
  const lower = query.toLowerCase()
  const idx = lower.indexOf(`${cue} `)
  if (idx < 0) return ''
  return findProject(lower.slice(idx + cue.length + 1), fleet) || ''
}

export function classifyIntent(query = '') {
  const text = query.trim()
  if (!text) return QUICK_INTENTS[0]
  return (
    ACTION_PATTERNS.find((action) => action.pattern.test(text)) || {
      view: 'workspace',
      kind: 'workspace',
      label: 'Build with me',
      cta: 'Start building',
    }
  )
}

export function buildIntent(query = '', selectedProject = '', fleet = []) {
  const base = classifyIntent(query)
  const project = selectedProject || findProject(query, fleet) || ''
  const runner = detectRunner(query)
  const prompt = query.trim()
  const captureProject = base.kind === 'design' ? findProjectAfterCue(query, fleet, 'from') : ''
  return {
    ...base,
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    project,
    runner,
    prompt,
    title: cleanTitle(prompt, base.label),
    captureProject,
  }
}
