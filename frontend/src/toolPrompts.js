const COMMON_GUARDRAILS = [
  'Inspect the existing stack, routes, data model, env handling, and tests before changing code.',
  'Ask before selecting a paid provider, changing the security model, purchasing anything, or making live DNS/deploy changes.',
  'Use environment variables for secrets. Never hardcode API keys, tokens, credentials, or private URLs.',
  'Keep the change small enough to review. Add docs, setup notes, and local verification steps.',
  'Stop at code-ready unless the operator explicitly asks you to deploy, publish, or buy/configure a domain.',
]

export const TOOL_PROMPTS = [
  {
    id: 'payments',
    label: 'Payments',
    task: 'Add payments',
    blurb: 'Checkout, subscriptions, invoices, webhooks.',
    questions: [
      { id: 'provider', label: 'Provider', type: 'choice', options: ['Stripe', 'Paddle', 'Lemon Squeezy', 'Not sure'] },
      {
        id: 'model',
        label: 'Money model',
        type: 'choice',
        options: ['One-time', 'Subscription', 'Usage billing', 'Deposit'],
      },
      { id: 'selling', label: 'What gets purchased?', placeholder: 'e.g. Pro plan, booking deposit, invoice payment' },
      { id: 'success', label: 'After payment', placeholder: 'e.g. unlock account, send receipt, create booking' },
      { id: 'webhooks', label: 'Webhooks', type: 'choice', options: ['Needed', 'Not sure', 'Not yet'] },
    ],
    guardrails: [
      'Prefer hosted checkout unless the existing product clearly needs embedded payments.',
      'Implement webhook idempotency and verify paid state server-side.',
      'Never handle raw card details directly.',
    ],
  },
  {
    id: 'auth',
    label: 'Auth',
    task: 'Add authentication',
    blurb: 'Login, signup, sessions, protected routes.',
    questions: [
      {
        id: 'provider',
        label: 'Provider',
        type: 'choice',
        options: ['Supabase', 'Clerk', 'Auth.js', 'Custom', 'Not sure'],
      },
      { id: 'users', label: 'Who signs in?', placeholder: 'e.g. customers, admins, team members' },
      {
        id: 'methods',
        label: 'Login method',
        type: 'choice',
        options: ['Email/password', 'Magic link', 'Google', 'Email + Google'],
      },
      { id: 'roles', label: 'Roles', placeholder: 'e.g. user/admin, owner/member, tenant admin' },
      { id: 'protect', label: 'Protect what?', placeholder: 'e.g. dashboard, checkout, admin area, API routes' },
    ],
    guardrails: [
      'Define session storage, logout, reset/recovery, and protected route behavior.',
      'Protect server/API routes too; frontend-only auth is not enough.',
      'Add basic abuse and account-state handling where the stack supports it.',
    ],
  },
  {
    id: 'domain',
    label: 'Domain',
    task: 'Connect a domain',
    blurb: 'DNS records, redirects, SSL, www/apex.',
    questions: [
      { id: 'domain', label: 'Domain name', placeholder: 'e.g. noirdeck.dev' },
      { id: 'registrar', label: 'DNS host', placeholder: 'e.g. Cloudflare, Namecheap, GoDaddy, Vercel DNS' },
      { id: 'target', label: 'Where should it point?', placeholder: 'e.g. Vercel project, server IP, Netlify site' },
      { id: 'shape', label: 'Preferred URL', type: 'choice', options: ['apex', 'www', 'both', 'Not sure'] },
      {
        id: 'email',
        label: 'Email on domain?',
        type: 'choice',
        options: ['No', 'Google Workspace', 'Microsoft 365', 'Not sure'],
      },
    ],
    guardrails: [
      'Do not make live DNS changes unless the operator explicitly confirms.',
      'List exact DNS records, expected propagation, SSL checks, and rollback records.',
      'Preserve existing MX/TXT records unless the operator asks to change email.',
    ],
  },
  {
    id: 'hosting',
    label: 'Hosting',
    task: 'Host the app',
    blurb: 'Deploy target, build command, env vars, health check.',
    questions: [
      {
        id: 'target',
        label: 'Host',
        type: 'choice',
        options: ['Vercel', 'Netlify', 'Railway', 'Render', 'VPS', 'Not sure'],
      },
      {
        id: 'app_type',
        label: 'App type',
        type: 'choice',
        options: ['Static site', 'Full-stack', 'API + frontend', 'Not sure'],
      },
      { id: 'build', label: 'Build/start command', placeholder: 'e.g. npm run build, uvicorn app:app, not sure' },
      { id: 'env', label: 'Required env vars', placeholder: 'e.g. DATABASE_URL, STRIPE_SECRET_KEY, none yet' },
      { id: 'domain', label: 'Domain', placeholder: 'e.g. noirdeck.dev, staging first, not yet' },
    ],
    guardrails: [
      'Create a deployment plan first: build, start, env vars, health check, logs, rollback.',
      'Do not publish or expose private/local tools without explicit operator approval.',
      'Keep staging and production secrets separate.',
    ],
  },
  {
    id: 'database',
    label: 'Database',
    task: 'Add a database',
    blurb: 'Schema, migrations, seed data, backups.',
    questions: [
      {
        id: 'provider',
        label: 'Provider',
        type: 'choice',
        options: ['Supabase', 'Postgres', 'SQLite', 'Neon', 'Not sure'],
      },
      { id: 'data', label: 'Data to store', placeholder: 'e.g. users, orders, projects, audit logs' },
      {
        id: 'scale',
        label: 'Scale now',
        type: 'choice',
        options: ['Prototype', 'Production small', 'Multi-tenant', 'Not sure'],
      },
      { id: 'migration', label: 'Migration tool', placeholder: 'e.g. Prisma, Drizzle, Alembic, built-in, not sure' },
      { id: 'seed', label: 'Seed data', placeholder: 'e.g. admin user, demo products, none' },
    ],
    guardrails: [
      'Use migrations, not manual schema edits.',
      'Define backup/restore expectations before calling it production-ready.',
      'Avoid destructive migrations without a rollback path.',
    ],
  },
  {
    id: 'email',
    label: 'Email',
    task: 'Add email',
    blurb: 'Transactional mail, templates, DNS, retries.',
    questions: [
      {
        id: 'provider',
        label: 'Provider',
        type: 'choice',
        options: ['Resend', 'Postmark', 'SendGrid', 'SES', 'Not sure'],
      },
      {
        id: 'emails',
        label: 'Emails needed',
        placeholder: 'e.g. welcome, reset password, receipt, booking confirmation',
      },
      { id: 'from', label: 'From address', placeholder: 'e.g. hello@noirdeck.dev, support@domain.com' },
      {
        id: 'templates',
        label: 'Templates',
        type: 'choice',
        options: ['Plain text first', 'HTML branded', 'Both', 'Not sure'],
      },
      { id: 'domain_dns', label: 'DNS ready?', type: 'choice', options: ['Yes', 'No', 'Not sure'] },
    ],
    guardrails: [
      'Separate transactional email from marketing email unless the operator asks for campaigns.',
      'Document SPF/DKIM/DMARC records and local/dev email behavior.',
      'Add retry/error logging for critical emails.',
    ],
  },
  {
    id: 'uploads',
    label: 'Uploads',
    task: 'Add file uploads',
    blurb: 'Storage, validation, previews, cleanup.',
    questions: [
      {
        id: 'storage',
        label: 'Storage',
        type: 'choice',
        options: ['S3', 'Supabase Storage', 'Cloudinary', 'Local dev', 'Not sure'],
      },
      { id: 'files', label: 'File types', placeholder: 'e.g. images, PDFs, CSVs, avatars, attachments' },
      { id: 'size', label: 'Size limit', placeholder: 'e.g. 5MB images, 50MB PDFs, not sure' },
      { id: 'access', label: 'Access', type: 'choice', options: ['Private', 'Public', 'Signed URLs', 'Not sure'] },
      { id: 'scan', label: 'Validation', placeholder: 'e.g. MIME check, image dimensions, virus scan, none yet' },
    ],
    guardrails: [
      'Validate type and size server-side.',
      'Keep private files private; use signed URLs where appropriate.',
      'Plan cleanup for abandoned or replaced files.',
    ],
  },
  {
    id: 'analytics',
    label: 'Analytics',
    task: 'Add analytics',
    blurb: 'Events, funnels, product metrics, privacy.',
    questions: [
      {
        id: 'provider',
        label: 'Provider',
        type: 'choice',
        options: ['PostHog', 'Plausible', 'GA4', 'Custom events', 'Not sure'],
      },
      {
        id: 'events',
        label: 'Key events',
        placeholder: 'e.g. signup, checkout started, payment succeeded, project created',
      },
      {
        id: 'users',
        label: 'Identify users?',
        type: 'choice',
        options: ['Anonymous only', 'Logged-in users', 'Both', 'Not sure'],
      },
      {
        id: 'privacy',
        label: 'Privacy level',
        type: 'choice',
        options: ['Cookie-light', 'Consent banner', 'Internal only', 'Not sure'],
      },
      {
        id: 'dashboard',
        label: 'Where to view metrics?',
        placeholder: 'e.g. provider dashboard, admin page, weekly report',
      },
    ],
    guardrails: [
      'Name events consistently and avoid collecting secrets or sensitive content.',
      'Respect consent and regional privacy requirements for the intended users.',
      'Add a small event map to docs so future work uses the same names.',
    ],
  },
  {
    id: 'admin',
    label: 'Admin',
    task: 'Add an admin area',
    blurb: 'Back office, roles, audit trail, support tools.',
    questions: [
      { id: 'users', label: 'Admin users', placeholder: 'e.g. founder only, support team, tenant admins' },
      {
        id: 'actions',
        label: 'Admin actions',
        placeholder: 'e.g. view users, refund orders, edit content, reset accounts',
      },
      {
        id: 'roles',
        label: 'Permissions',
        type: 'choice',
        options: ['Single admin', 'Role-based', 'Tenant-based', 'Not sure'],
      },
      { id: 'audit', label: 'Audit log', type: 'choice', options: ['Required', 'Nice to have', 'Not yet'] },
      { id: 'safety', label: 'Dangerous actions', placeholder: 'e.g. deletes, refunds, impersonation, none' },
    ],
    guardrails: [
      'Admin routes must be server-protected and tested.',
      'Add confirmation and audit logging for destructive or money-related actions.',
      'Do not add impersonation unless explicitly requested and logged.',
    ],
  },
  {
    id: 'release',
    label: 'Release',
    task: 'Prepare for launch',
    blurb: 'Tests, QA gates, env checks, rollback notes.',
    questions: [
      { id: 'stage', label: 'Launch stage', type: 'choice', options: ['First demo', 'Beta', 'Production', 'Not sure'] },
      { id: 'must_work', label: 'Critical paths', placeholder: 'e.g. signup, checkout, upload, dashboard load' },
      {
        id: 'tests',
        label: 'Test depth',
        type: 'choice',
        options: ['Smoke tests', 'Unit + smoke', 'E2E critical paths', 'Not sure'],
      },
      { id: 'env', label: 'Env checks', placeholder: 'e.g. API keys, database URL, webhook secret, none' },
      { id: 'rollback', label: 'Rollback', placeholder: 'e.g. previous deploy, git tag, database backup, not sure' },
    ],
    guardrails: [
      'Create a release checklist and verify the critical paths locally.',
      'Flag any missing env vars, secrets, migrations, or deployment risks.',
      'Do not deploy; stop with a clear go/no-go report unless told to ship.',
    ],
  },
]

