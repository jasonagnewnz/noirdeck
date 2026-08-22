import { useEffect, useState } from 'react'
import { api } from '../../api.js'

// The guided intake: deliberately ONE page, not a wizard: a non-technical
// person can see the whole interview at once, answer in any order, and nothing
// is hidden behind a "next" button. Questions come from the backend
// (/api/guided/questions) so the form and the brief compiler can never drift.

const legendStyle = {
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.13em',
  color: 'var(--text-3)',
  margin: '10px 0 4px',
  padding: 0,
}
const helpStyle = { fontSize: 11.5, margin: '0 0 6px', maxWidth: '72ch' }

const Req = () => (
  <span className="faint" style={{ textTransform: 'none', letterSpacing: 0 }}>
    {' '}
    : required
  </span>
)

const Help = ({ id, text }) =>
  text ? (
    <p className="faint" id={id} style={helpStyle}>
      {text}
    </p>
  ) : null

export default function GuidedIntake({ onCreated }) {
  const [questions, setQuestions] = useState(null)
  const [recipes, setRecipes] = useState([])
  const [picked, setPicked] = useState(null)
  const [loadErr, setLoadErr] = useState(null)
  const [name, setName] = useState('')
  const [answers, setAnswers] = useState({})
  const [missing, setMissing] = useState([]) // question ids the server said need answers
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    api('/guided/questions')
      .then((qs) => alive && setQuestions(qs))
      .catch((ex) => alive && setLoadErr(ex.message))
    api('/guided/recipes')
      .then((rs) => alive && setRecipes(rs))
      .catch(() => {
        /* templates are optional sugar: the form works without them */
      })
    return () => {
      alive = false
    }
  }, [])

  const applyRecipe = (r) => {
    setPicked(r.id)
    setAnswers({ ...r.answers })
    setMissing([])
    document.getElementById('g-name')?.focus()
  }

  const setAnswer = (id, v) => setAnswers((a) => ({ ...a, [id]: v }))

  const submit = async (e) => {
    e.preventDefault()
    setErr(null)
    setMissing([])
    setBusy(true)
    try {
      const cleaned = {}
      for (const q of questions) {
        const v = answers[q.id]
        cleaned[q.id] = q.type === 'list' ? (v || []).map((s) => s.trim()).filter(Boolean) : (v ?? '')
      }
      const { id } = await api('/builds/guided', { body: { name: name.trim(), answers: cleaned } })
      setName('')
      setAnswers({})
      onCreated(id)
    } catch (ex) {
      // Backend 400 detail is a comma-joined string: "missing answers: purpose, users"
      const m = /^missing answers:\s*(.+)$/.exec(ex.message || '')
      if (m && questions) {
        const ids = m[1].split(',').map((s) => s.trim())
        setMissing(ids)
        const labels = ids.map((qid) => (questions.find((q) => q.id === qid) || { label: qid }).label)
        setErr(`Almost there: please answer: ${labels.join(' · ')}`)
      } else {
        setErr(ex.message)
      }
    } finally {
      setBusy(false)
    }
  }

  if (loadErr) {
    return (
      <div className="err" role="alert">
        Couldn't load the questions: {loadErr}
      </div>
    )
  }
  if (!questions) {
    return (
      <div className="loading" role="status" aria-live="polite">
        loading questions
      </div>
    )
  }

  return (
    <form onSubmit={submit}>
      <p className="dim" style={{ maxWidth: '72ch', margin: '6px 0 2px' }}>
        Answer in plain English: no technical knowledge needed. We'll turn your answers into a full brief, draft a plan,
        and show you that plan before anything gets built.
      </p>

      {recipes.length > 0 && (
        <div role="group" aria-label="Start from a template">
          <div className="fl" style={{ margin: '12px 0 2px' }}>
            Start from a template if one fits: every answer stays editable
          </div>
          <div className="recipe-grid">
            {recipes.map((r) => (
              <button
                type="button"
                key={r.id}
                className={`recipe-card${picked === r.id ? ' on' : ''}`}
                aria-pressed={picked === r.id}
                onClick={() => applyRecipe(r)}
              >
                <b>{r.title}</b>
                <span>{r.blurb}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <label className="fl" htmlFor="g-name">
        <span className="qnum">1.</span>What should we call it?
        <Req />
      </label>
      <p className="faint" id="g-name-help" style={helpStyle}>
        lowercase letters, numbers and dashes
      </p>
      <input
        id="g-name"
        value={name}
        required
        aria-required="true"
        pattern="[a-z0-9-]+"
        placeholder="my-new-product"
        aria-describedby="g-name-help"
        onChange={(e) => setName(e.target.value)}
      />

      {questions.map((q, i) => {
        const qid = `gq-${q.id}`
        const invalid = missing.includes(q.id) || undefined
        const num = <span className="qnum">{i + 2}.</span>

        if (q.type === 'choice') {
          return (
            <fieldset key={q.id} className="qblock" style={{ border: 0, padding: 0 }}>
              <legend style={legendStyle}>
                {num}
                {q.label}
                {q.required && <Req />}
              </legend>
              <Help id={`${qid}-help`} text={q.help} />
              {(q.options || []).map(([val, lab]) => {
                const oid = `${qid}-${val}`
                return (
                  <div key={val} style={{ margin: '3px 0' }}>
                    <label htmlFor={oid} style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
                      <input
                        type="radio"
                        id={oid}
                        name={qid}
                        value={val}
                        checked={answers[q.id] === val}
                        required={q.required || undefined}
                        style={{ width: 'auto', margin: 0, flexShrink: 0 }}
                        onChange={() => setAnswer(q.id, val)}
                      />
                      <span>{lab}</span>
                    </label>
                  </div>
                )
              })}
              {invalid && (
                <div className="err" style={{ padding: '2px 0' }}>
                  Please pick one
                </div>
              )}
            </fieldset>
          )
        }

        if (q.type === 'list') {
          const items = answers[q.id] && answers[q.id].length ? answers[q.id] : ['']
          const max = q.max_items || 5
          return (
            <fieldset key={q.id} className="qblock" style={{ border: 0, padding: 0 }}>
              <legend style={legendStyle}>
                {num}
                {q.label}
                {q.required && <Req />}
              </legend>
              <Help id={`${qid}-help`} text={q.help} />
              {items.map((v, i) => (
                <input
                  key={i}
                  value={v}
                  aria-label={`${q.label}: item ${i + 1} of ${items.length}`}
                  aria-required={(q.required && i === 0) || undefined}
                  required={(q.required && i === 0) || undefined}
                  aria-invalid={(i === 0 && invalid) || undefined}
                  aria-describedby={q.help ? `${qid}-help` : undefined}
                  placeholder={i === 0 ? q.placeholder || '' : ''}
                  style={{ marginTop: i ? 6 : 0 }}
                  onChange={(e) => {
                    const next = [...items]
                    next[i] = e.target.value
                    setAnswer(q.id, next)
                  }}
                />
              ))}
              {items.length < max && (
                <div style={{ marginTop: 6 }}>
                  <button type="button" className="act ghost" onClick={() => setAnswer(q.id, [...items, ''])}>
                    add another
                  </button>
                  <span className="faint" style={{ marginLeft: 8 }}>
                    up to {max}
                  </span>
                </div>
              )}
            </fieldset>
          )
        }

        // default: single-line text
        return (
          <div key={q.id} className="qblock">
            <label className="fl" htmlFor={qid} style={{ marginTop: 0 }}>
              {num}
              {q.label}
              {q.required && <Req />}
            </label>
            <Help id={`${qid}-help`} text={q.help} />
            <input
              id={qid}
              value={answers[q.id] || ''}
              required={q.required || undefined}
              aria-required={q.required || undefined}
              aria-invalid={invalid}
              aria-describedby={q.help ? `${qid}-help` : undefined}
              placeholder={q.placeholder || ''}
              onChange={(e) => setAnswer(q.id, e.target.value)}
            />
          </div>
        )
      })}

      <div style={{ marginTop: 14 }}>
        <button className="act" type="submit" disabled={busy}>
          Plan my build
        </button>
      </div>
      {busy && (
        <div role="status" aria-live="polite" className="dim" style={{ marginTop: 8 }}>
          Sending your answers: the planner will draft a plan for you to approve…
        </div>
      )}
      {err && (
        <div className="err" role="alert">
          {err}
        </div>
      )}
    </form>
  )
}
