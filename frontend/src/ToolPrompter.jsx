import { useEffect, useMemo, useRef, useState } from 'react'
import { api, useData } from './api.js'
import { appendSuggestedMethod, buildToolPrompt, buildToolTitle, TOOL_PROMPTS, toolPromptById } from './toolPrompts.js'

function MethodDetails({ method, accepted = false, label = '' }) {
  const reasons = method.reasons || []
  const hints = method.memory_hints || []
  return (
    <div className="method-card-main">
      <span className="method-kicker">Memory + preferences</span>
      <b>{accepted ? `Using ${label}` : method.title}</b>
      <p>{method.question}</p>
      {reasons.length > 0 && (
        <div className="method-reasons">
          {reasons.map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
      )}
      {hints.length > 0 && (
        <div className="method-memory">
          {hints.slice(0, 4).map((hint) => (
            <span className="chip" key={`${hint.namespace || 'method'}:${hint.name}`} title={hint.description}>
              {hint.name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ToolPrompter({ fleet = [], onIntent }) {
  const { data: runtime } = useData('/workspace/runtimes', 0)
  const [toolId, setToolId] = useState(TOOL_PROMPTS[0].id)
  const [project, setProject] = useState('')
  const [answers, setAnswers] = useState({})
  const [copied, setCopied] = useState(false)
  const [useMemory, setUseMemory] = useState(false)
  const [methodSuggestion, setMethodSuggestion] = useState(null)
  const [methodDismissed, setMethodDismissed] = useState(false)
  const [preferredMethod, setPreferredMethod] = useState(null)
  const [methodBusy, setMethodBusy] = useState(false)
  const defaultsLoaded = useRef(false)
  const tool = toolPromptById(toolId)
  const basePrompt = useMemo(() => buildToolPrompt(tool, answers, project), [tool, answers, project])
  const prompt = useMemo(() => appendSuggestedMethod(basePrompt, preferredMethod), [basePrompt, preferredMethod])
  const title = useMemo(() => buildToolTitle(tool, answers), [tool, answers])
  const canLaunch = Boolean(project)
  const preferredLabel = preferredMethod
    ? `${preferredMethod.runner_label || preferredMethod.runner}${preferredMethod.model_label ? ` / ${preferredMethod.model_label}` : ''}`
    : ''

  useEffect(() => {
    if (runtime?.defaults && !defaultsLoaded.current) {
      defaultsLoaded.current = true
      setUseMemory(!!runtime.defaults.method_advisor)
    }
  }, [runtime])

  // biome-ignore lint/correctness/useExhaustiveDependencies: project/tool changes are the reset signal for method picks.
  useEffect(() => {
    setMethodDismissed(false)
    setMethodSuggestion(null)
    setPreferredMethod(null)
  }, [project, toolId])

  useEffect(() => {
    if (!useMemory || !project || methodDismissed || preferredMethod) {
      setMethodSuggestion(null)
      setMethodBusy(false)
      return undefined
    }
    let alive = true
    setMethodBusy(true)
    const timer = setTimeout(() => {
      api('/workspace/method', { body: { project, prompt: basePrompt } })
        .then((suggestion) => alive && setMethodSuggestion(suggestion))
        .catch(() => alive && setMethodSuggestion(null))
        .finally(() => alive && setMethodBusy(false))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [useMemory, project, basePrompt, methodDismissed, preferredMethod])

  const chooseTool = (id) => {
    setToolId(id)
    setAnswers({})
    setCopied(false)
  }

  const updateAnswer = (id, value) => {
    setAnswers((current) => ({ ...current, [id]: value }))
    setCopied(false)
  }

  const toggleMemory = (checked) => {
    setUseMemory(checked)
    setMethodDismissed(false)
    if (!checked) {
      setMethodSuggestion(null)
      setPreferredMethod(null)
      setMethodBusy(false)
    }
  }

  const useSuggestedMethod = () => {
    if (!methodSuggestion) return
    setPreferredMethod(methodSuggestion)
    setMethodSuggestion(null)
    setCopied(false)
  }

  const chooseDifferent = () => {
    setPreferredMethod(null)
    setMethodDismissed(true)
    setCopied(false)
  }

  const launch = (view) => {
    if (!canLaunch) return
    onIntent?.({
      id: `${Date.now()}-${tool.id}`,
      kind: view === 'queue' ? 'queue' : 'workspace',
      view,
      project,
      title,
      prompt,
      runner: preferredMethod?.runner,
      model: preferredMethod?.model || undefined,
    })
  }

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section className="panel tool-prompter reveal d1" aria-labelledby="tool-prompter-title">
      <div className="tool-prompter-head">
        <div>
          <h2 id="tool-prompter-title">Add essentials</h2>
          <p className="sechint tool-prompter-hint">
            Pick what the product needs, answer the few questions that matter, then send a clean brief.
          </p>
        </div>
        <div className="tool-head-actions">
          <select
            className="tool-project"
            aria-label="Target project"
            value={project}
            onChange={(e) => setProject(e.target.value)}
          >
            <option value="">Choose project</option>
            {fleet.map((repo) => (
              <option key={repo.path || repo.name} value={repo.name}>
                {repo.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="tool-prompter-body">
        <nav className="tool-catalog" aria-label="Common launch jobs">
          {TOOL_PROMPTS.map((item) => (
            <button
              className={`tool-card ${item.id === tool.id ? 'on' : ''}`}
              key={item.id}
              type="button"
              onClick={() => chooseTool(item.id)}
            >
              <b>{item.label}</b>
              <span>{item.blurb}</span>
            </button>
          ))}
        </nav>

        <div className="tool-builder">
          <div className="tool-builder-title">
            <span className="eyebrow">Brief builder</span>
            <h3>{tool.task}</h3>
          </div>
          <div className="tool-method-control">
            <label className="toggleline tool-memory-toggle" htmlFor="tool-method-memory">
              <input
                id="tool-method-memory"
                type="checkbox"
                checked={useMemory}
                onChange={(e) => toggleMemory(e.target.checked)}
              />
              <span>use memories + preferences</span>
            </label>
            {useMemory && preferredMethod && <span className="chip hot">using {preferredLabel}</span>}
            {useMemory && !project && <span className="faint">choose a project for suggestions</span>}
          </div>
          <div className="tool-questions">
            {tool.questions.map((q) => (
              <div className="tool-question" key={q.id}>
                {q.type === 'choice' ? (
                  <fieldset className="tool-choices">
                    <legend>{q.label}</legend>
                    {q.options.map((option) => (
                      <button
                        className={answers[q.id] === option ? 'on' : ''}
                        key={option}
                        type="button"
                        onClick={() => updateAnswer(q.id, option)}
                      >
                        {option}
                      </button>
                    ))}
                  </fieldset>
                ) : (
                  <>
                    <label htmlFor={`tool-${tool.id}-${q.id}`}>{q.label}</label>
                    <input
                      id={`tool-${tool.id}-${q.id}`}
                      value={answers[q.id] || ''}
                      placeholder={q.placeholder}
                      onChange={(e) => updateAnswer(q.id, e.target.value)}
                    />
                  </>
                )}
              </div>
            ))}
          </div>

          {useMemory && project && !methodDismissed && (preferredMethod || methodSuggestion || methodBusy) && (
            <div className="method-card tool-method-card" role="status" aria-live="polite">
              {preferredMethod ? (
                <>
                  <MethodDetails method={preferredMethod} accepted label={preferredLabel} />
                  <div className="method-actions">
                    <button className="act ghost" type="button" onClick={chooseDifferent}>
                      different
                    </button>
                  </div>
                </>
              ) : methodSuggestion ? (
                <>
                  <MethodDetails method={methodSuggestion} />
                  <div className="method-actions">
                    <button className="act" type="button" disabled={methodBusy} onClick={useSuggestedMethod}>
                      use method
                    </button>
                    <button className="act ghost" type="button" onClick={chooseDifferent}>
                      different
                    </button>
                  </div>
                </>
              ) : (
                <span className="faint">checking previous methods…</span>
              )}
            </div>
          )}

          <div className="tool-preview">
            <div className="tool-preview-head">
              <span>Generated brief</span>
              <button className="act ghost sm" type="button" onClick={copyPrompt}>
                {copied ? 'copied' : 'copy'}
              </button>
            </div>
            <pre>{prompt}</pre>
          </div>

          <div className="tool-actions">
            <button className="act" type="button" disabled={!canLaunch} onClick={() => launch('workspace')}>
              build with me
            </button>
            <button className="act ghost" type="button" disabled={!canLaunch} onClick={() => launch('queue')}>
              run in background
            </button>
            {!canLaunch && <span className="faint">choose a project to start</span>}
          </div>
        </div>
      </div>
    </section>
  )
}
