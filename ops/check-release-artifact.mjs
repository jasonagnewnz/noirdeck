// Does the artifact the installer would fetch match the source in this tree?
//
// ⛔ WHAT THIS PROTECTS (2026-08-23). noirdeck is distributed from noirdeck.dev
// rather than a package index, so the thing customers install is an object in a
// bucket that someone uploaded by hand. That object drifted: for several hours
// the download served a build made before the clickjacking fix, the licence
// panel and the platform detection went in. Nothing reported it, because the
// version number had not moved either, so every check compared a stale artifact
// against a stale expectation and agreed.
//
// This compares three things that must all say the same version:
//   backend/noirdeck/version.py   what the source is
//   pyproject.toml                what a build would be named
//   src/worker.ts LATEST          what /dl/<key>/latest actually hands over
//
// It cannot see inside the bucket from CI, and does not try to: the worker's
// allowlist is the name it will serve, so agreeing with it is the check that can
// be made without credentials. Uploading the object remains a release step.
//
// Run: node ops/check-release-artifact.mjs   (exit 1 on any disagreement)
import { readFileSync } from 'node:fs'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
const fail = (msg) => {
  console.error(`FAIL ${msg}`)
  process.exitCode = 1
}

const source = read('../backend/noirdeck/version.py').match(/VERSION = "([^"]+)"/)?.[1]
const packaged = read('../pyproject.toml').match(/^version = "([^"]+)"/m)?.[1]

// The website is a sibling checkout and is not always present; skip rather than
// fail when it is absent, and say so, because a check that quietly does nothing
// is worse than one that is not there.
let served = null
try {
  served = read('../../noirdeck-website/src/worker.ts').match(/const LATEST = '([^']+)'/)?.[1]
} catch {
  console.log('note: the website checkout is not beside this one, so the served name was not checked')
}

if (!source) fail('could not read VERSION from backend/noirdeck/version.py')
if (!packaged) fail('could not read version from pyproject.toml')
if (source && packaged && source !== packaged) {
  fail(`pyproject says ${packaged}, the package says ${source}`)
}
if (served) {
  const expected = `noirdeck-${source}-py3-none-any.whl`
  if (served !== expected) {
    fail(`the installer would fetch ${served}, but this tree builds ${expected}`)
  } else {
    console.log(`pass  served artifact ${served}`)
  }
}
if (!process.exitCode) console.log(`pass  version ${source} agrees across the tree`)
