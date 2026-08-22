import { useEffect, useState } from 'react'

const SIZES = [10, 25, 50, 100, 'all']

// Client-side pager: usePager(items) -> [pageOfItems, <PagerBar/>]
export function usePager(items, initialSize = 25) {
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(initialSize)
  const total = items?.length || 0
  const pages = size === 'all' ? 1 : Math.max(1, Math.ceil(total / size))
  useEffect(() => {
    if (page >= pages) setPage(0)
  }, [total, size, pages])
  const view = !items ? [] : size === 'all' ? items : items.slice(page * size, (page + 1) * size)

  // No bar when everything already fits on one page at the smallest size:
  // "1–1 of 1 · 10 25 50 100 all" under a single item is pure noise.
  const bar =
    total <= SIZES[0] ? null : (
      <div className="pager">
        <span className="faint">
          {size === 'all' ? `all ${total}` : `${page * size + 1}–${Math.min((page + 1) * size, total)} of ${total}`}
        </span>
        <span className="pager-sizes">
          {SIZES.map((s) => (
            <button
              key={s}
              className={`pz ${size === s ? 'on' : ''}`}
              onClick={() => {
                setSize(s)
                setPage(0)
              }}
            >
              {s === 'all' ? 'all' : s}
            </button>
          ))}
        </span>
        {pages > 1 && (
          <span className="pager-nav">
            <button className="pz" disabled={page === 0} onClick={() => setPage(0)} aria-label="First page">
              «
            </button>
            <button className="pz" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Previous page">
              ‹
            </button>
            <span className="dim" aria-live="polite">
              {page + 1}/{pages}
            </span>
            <button
              className="pz"
              disabled={page >= pages - 1}
              onClick={() => setPage(page + 1)}
              aria-label="Next page"
            >
              ›
            </button>
            <button
              className="pz"
              disabled={page >= pages - 1}
              onClick={() => setPage(pages - 1)}
              aria-label="Last page"
            >
              »
            </button>
          </span>
        )}
      </div>
    )
  return [view, bar]
}
