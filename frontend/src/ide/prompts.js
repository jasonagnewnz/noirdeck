// Prompt text for the project actions strip. Live variants are pasted into a
// fresh terminal session (see TermPane's injectPrompt); overnight variants are
// phrased for an unattended queue run and always land as a committed report,
// never a direct edit.

export const REVIEW_LIVE =
  "Act as a demanding principal engineer. Review this repository's structure and code against " +
  'best practice: layering, naming, dead code, duplication, test coverage, docs. Produce a ' +
  'prioritized findings list with file:line refs, then STOP and wait for my direction — do not ' +
  'change code until I approve.'

export const REVIEW_OVERNIGHT =
  "Act as a demanding principal engineer running autonomously overnight. Review this repository's " +
  'structure and code against best practice: layering, naming, dead code, duplication, test ' +
  'coverage, docs. Produce a prioritized findings list with file:line refs as a markdown report ' +
  'committed to the repo in small reviewed commits. Never delete or modify existing code — ' +
  'findings only.'

export const TIDY_LIVE =
  "Work through this codebase's comments and legacy code: list stale/noise comments to remove, " +
  'constraint comments to keep, dead code candidates with evidence. Propose the cleanup as a ' +
  'findings list first; only apply once I approve, then in small reviewed commits.'

export const TIDY_OVERNIGHT =
  "Work through this codebase's comments and legacy code autonomously: list stale/noise comments " +
  'to remove, constraint comments to keep, dead code candidates with evidence. Produce the ' +
  'findings as a markdown report file committed to the repo. Never delete or modify existing code ' +
  '— findings only.'

export const ACTIONS = [
  { key: 'review', label: 'Review structure', live: REVIEW_LIVE, overnight: REVIEW_OVERNIGHT },
  { key: 'tidy', label: 'Tidy comments & legacy', live: TIDY_LIVE, overnight: TIDY_OVERNIGHT },
]
