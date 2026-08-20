import { useState } from 'react'
import { api, useData } from '../api.js'
import { usePager } from '../pager.jsx'
import { ConfirmButton, ViewHead } from '../ui.jsx'

// Credential findings in the AI workspace. Two rules shape this whole screen:
//
// 1. Nothing here is ever the secret itself. A row carries the detector, the
//    file, the line, a SHA-256 fingerprint prefix and the source line with the
//    VALUE REPLACED. Showing a "safe" prefix of a credential would just move the
//    credential into the browser and call it handled.
// 2. Nothing is auto-actioned. The medium tier contains false positives by
//    design (a memory file that documents a credential's existence reads much
//    like one that holds it), so every decision is a human's.

const DETECTOR_LABELS = {
  aws_access_key_id: 'AWS access key',
  github_pat: 'GitHub token',
  github_fine_grained_pat: 'GitHub fine-grained token',
  slack_token: 'Slack token',
  stripe_live_key: 'Stripe LIVE key',
  google_api_key: 'Google API key',
  openai_key: 'OpenAI-style key',
  anthropic_key: 'Anthropic key',
  private_key_block: 'Private key block',
  jwt: 'JWT',
  connection_string_password: 'Password in a connection string',
  assigned_secret: 'NAME=value secret',
  lowercase_assigned_secret: 'name: value secret',
  password_in_prose: 'Password written in prose',
  credential_is_prose: 'Credential named in prose',
  sudo_prose: 'Password stated as sudo',
  bearer_token: 'Bearer token',
  basic_auth_header: 'Basic auth header',
}

const label = (d) => DETECTOR_LABELS[d] || d

function area(path) {
  const parts = path.split('/')
  if (parts[0] === 'projects' && parts.includes('memory')) return 'memory (loads into sessions)'
  if (parts[0] === 'projects') return 'session transcripts & caches'
  if (['skills', 'agents', 'rules'].includes(parts[0])) return `${parts[0]} (loads into sessions)`
  if (parts[0] === 'archive') return 'archive'
  return parts.length === 1 ? 'config' : parts[0]
}

