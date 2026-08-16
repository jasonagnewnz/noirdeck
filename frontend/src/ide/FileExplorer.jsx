import { useEffect, useRef, useState } from 'react'
import { ChevronIcon, FileDotIcon } from './icons.jsx'
import { getJSON } from './ideApi.js'

function Node({ project, entry, cache, onOpenFile }) {
  const [open, setOpen] = useState(false)
  const [children, setChildren] = useState(cache.current.get(entry.path) || null)
  const [err, setErr] = useState(null)
  const isDir = entry.type === 'dir'

  const toggle = async () => {
    if (!isDir) {
      onOpenFile(entry)
      return
    }
    if (!open && children === null) {
      try {
        const kids = await getJSON(`/files/${project}?path=${encodeURIComponent(entry.path)}`)
        cache.current.set(entry.path, kids)
        setChildren(kids)
      } catch (e) {
        setErr(e.message)
        return
      }
    }
    setOpen((o) => !o)
  }

  return (
    <div className="ftree-node">
      <button
        type="button"
        className={`ftree-row ${isDir ? 'dir' : 'file'}`}
        onClick={toggle}
        aria-expanded={isDir ? open : undefined}
      >
        {isDir ? <ChevronIcon className={`chev ${open ? 'open' : ''}`} /> : <FileDotIcon className="filedot" />}
        <span className="ftree-name">{entry.name}</span>
      </button>
      {isDir && open && (
        <div className="ftree-children">
          {err && <div className="ftree-empty err">{err}</div>}
          {!err && children && children.length === 0 && <div className="ftree-empty">empty</div>}
          {!err &&
            children &&
            children.map((c) => (
              <Node key={c.path} project={project} entry={c} cache={cache} onOpenFile={onOpenFile} />
            ))}
        </div>
      )}
    </div>
  )
}

// Lazy file tree over GET /api/files/{project}?path=<rel>. Root re-fetched
// (and the child cache reset) whenever the project changes.
export default function FileExplorer({ project, onOpenFile, collapsed, onToggleCollapse }) {
  const [root, setRoot] = useState(null)
  const [err, setErr] = useState(null)
  const cache = useRef(new Map())

  useEffect(() => {
    setRoot(null)
    setErr(null)
    cache.current = new Map()
    if (!project) return
    let alive = true
    getJSON(`/files/${project}`)
      .then((d) => alive && setRoot(d))
      .catch((e) => alive && setErr(e.message))
    return () => {
      alive = false
    }
  }, [project])

  if (collapsed) {
    return (
      <div className="explorer collapsed">
        <button
          className="explorer-toggle"
          title="Show explorer"
          aria-label="Show explorer"
          aria-expanded="false"
          onClick={onToggleCollapse}
        >
          <ChevronIcon />
        </button>
      </div>
    )
  }

  return (
    <div className="explorer">
      <div className="explorer-head">
        <span id="explorer-heading">Explorer</span>
        <button
          className="explorer-toggle"
          title="Collapse explorer"
          aria-label="Collapse explorer"
          aria-expanded="true"
          onClick={onToggleCollapse}
        >
          <ChevronIcon className="open-left" />
        </button>
      </div>
      <div className="explorer-body" aria-labelledby="explorer-heading">
        {err && (
          <div className="err" role="alert" style={{ padding: '8px 12px' }}>
            {err}
          </div>
        )}
        {!err && !root && (
          <div className="faint" style={{ padding: '8px 12px' }}>
            loading tree…
          </div>
        )}
        {!err && root && root.length === 0 && (
          <div className="faint" style={{ padding: '8px 12px' }}>
            no files
          </div>
        )}
        {!err &&
          root &&
          root.map((e) => <Node key={e.path} project={project} entry={e} cache={cache} onOpenFile={onOpenFile} />)}
      </div>
    </div>
  )
}
