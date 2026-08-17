import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const here = dirname(fileURLToPath(import.meta.url))
const pkg = JSON.parse(readFileSync(join(here, 'package.json'), 'utf8'))

function gitCommit() {
  try {
    return execSync('git rev-parse --short HEAD', {
      cwd: resolve(here, '..'),
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
  } catch {
    return ''
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    'import.meta.env.NOIRDECK_FRONTEND_VERSION': JSON.stringify(pkg.version),
    'import.meta.env.NOIRDECK_FRONTEND_BUILT_AT': JSON.stringify(
      process.env.NOIRDECK_FRONTEND_BUILT_AT || new Date().toISOString()
    ),
    'import.meta.env.NOIRDECK_FRONTEND_COMMIT': JSON.stringify(process.env.NOIRDECK_FRONTEND_COMMIT || gitCommit()),
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:4747' },
  },
  build: { outDir: 'dist' },
  test: {
    environment: 'jsdom',
    setupFiles: './tests/setup.js',
  },
})
