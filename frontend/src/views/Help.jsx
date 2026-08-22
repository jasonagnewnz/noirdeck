import { useEffect } from 'react'
import { ViewHead } from '../ui.jsx'

// The manual. Deep-linkable: #help:queue jumps straight to the Run later chapter:
// every view's "how this works →" header link lands here on its own section.
const SECTIONS = [
  ['about', 'What noirdeck is'],
  ['interface', 'Reading the interface'],
  ['overview', 'Home'],
  ['workspace', 'Build live'],
  ['builds', 'Builds'],
  ['design', 'Design'],
  ['sessions', 'History'],
  ['skills', 'Helpers'],
  ['memories', 'Knowledge'],
  ['proposals', 'Review'],
  ['queue', 'Tasks'],
  ['quality', 'Checks'],
  ['secrets', 'Credentials'],
  ['safety', 'The safety model'],
  ['automation', 'Background automation'],
  ['keys', 'Keyboard & palette'],
  ['trouble', 'Troubleshooting'],
]

const anchorFromHash = () => {
  const [view, anchor] = window.location.hash.replace(/^#\/?/, '').split(':')
  return view === 'help' && anchor ? anchor : null
}

function Sec({ id, title, children }) {
  return (
    <div className="panel" id={`help-${id}`}>
      <h2>{title}</h2>
      {children}
    </div>
  )
}

export default function Help() {
  useEffect(() => {
    const scroll = () => {
      const a = anchorFromHash()
      if (!a) return
      document.getElementById(`help-${a}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    scroll()
    window.addEventListener('hashchange', scroll)
    return () => window.removeEventListener('hashchange', scroll)
  }, [])

  return (
    <>
      <ViewHead
        title="Guide"
        hint="The full manual: what each view does, how the safety model works, and what runs while you sleep."
      />

      <nav className="help-toc" aria-label="Help sections">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#help:${id}`}>
            {label}
          </a>
        ))}
      </nav>

      <Sec id="about" title="What noirdeck is">
        <p className="help">
          noirdeck.dev is a local build studio for people who want great software without managing a pile of AI tools by
          hand. It watches your projects, remembers useful ways of working, runs carefully-caged automation on your
          behalf, and turns risky changes into <b>decisions you approve</b>: it never rewrites your work on its own.
        </p>
        <ul className="helplist">
          <li>
            <b>Local only</b>: the server binds 127.0.0.1; nothing is exposed to the network.
          </li>
          <li>
            <b>Approve-first</b>: the single write path into your AI workspace knowledge is you approving a change in
            Review. Applied changes keep a pre-apply snapshot and can be reverted.
          </li>
          <li>
            <b>Fail-closed</b>: every autonomous capability sits behind an env master flag AND an expiring arming
            contract; if either is missing, it does not run.
          </li>
        </ul>
      </Sec>

      <Sec id="interface" title="Reading the interface">
        <h3>Status pills</h3>
        <ul className="helplist">
          <li>
            <span className="pill BLOCKER">BLOCKER</span>: red border: broken, failing, or genuinely stuck. Needs
            action.
          </li>
          <li>
            <span className="pill GAP">GAP</span> / <span className="pill queued">queued</span>: accent border: waiting,
            incomplete, or worth attention soon.
          </li>
          <li>
            <span className="pill running">running</span>: something is actively in flight.
          </li>
          <li>
            <span className="pill PASS">PASS</span> / <span className="pill done">done</span>: deliberately quiet, no
            signal color: resolved states should not compete for your eye.
          </li>
        </ul>
        <h3>Everything else</h3>
        <ul className="helplist">
          <li>
            <b>Build studio</b>: Home starts with a project picker and one outcome box. Type what you want built and
            noirdeck routes it to live work, design, background tasks or a read-only answer.
          </li>
          <li>
            <b>Add essentials</b>: click a common product need, answer targeted questions, then send the generated brief
            to live work or background tasks. Turn on memories + preferences to reuse a method Noirdeck has seen work
            for that project.
          </li>
          <li>
            <span className="chip">chips</span> label and categorise; <span className="chip hot">accent chips</span>{' '}
            mark the active or armed one.
          </li>
          <li>
            Sidebar <b>badges</b> count items waiting on you: reviews, blocked tasks and open loops.
          </li>
          <li>
            The status-bar <b>dot</b> is live server connectivity: green = event stream connected, red = the server is
            unreachable.
          </li>
          <li>
            Panels open with an <b>uppercase title</b> and a one-line statement of what that section does. Card lists
            sit under a labelled header with a count.
          </li>
        </ul>
      </Sec>

      <Sec id="overview" title="Home">
        <p className="help">
          Your start page. The <b>Build studio</b> leads: pick a project, type the outcome, and jump straight into the
          right path. <b>Add essentials</b> turns common product needs into guarded, project-ready briefs: payments,
          auth, domains, hosting, database, email, uploads, analytics, admin and release. Its optional memories +
          preferences toggle can suggest "reuse this method" before sending the job. Below that, a deterministic
          <b>digest</b> (computed from real data, not model output) shows what happened since you last looked: finished
          background tasks, reviews waiting, automation spend and backup age.
        </p>
      </Sec>

      <Sec id="workspace" title="Build live">
        <p className="help">
          Live AI sessions in the browser: choose <b>where</b> the work happens, <b>who</b> should do it, then work in
          an embedded terminal with a read-only file explorer beside it. Work supports Claude, Codex, Ollama local
          models and configured custom tools.
        </p>
        <ul className="helplist">
          <li>
            Terminals are real PTYs running server-owned runner commands such as <b>claude</b>, <b>codex</b>, or{' '}
            <b>ollama</b>; working directories are allowlisted to your projects folder.
          </li>
          <li>
            <b>Remembered choice</b>: save your usual tool once, then override it per live session or run-later task
            when a repo needs a different model.
          </li>
          <li>
            <b>Transfer packs</b> summarize repo context, recent source sessions and durable memory so another runtime
            can start with the same orientation.
          </li>
          <li>
            <b>Suggest method</b> checks saved preferences, recent queued work, paused sessions, handoff packs and
            memory notes for the selected repo, then offers to reuse that method or let you choose different.
          </li>
          <li>
            <b>Switch to</b>: while a terminal tab is active, pick another model/tool and start a new session in the
            same repo with a handoff brief from the current terminal context. Enable <b>close source</b> to replace the
            old session instead of keeping both.
          </li>
          <li>Run-later tasks can be created from Work without opening a terminal tab.</li>
          <li>The file viewer is read-only: editing happens through the session itself.</li>
          <li>
            Codex may ask whether you trust a repo. That prompt comes from Codex; choose yes only for repos you trust.
          </li>
          <li>
            A focused terminal keeps its own keys (including Ctrl+B); the app only steals shortcuts when you are outside
            it.
          </li>
        </ul>
      </Sec>

      <Sec id="builds" title="Builds">
        <p className="help">
          Describe software; a staged pipeline builds it: <b>plan → build → test → review → finish</b>, with quality
          gates run between phases by ordinary code, not by the model grading itself. Nothing is pushed or deployed: a
          finished build stops at code-ready in a local repo.
        </p>
        <ul className="helplist">
          <li>
            <b>Guided</b> intake asks eight plain-English questions (or start from a recipe card), then{' '}
            <b>parks at the plan</b> for your approval before any code is written. Approve, request changes, or decline.
          </li>
          <li>
            <b>Expert</b> intake takes a full written brief and runs the same pipeline without the plan gate.
          </li>
          <li>
            Builds are <b>resumable</b>: phases commit as they go, so a failure only loses bookkeeping, never work.
          </li>
          <li>If it can't decide something, it parks as a question on the card rather than guessing.</li>
          <li>
            <b>Try it</b> appears on finished builds with a static web entry point: the preview iframe is sandboxed, so
            previewed code has no authority over this app.
          </li>
          <li>The card list is attention-sorted: things waiting on you first, then things moving.</li>
        </ul>
      </Sec>

      <Sec id="design" title="Design">
        <p className="help">
          Restyle a project's frontend safely. Choose a target repo, capture a design from another project or write a
          short UI brief, then three visual directions are mocked in parallel inside one of six ready-to-go UI kits.{' '}
          <b>Mocks never touch the repo</b>; only clicking apply writes the chosen direction to the real frontend, and
          that too stops at code-ready.
        </p>
        <p className="help">
          The kits are plain-language starting points: Landing Page, Dashboard, Booking Flow, Shopfront, Admin Portal
          and Portfolio.
        </p>
      </Sec>

      <Sec id="settings" title="Settings">
        <p className="help">
          The sidebar carries the handful of things you touch in a normal session. Everything else lives in{' '}
          <b>Settings</b>: reachable from the gear at the bottom of the sidebar, or by pressing <kbd>0</kbd>.
        </p>
        <p className="help">
          Nothing was taken away. <b>Design</b>, <b>Helpers</b>, <b>Knowledge</b> and <b>Checks</b> are the same views
          they always were, still with their own links, just no longer competing for a slot you rarely click. Settings
          also holds the theme, what background automation is armed, and which assistants this machine can run.
        </p>
      </Sec>

      <Sec id="sessions" title="History">
        <p className="help">
          Every recorded Claude Code session across the estate, plus full-text search over your entire prompt history:
          the "have I asked this before?" button. <b>resume</b> reopens a past session in Work with its context intact.
        </p>
        <p className="help">
          An <span className="pill GAP">open loop</span> marks a session that looks unfinished: worth resuming or
          closing out.
        </p>
      </Sec>

      <Sec id="skills" title="Skills + Agents">
        <p className="help">
          The installed capability surface: every skill and subagent your sessions can already use without re-prompting.
          Read-only inventory: skills are created or refined through the Proposals spine, never edited here.
        </p>
      </Sec>

      <Sec id="memories" title="Memories">
        <p className="help">
          Everything your sessions remember, across every project namespace, with upkeep tooling to keep that knowledge
          base lean.
        </p>
        <ul className="helplist">
          <li>
            <b>Hygiene</b> scans a namespace for duplicates, near-empty and oversized files, dangling [[links]], and
            index drift. It is read-only: "propose merge" drafts a consolidation through Proposals; nothing is rewritten
            or deleted directly.
          </li>
          <li>
            <b>Grouped themes</b> are clusters the miner spotted: repeated memory topics that may deserve one canonical
            file.
          </li>
          <li>
            <b>All memories</b> is the searchable raw inventory.
          </li>
        </ul>
      </Sec>

      <Sec id="proposals" title="Review">
        <p className="help">
          The single gate between noirdeck and your estate. Everything any subsystem wants to write into{' '}
          <b>~/.claude</b>: mined skills, memory merges, improver output: lands here as a diff and waits. Approve writes
          it; dismiss discards it.
        </p>
        <ul className="helplist">
          <li>
            <b>Mining</b> scans your session history for repeated prompts and patterns worth turning into skills or
            memories. The heuristic pass is instant and local; the LLM pass runs only while armed.
          </li>
          <li>
            Review the <b>diff</b>, not the wall of text: the full proposed content is folded underneath.
          </li>
          <li>
            <b>Applied: still reversible</b>: every applied proposal keeps a pre-apply snapshot; one click reverts it.
            If the file was hand-edited afterwards, the revert asks before clobbering your edits.
          </li>
        </ul>
      </Sec>

      <Sec id="queue" title="Tasks">
        <p className="help">
          Send work off without opening a live terminal. Pick where it should happen, who should do it, and how deep it
          should go. Write the outcome like a good ticket: the more specific the brief, the fewer assumptions get
          logged.
        </p>
        <ul className="helplist">
          <li>
            <b>Arming is a contract, not a switch</b>: an expiry plus task and token budgets. Runs need the env master
            flag AND a live contract; the runner re-checks before every task. Contracts are folded under safety controls
            because most users only need them when unattended work is blocked.
          </li>
          <li>
            <b>Who/model</b>: use the remembered Work choice or override per task. Claude tasks still auto-route a model
            when you leave the model blank; other tools use their configured default unless you type a model.
          </li>
          <li>
            <b>Effort</b>: light = one session; heavy = staged plan → do → check, where the plan pass is
            read-only-caged. Auto routes from the task text.
          </li>
          <li>
            Claude-backed run-later tasks include the pipeline guard that denies push/publish/deploy commands before
            execution. Non-Claude runners are still launched by server-owned argv, but their edit permissions follow
            that CLI's own sandbox and auth model.
          </li>
          <li>
            Anything the run can't decide <b>parks as a question</b> on the task and the night moves on; answering
            re-queues it.
          </li>
        </ul>
      </Sec>

      <Sec id="quality" title="Checks">
        <p className="help">
          Commercial-readiness for every repo in the fleet: each project is scored
          <span className="pill BLOCKER"> BLOCKER</span> / <span className="pill GAP">GAP</span> /
          <span className="pill PASS"> PASS</span> against concrete gates (tests, docs, secrets, git health), with
          evidence per gate. <b>briefing</b> assembles a start-here card for a repo: recent sessions, follow-ons, and
          git state.
        </p>
        <h3>The local improver</h3>
        <ul className="helplist">
          <li>
            A <b>local model via Ollama</b>: zero cloud calls, zero cost: quietly proposes small improvements
            (docstrings, comment tidy, READMEs) to repos you map here.
          </li>
          <li>
            Every change is built in a throwaway worktree on an isolated branch, AST-checked so executable code is
            untouched, diff-capped, and test-gated. <b>Merging is always your click.</b>
          </li>
          <li>
            <b>Estate targets</b> extend it to skills and memory notes: each target must be individually armed
            (expiring, 7 days), and output goes through Proposals, never written directly.
          </li>
          <li>
            It <b>learns from your decisions</b>: merges and discards re-rank future candidates; three discards with no
            merges mutes that kind for the repo until you merge one.
          </li>
        </ul>
      </Sec>

      <Sec id="secrets" title="Credentials">
        <p>
          Passwords, API keys and tokens have a way of ending up in notes. A prompt like &ldquo;the password is
          hunter2&rdquo; becomes a transcript, a transcript becomes a memory file, and that file then loads into every
          session you run. This view finds those and tells you where they are.
        </p>
        <p>
          It runs nightly at 02:00, deliberately ahead of mining at 02:30: mining reads the same files and sends
          excerpts to a model, so anything leaking should be flagged before that happens. You can also scan on demand.
          Markdown, settings and config are always covered; transcripts are opt-in because there are tens of thousands
          of them, and the result always tells you what was actually scanned so &ldquo;nothing found&rdquo; can never be
          confused with &ldquo;did not look&rdquo;.
        </p>
        <p>
          <b>No finding ever shows you the secret.</b> You get the kind of credential, the file and line, the source
          line with the value replaced, and a fingerprint: a hash, so the same fingerprint appearing in two files tells
          you it is one secret in both places. Showing a &ldquo;safe&rdquo; few characters of a password would simply
          move the password somewhere new.
        </p>
        <p>
          Two actions, both yours: <b>Acknowledge</b> records that you have dealt with it or that it is a false
          positive, and changes no file. <b>Move file out of workspace</b> relocates the whole file to{' '}
          <code>~/noirdeck-quarantine</code> so it stops loading into sessions. Neither is a fix. A credential that has
          been sitting in a file readable by every session, and copied into transcripts and backups, is disclosed.{' '}
          <b>rotate it</b>.
        </p>
      </Sec>

      <Sec id="safety" title="The safety model">
        <p className="help">Independent layers: any one failing still leaves the others standing:</p>
        <ul className="helplist">
          <li>
            <b>Local-only server</b>: binds 127.0.0.1, with host/origin allowlist middleware against DNS-rebinding.
            Never tunnel it without adding auth.
          </li>
          <li>
            <b>Propose-only spine</b>: the only write path into ~/.claude is proposal approval, allowlisted to skills
            and the primary memory namespace, traversal-checked, audited, and reversible via pre-apply snapshots.
          </li>
          <li>
            <b>Double gates on autonomy</b>: env master flag AND an expiring arming contract with task/token budgets,
            re-checked before every unit of work.
          </li>
          <li>
            <b>Harness-level guard</b>: pipeline sessions launch with a pre-execution hook that denies push, publish,
            deploy and remote-access commands: enforcement below the model, not a polite instruction.
          </li>
          <li>
            <b>Cages and sandboxes</b>: mock and build previews render in sandboxed iframes; the improver works in temp
            worktrees with AST verification; the ask endpoint runs with read-only tools.
          </li>
          <li>
            <b>Audit trail</b>: arming, approvals, reverts, skips and failures are recorded: silent failure is treated
            as a defect.
          </li>
        </ul>
      </Sec>

      <Sec id="automation" title="Background automation">
        <p className="help">Four recurring jobs run on user-level systemd timers while their gates are open:</p>
        <ul className="helplist">
          <li>
            <b>Run later</b>: runs queued tasks without a live terminal (needs a live arming contract).
          </li>
          <li>
            <b>Miner</b>: scans new session history for skill/memory candidates; drafts land in Proposals.
          </li>
          <li>
            <b>Vault</b>: encrypted, restore-verified offsite backup of memories, skills, agents, config and
            unpushed-work bundles. The status bar shows time since the last <b>verified restore</b>, not just the last
            run. Keep the vault passphrase escrowed somewhere that survives this machine.
          </li>
          <li>
            <b>Improver</b>: hourly pass proposing small changes to mapped repos and armed estate targets.
          </li>
        </ul>
        <p className="help">
          Inspect or adjust cadence with <kbd>systemctl --user list-timers 'noirdeck-*'</kbd>.
        </p>
      </Sec>

      <Sec id="keys" title="Keyboard & palette">
        <ul className="helplist">
          <li>
            <kbd>1</kbd>–<kbd>0</kbd> jump between the first ten views; <kbd>Ctrl+B</kbd> toggles the sidebar;{' '}
            <kbd>Esc</kbd> closes overlays.
          </li>
          <li>
            <kbd>Ctrl+K</kbd> opens the command palette: type an outcome to launch it, or search skills, shortcuts and
            tips.
          </li>
          <li>
            <kbd>?</kbd> opens quick keys, including the full Claude Code reference (session keys, slash commands, CLI
            flags) with click-to-copy.
          </li>
          <li>
            Every view header's <b>how this works →</b> link lands on its chapter here.
          </li>
        </ul>
      </Sec>

      <Sec id="trouble" title="Troubleshooting">
        <ul className="helplist">
          <li>
            <b>Status dot is red</b>: the server is down or restarting; the page reconnects automatically when it
            returns.
          </li>
          <li>
            <b>"local model offline"</b> in the improver: start Ollama, then re-check; the first generation after a cold
            start can take minutes while the model loads.
          </li>
          <li>
            <b>Only Claude appears in Workspace</b>: the browser is probably talking to an old backend, or the runner
            binary is missing. Restart the current noirdeck backend and check <b>/api/workspace/runtimes</b>.
          </li>
          <li>
            <b>Codex opens and waits</b>: Codex may ask whether you trust that repo. Choose yes only for repos you
            trust; after that the session continues normally.
          </li>
          <li>
            <b>Helper marked "not found"</b>: install the CLI or set its binary env var, for example{' '}
            <b>NOIRDECK_CODEX_BIN</b>, <b>NOIRDECK_OLLAMA_BIN</b> or <b>NOIRDECK_GROK_BIN</b>.
          </li>
          <li>
            <b>"run blocked / disarmed"</b>: an env master flag is off or the arming contract expired. Re-arm in the Run
            later view (overnight, mining) or arm the specific target (improver).
          </li>
          <li>
            <b>Overnight tasks didn't run</b>: check the arming contract wasn't expired or its budget spent, and that
            the machine was awake in the window; the timers are deliberately not catch-up-on-boot for token-burning
            jobs.
          </li>
          <li>
            <b>A queue task is blocked with a question</b>: that's by design: answer it on the card and it re-queues, or
            cancel it.
          </li>
          <li>
            <b>An applied proposal was wrong</b>: Proposals → "Applied: still reversible" → revert. Hand-edits after
            apply are detected and confirmed before being overwritten.
          </li>
        </ul>
      </Sec>
    </>
  )
}
