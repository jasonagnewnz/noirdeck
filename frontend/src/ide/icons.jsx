import React from 'react'

// Inline-SVG stroke icon set for the activity bar. Hand-drawn, zero external
// assets (matches the zero-egress posture already established for fonts).
// All icons are decorative by default — the interactive control they sit in
// (a button with its own aria-label, a link, etc.) carries the accessible
// name, so the glyph itself is hidden from assistive tech and out of the tab
// order. Pass aria-hidden={false} at a call site if an icon is ever used
// standalone without a labeled parent control.
const base = {
  width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round',
  'aria-hidden': 'true', focusable: 'false',
}

export const OverviewIcon = (p) => (
  <svg {...base} {...p}>
    <rect x="3" y="3" width="7.5" height="7.5" rx="1" /><rect x="13.5" y="3" width="7" height="7.5" rx="1" />
    <rect x="3" y="13" width="7" height="8" rx="1" /><rect x="13" y="13" width="8" height="8" rx="1" />
  </svg>
)

export const WorkspaceIcon = (p) => (
  <svg {...base} {...p}>
    <rect x="2.5" y="4" width="19" height="16" rx="1.6" />
    <path d="M7 9.5l3 2.7-3 2.7" /><path d="M13 15h4.5" />
  </svg>
)

export const BuildsIcon = (p) => (
  <svg {...base} {...p}>
    <path d="M13 2 4.5 14h5.5l-1 8 9-12h-5.5l1-8z" />
  </svg>
)

export const DesignIcon = (p) => (
  <svg {...base} {...p}>
    <circle cx="8" cy="8" r="2.6" /><circle cx="16" cy="8" r="2.6" />
    <circle cx="8" cy="16" r="2.6" /><circle cx="16" cy="16" r="2.6" />
  </svg>
)

export const SessionsIcon = (p) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7.5v5l3.3 1.9" />
  </svg>
)

export const SkillsIcon = (p) => (
  <svg {...base} {...p}>
    <rect x="6" y="6" width="12" height="12" rx="1.6" />
    <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
  </svg>
)

export const MemoriesIcon = (p) => (
  <svg {...base} {...p}>
    <ellipse cx="12" cy="5.5" rx="7" ry="2.6" />
    <path d="M5 5.5v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-6" />
    <path d="M5 11.5v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-6" />
  </svg>
)

export const ProposalsIcon = (p) => (
  <svg {...base} {...p}>
    <rect x="3.5" y="3.5" width="17" height="17" rx="2" />
    <path d="M8 12.2l2.6 2.6L16.5 9" />
  </svg>
)

export const QueueIcon = (p) => (
  <svg {...base} {...p}>
    <path d="M20 14.2A8.4 8.4 0 1 1 9.8 4a7 7 0 0 0 10.2 10.2z" />
  </svg>
)

export const QualityIcon = (p) => (
  <svg {...base} {...p}>
    <path d="M12 3l7 3v6c0 5-3.5 7.5-7 9-3.5-1.5-7-4-7-9V6l7-3z" />
    <path d="M9 12l2 2 4-4.2" />
  </svg>
)

export const ICONS = {
  overview: OverviewIcon,
  workspace: WorkspaceIcon,
  builds: BuildsIcon,
  design: DesignIcon,
  sessions: SessionsIcon,
  skills: SkillsIcon,
  memories: MemoriesIcon,
  proposals: ProposalsIcon,
  queue: QueueIcon,
  quality: QualityIcon,
}

export const ChevronIcon = (p) => (
  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...p}>
    <path d="M8 5l8 7-8 7" />
  </svg>
)

export const FileDotIcon = (p) => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...p}>
    <path d="M6 2.5h8l4 4v15H6z" /><path d="M14 2.5V7h4" />
  </svg>
)
