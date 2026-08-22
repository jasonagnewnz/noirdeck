import { useEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), ' +
  'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

// Shared modal-dialog focus behavior for Palette / KeysOverlay: moves focus
// into the dialog on open, traps Tab/Shift+Tab so it cycles inside the
// container instead of escaping to the page behind it, and restores focus to
// whatever had it before the dialog opened once it closes.
//
// `containerRef` must point at the dialog panel (not the backdrop). Mark the
// element that should receive initial focus with `data-autofocus`: falls
// back to the first focusable element, then the container itself.
export function useFocusTrap(containerRef, open) {
  const restoreRef = useRef(null)

  useEffect(() => {
    if (!open) return
    restoreRef.current = document.activeElement

    const container = containerRef.current
    const focusables = () => Array.from(container?.querySelectorAll(FOCUSABLE) || [])

    const initial = container?.querySelector('[data-autofocus]') || focusables()[0] || container
    // let the dialog finish its first paint before stealing focus
    const raf = requestAnimationFrame(() => initial?.focus())

    const onKeyDown = (e) => {
      if (e.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    // capture phase so the trap wins regardless of what else is listening
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      cancelAnimationFrame(raf)
      document.removeEventListener('keydown', onKeyDown, true)
      restoreRef.current?.focus?.()
    }
  }, [open])
}
