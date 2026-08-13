import React from 'react'

const fmtSize = (n) => {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

// Read-only file viewer tab: breadcrumb header + generated line-number gutter.
// No syntax highlighting dependency by design — a tasteful minimal look instead.
export default function FileViewer({ tab }) {
  if (tab.error) return <div className="panel"><div className="err" role="alert">{tab.error}</div></div>
  if (tab.loading) return <div className="loading">reading file…</div>

  const lines = (tab.content ?? '').split('\n')
  const crumbs = tab.path.split('/').filter(Boolean)

  return (
    <div className="fileview">
      <div className="fileview-head">
        <span className="fileview-crumbs">
          <span className="dim">{tab.project}</span>
          {crumbs.map((c, i) => (
            <React.Fragment key={i}>
              <span className="faint">/</span>
              <span className={i === crumbs.length - 1 ? 'ink' : 'dim'}>{c}</span>
            </React.Fragment>
          ))}
        </span>
        <span className="fileview-meta">
          {tab.truncated && <span className="pill GAP">truncated</span>}
          <span className="faint">{fmtSize(tab.size)}</span>
        </span>
      </div>
      <div className="fileview-body">
        <pre className="code">
          {lines.map((line, i) => (
            <div className="code-line" key={i}>
              <span className="gutter">{i + 1}</span>
              <span className="code-text">{line.length ? line : ' '}</span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  )
}