export default function Secrets({ bump }) {
  const [refresh, setRefresh] = useState(0)
  const [status, setStatus] = useState('open')
  const { data, loading } = useData(`/secrets?status=${status}`, bump + refresh)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)
  const [scanResult, setScanResult] = useState(null)
  const findings = data?.findings || []
  const [page, pager] = usePager(findings, 25)

  const act = async (path, body = {}) => {
    setBusy(path)
    setErr(null)
    try {
      const out = await api(path, { body })
      if (out.next_step) setScanResult({ note: out.next_step })
      return out
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(null)
      setRefresh((r) => r + 1)
    }
  }

  const scan = async (includeTranscripts) => {
    setBusy('scan')
    setErr(null)
    setScanResult(null)
    try {
      const out = await api('/secrets/scan', { body: { include_transcripts: includeTranscripts } })
      setScanResult(out)
    } catch (e) {
      setErr(e.message)
    }
    setBusy(null)
    setRefresh((r) => r + 1)
  }

  // The consequence is stated in the UI beside the button, not inside a dialog
  // nobody reads. See the caption under Findings.
  const quarantine = (f) => act(`/secrets/${f.id}/quarantine`)

  const counts = data?.counts || {}
  const openCount = counts.open || 0

  return (
    <>
      <ViewHead
        title="Credentials"
        helpId="secrets"
        hint="Scans your AI workspace for passwords, API keys and tokens sitting in cleartext. Report-only: it finds and flags, and never edits a file on its own."
      />

      {openCount > 0 && (
        <div className="panel alarm">
          <h2>
            {openCount} unresolved {openCount === 1 ? 'finding' : 'findings'}
          </h2>
          <p className="sechint">
            A credential in this tree is readable by every session on this machine, and the miner reads the same files
            before sending excerpts to a model. Rotation is the only real fix — moving or deleting the file does not
            undo a disclosure.
          </p>
        </div>
      )}

      <div className="panel">
        <h2>
          Scan — <b>look for credentials now</b>
        </h2>
        <p className="sechint">
          Runs automatically each night at 02:00, ahead of mining. Markdown, settings and config files are always
          checked; session transcripts are opt-in because there are tens of thousands of them.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="act" disabled={!!busy} onClick={() => scan(false)}>
            {busy === 'scan' ? 'Scanning…' : 'Scan workspace'}
          </button>
          <button type="button" className="act ghost" disabled={!!busy} onClick={() => scan(true)}>
            Scan including transcripts (slow)
          </button>
        </div>
        {scanResult && (
          <div className="scanline" style={{ marginTop: 10 }}>
            {scanResult.note ? (
              <b>{scanResult.note}</b>
            ) : (
              <>
                Scanned <b>{scanResult.files_scanned}</b> files
                {scanResult.transcripts_included ? ' (transcripts included)' : ' (transcripts skipped)'} —{' '}
                <b>{scanResult.findings}</b> findings, <b>{scanResult.new_findings}</b> new,{' '}
                <b>{scanResult.open_findings}</b> still open.
                {scanResult.truncated && ' ⚠ File cap reached: coverage is incomplete.'}
                {scanResult.files_unreadable > 0 && ` ${scanResult.files_unreadable} files could not be read.`}
              </>
            )}
          </div>
        )}
        {data?.last_scan && !scanResult && <div className="faint">Last scan: {data.last_scan.detail}</div>}
      </div>

      {err && (
        <div className="err" role="alert">
          {err}
        </div>
      )}

      <div className="panel">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0 }}>Findings</h2>
          <div style={{ display: 'flex', gap: 6 }}>
            {['open', 'acknowledged', 'quarantined'].map((s) => (
              <button key={s} type="button" className={s === status ? 'act' : 'act ghost'} onClick={() => setStatus(s)}>
                {s} {counts[s] ? `(${counts[s]})` : ''}
              </button>
            ))}
          </div>
        </div>
        <p className="sechint">
          No row shows the credential. You get the detector, the location, and the line with the value replaced — enough
          to find it and fix it, useless to anyone else. Two findings showing the same short code are the same secret in
          both places. <b>Moving a file</b> takes it out of your workspace so sessions stop reading it — it does not
          undo the leak, so rotate the credential either way.
        </p>

        {loading && <div className="loading">scanning findings</div>}
        {!loading && findings.length === 0 && (
          <div className="faint">
            {status === 'open'
              ? 'No open findings. If you have never run a scan, that means "not looked" rather than "clean" — use Scan workspace above.'
              : `Nothing ${status}.`}
          </div>
        )}

        {page.map((f) => (
          <details key={f.id} className={f.confidence === 'high' ? 'finding hot' : 'finding'}>
            <summary>
              <span className={f.confidence === 'high' ? 'chip hot' : 'chip'}>{f.confidence}</span> {label(f.detector)}{' '}
              <span className="dim">
                — {f.path}:{f.line}
              </span>
            </summary>
            <div style={{ padding: '8px 0 10px 14px' }}>
              <div className="dim" style={{ marginBottom: 6 }}>
                {area(f.path)} · fingerprint <code>{f.fingerprint}</code> · first seen {f.first_seen_at?.slice(0, 16)}
              </div>
              <pre className="finding-context">{f.context}</pre>
              {f.note && <div className="faint">{f.note}</div>}
              {status === 'open' && (
                <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    className="act ghost"
                    disabled={!!busy}
                    onClick={() => act(`/secrets/${f.id}/acknowledge`, { note: 'handled from the console' })}
                  >
                    Acknowledge
                  </button>
                  <ConfirmButton
                    className="act warn"
                    confirmLabel="Move the whole file?"
                    disabled={!!busy}
                    onConfirm={() => quarantine(f)}
                  >
                    Move file out of workspace
                  </ConfirmButton>
                </div>
              )}
            </div>
          </details>
        ))}
        {pager}
      </div>
    </>
  )
}