export function toolPromptById(id) {
  return TOOL_PROMPTS.find((tool) => tool.id === id) || TOOL_PROMPTS[0]
}

export function buildToolPrompt(tool, answers = {}, project = '') {
  const known = tool.questions.map((q) => [q.label, (answers[q.id] || '').trim() || 'Ask before deciding'])
  const answerLines = known.map(([label, value]) => `- ${label}: ${value}`)
  const guardrailLines = [...COMMON_GUARDRAILS, ...tool.guardrails].map((line) => `- ${line}`)
  return [
    `# ${tool.task}`,
    '',
    `Project: ${project || 'selected project'}`,
    `Outcome: ${tool.task} in a way that fits the existing product and can be reviewed safely.`,
    '',
    '## Operator Answers',
    ...answerLines,
    '',
    '## How To Work',
    ...guardrailLines,
    '',
    '## Expected Finish',
    '- Code changes are scoped and committed or ready to commit.',
    '- Tests or a concrete verification checklist are included.',
    '- Required env vars, provider setup, and any manual steps are documented.',
    '- If a decision is still ambiguous, park with a clear question instead of guessing.',
  ].join('\n')
}

export function buildToolTitle(tool, answers = {}) {
  const subject = (answers.selling || answers.domain || answers.target || answers.data || answers.emails || '').trim()
  return subject ? `${tool.task}: ${subject}` : tool.task
}

export function appendSuggestedMethod(prompt, method) {
  if (!method) return prompt
  const runner = method.runner_label || method.runner || 'selected tool'
  const model = method.model_label ? ` / ${method.model_label}` : ''
  const reasons = (method.reasons || []).slice(0, 3).map((reason) => `- ${reason}`)
  const memoryHints = (method.memory_hints || []).slice(0, 4).map((hint) => hint.name || hint.namespace)
  return [
    prompt,
    '',
    '## Suggested Method From Noirdeck',
    `- Runner: ${runner}${model}`,
    `- Reuse prompt: ${method.question || 'Use this previous method if it still fits.'}`,
    ...(reasons.length ? ['- Why:', ...reasons.map((reason) => `  ${reason}`)] : []),
    `- Memory hints: ${memoryHints.length ? memoryHints.join(', ') : 'none surfaced'}`,
    '',
    'Use this previous method as orientation, but verify it still fits this task before editing.',
  ].join('\n')
}
