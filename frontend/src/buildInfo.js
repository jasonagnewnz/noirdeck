const env = import.meta.env || {}

export const FRONTEND_VERSION = env.NOIRDECK_FRONTEND_VERSION || 'dev'
export const FRONTEND_BUILT_AT = env.NOIRDECK_FRONTEND_BUILT_AT || new Date().toISOString()
export const FRONTEND_COMMIT = env.NOIRDECK_FRONTEND_COMMIT || ''
export const FRONTEND_LOADED_AT = new Date().toISOString()

const pad = (n) => String(n).padStart(2, '0')

export function compactDateTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'unknown'
  return [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`,
  ].join(' ')
}

export function isoDateTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'unknown'
  return date.toISOString()
}
