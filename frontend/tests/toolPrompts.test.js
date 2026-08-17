import { describe, expect, it } from 'vitest'
import {
  appendSuggestedMethod,
  buildToolPrompt,
  buildToolTitle,
  TOOL_PROMPTS,
  toolPromptById,
} from '../src/toolPrompts.js'

describe('tools prompter', () => {
  it('ships the top ten solo-coder launch jobs', () => {
    expect(TOOL_PROMPTS).toHaveLength(10)
    expect(TOOL_PROMPTS.map((tool) => tool.id)).toEqual([
      'payments',
      'auth',
      'domain',
      'hosting',
      'database',
      'email',
      'uploads',
      'analytics',
      'admin',
      'release',
    ])
  })

  it('builds a grounded payments prompt with safety guardrails', () => {
    const tool = toolPromptById('payments')
    const prompt = buildToolPrompt(
      tool,
      {
        provider: 'Stripe',
        model: 'Subscription',
        selling: 'Pro plan',
        success: 'unlock the workspace',
        webhooks: 'Needed',
      },
      'shop'
    )
    expect(prompt).toContain('# Add payments')
    expect(prompt).toContain('Project: shop')
    expect(prompt).toContain('- Provider: Stripe')
    expect(prompt).toContain('- Money model: Subscription')
    expect(prompt).toContain('Never handle raw card details directly.')
    expect(prompt).toContain('Stop at code-ready')
  })

  it('uses the concrete answer in the title when available', () => {
    const title = buildToolTitle(toolPromptById('domain'), { domain: 'noirdeck.dev' })
    expect(title).toBe('Connect a domain: noirdeck.dev')
  })

  it('adds accepted memory method context to a prompt', () => {
    const prompt = appendSuggestedMethod('# Add auth', {
      runner_label: 'Codex',
      model_label: 'gpt-5-codex',
      question: 'You have used Codex here before. Reuse that method, or choose different?',
      reasons: ['Your saved default is Codex.', '2 memory notes are available.'],
      memory_hints: [{ name: 'auth-stack' }, { name: 'release-style' }],
    })
    expect(prompt).toContain('## Suggested Method From Noirdeck')
    expect(prompt).toContain('- Runner: Codex / gpt-5-codex')
    expect(prompt).toContain('auth-stack, release-style')
    expect(prompt).toContain('verify it still fits')
  })
})
