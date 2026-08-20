# Getting credentials out of your workspace

Notes are where secrets go to be forgotten. Someone pastes a connection string to debug
something, the note becomes a memory file, the memory file loads into every session, and
a year later it is in a backup, a transcript, and a git history nobody is going to rewrite.

noirdeck's scanner finds them. This document is what to do next, in order, because the
order matters more than the tooling.

---

## The one thing people get wrong

**Moving or deleting the file does not fix anything.** A credential that has sat in a
readable file is disclosed. It is in:

- the file (which you are about to move)
- git history, if the file was ever committed
- session transcripts, if it was ever typed into a prompt or printed by a command
- every backup taken since it first appeared

You cannot chase it through all of those. **Rotate the credential.** Moving the file stops
the ongoing exposure; rotation is what ends it. If you only have time for one, rotate.

---

## Order of work

### 1. Look, before you move anything

```bash
noirdeck run secrets          # scan
noirdeck status               # how many are open
```

Then in the console, **Credentials**. Or plan a bulk move without touching a file:

```
GET /api/secrets/sweep        # grouped by file, moves nothing
```

The plan sorts **files that load into every session first** — `skills/`, `agents/`,
`rules/`, `CLAUDE.md`, anything under a `memory/` directory. Those are the ones actively
being read, so they are the ones worth doing first.

### 2. Triage: is it a credential, or a note about one?

The medium-confidence tier contains false positives by design. `the password is documented
in IT Glue` is a sentence, not a secret. **Acknowledge** those — it records your judgement
and changes no file.

Do not skip this. A sweep that moves 46 files, six of which were prose, teaches you to
distrust the tool.

### 3. Rotate, then move

Rotate first where you can. A moved file whose credential is still live is a false sense
of having dealt with it.

```
POST /api/secrets/sweep   {"ids": [...from the plan...], "confirm": true}
```

⛔ **The id list is deliberately mandatory.** There is no "move everything" call. On this
estate, irreversible actions are selected by explicit id — never by a filter, a status or
a time window — because a bulk action driven by a query does whatever the query happened
to match at that moment. The plan gives you the ids; confirming means confirming *those*.

Files move to `~/noirdeck-quarantine`, named with a timestamp and their original path, so
the move is reversible and auditable. Nothing is deleted.

### 4. Store the replacements somewhere that is not a note

---

## Where credentials should live instead

The rule that matters: **the secret should exist in exactly one place your tools can read,
and nowhere a human copies from.** Everything below is a way of achieving that.

| Where | Good for | Watch out for |
|---|---|---|
| **A password manager** (1Password, Bitwarden) with its CLI | Human-held credentials — the ones you personally type or paste | The CLI needs a session; scripted use wants a service account, not your personal vault |
| **A cloud secret manager** (AWS Secrets Manager, Google Secret Manager, Azure Key Vault) | Anything a server or a job reads | Costs a little per secret; needs IAM that is itself managed. Read at *start-up*, never bake into an image |
| **Platform secret stores** (GitHub Actions secrets, Cloudflare Worker secrets, systemd `LoadCredential`) | CI and deployed services | Scoped to that platform. A secret in three platforms is three rotations |
| **A `.env` file, gitignored, mode 600** | Local development only | ⛔ It ends up in backups and in `ps` output if exported carelessly. Never for anything production |
| **`gpg` symmetric encryption, offline** | Break-glass copies you must not lose | The passphrase becomes the thing you can lose. Store it apart from the file |

### Rules that survive contact with reality

1. **Reference, never copy.** `API_KEY=$(op read op://vault/item/field)` beats pasting the
   value. A copied secret is a second thing to rotate and a second thing to leak.
2. **Read at start-up, not at build time.** A secret baked into an image or a wheel ships
   everywhere that artifact goes.
3. **⛔ Never in a filename or a note "temporarily".** Every leak this scanner has found
   was temporary when it was written.
4. **Rotate on a schedule you actually keep**, even a slow one. An un-rotated credential is
   one whose exposure history you can no longer reason about.
5. **⛔⛔ Partial redaction is not redaction.** `sk-abc…` in a ticket, a log or a status
   page is a leak with a smaller font. This is why noirdeck's own findings never show the
   secret, only a hash.
6. **Assume a secret in a prompt is permanent.** It is in a transcript now. noirdeck
   redacts before sending excerpts to a model, but the transcript on disk keeps what you
   typed.

---

## Two things noirdeck deliberately will not do

**It will not edit the secret out of a file.** That would modify a file noirdeck did not
create — against the standing create-only rule — leave the value in history, and give you
the impression the credential is safe when only rotation makes it so.

**It will not rotate anything for you.** Rotation touches live systems: an API you might
break, a service account something depends on, a password someone else also uses. That is
an operator action with a blast radius noirdeck cannot see.

---

## Related

- `backend/noirdeck/secrets_scan.py` — detectors, and why a finding never carries the secret
- `docs/LICENCE_KEY_CUSTODY.md` — the same discipline applied to the one credential that
  cannot be rotated cheaply
- `PROJECT_PLAN.md` — the open findings on this estate and their concentration
