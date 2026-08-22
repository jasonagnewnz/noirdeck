// Thin GET helper for the IDE-shell components (file tree, file viewer, status
// bar polling). Kept separate from src/api.js: that file is shared with the
// rest of the app and this task only owns src/ide/*.
export async function getJSON(path) {
  const r = await fetch(`/api${path}`)
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail || detail
    } catch {
      /* keep statusText */
    }
    throw new Error(detail)
  }
  return r.json()
}
