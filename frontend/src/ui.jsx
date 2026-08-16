// Every view opens with the same anatomy: what this page IS (title), what it
// DOES (one-sentence hint), and a jump to its chapter in the Help manual.
// The link is a plain hash href — App's hashchange listener switches the view
// and the Help view scrolls itself to the matching section.
export function ViewHead({ title, hint, helpId }) {
  return (
    <div className="viewhead">
      <div className="viewhead-row">
        <h1>{title}</h1>
        {helpId && (
          <a className="headlink" href={`#help:${helpId}`}>
            how this works →
          </a>
        )}
      </div>
      {hint && <p>{hint}</p>}
    </div>
  )
}
