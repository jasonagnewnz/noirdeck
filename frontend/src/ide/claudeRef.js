// Claude Code reference: single source of truth for the quick-keys overlay
// tabs and the command palette's shortcut section. CLI flags verified against
// the installed CLI (claude 2.1.229); REPL keys / slash commands curated.

export const REPL_KEYS = [
  ['Esc', 'interrupt Claude mid-turn'],
  ['Esc Esc', 'rewind: jump back to an earlier message and edit it'],
  ['Shift+Tab', 'cycle permission modes: manual → auto-accept → plan'],
  ['Tab', 'toggle extended thinking for the next turn'],
  ['Ctrl+B', 'move the running task to the background'],
  ['Ctrl+C', 'clear input / cancel: twice to exit'],
  ['Ctrl+D', 'exit the session (EOF)'],
  ['Ctrl+L', 'clear the screen (conversation kept)'],
  ['Ctrl+O', 'expand / collapse verbose output'],
  ['Ctrl+R', 'reverse-search prompt history'],
  ['Ctrl+V', 'paste an image from the clipboard'],
  ['Ctrl+Z', 'suspend to the shell: fg to come back'],
  ['↑ / ↓', 'walk prompt history'],
  ['Shift+Enter', 'newline without sending (after /terminal-setup)'],
]

export const PROMPT_TRICKS = [
  ['/', 'slash commands + your skills'],
  ['@path', 'mention a file or directory (fuzzy completes)'],
  ['! cmd', 'run a shell command; output lands in the conversation'],
  ['# note', 'quick-add a note to memory'],
  ['"think hard"', 'ask for deeper extended thinking on a hard problem'],
]

export const SLASH_COMMANDS = [
  ['/help', 'all commands and keyboard shortcuts'],
  ['/clear', 'wipe the conversation, keep the session'],
  ['/compact', 'summarize history to reclaim context'],
  ['/context', 'visualize what is filling the context window'],
  ['/resume', 'picker of past sessions to resume'],
  ['/rewind', 'restore an earlier checkpoint of the conversation'],
  ['/model', 'switch model for this session'],
  ['/permissions', 'view / edit tool permission rules'],
  ['/agents', 'manage custom subagents'],
  ['/hooks', 'manage lifecycle hooks'],
  ['/mcp', 'manage MCP servers + OAuth'],
  ['/memory', 'edit CLAUDE.md memory files'],
  ['/init', 'generate a CLAUDE.md for this repo'],
  ['/add-dir', 'grant access to another directory'],
  ['/config', 'open settings'],
  ['/statusline', 'configure the status line'],
  ['/output-style', 'switch output style'],
  ['/vim', 'vim keybindings in the input'],
  ['/terminal-setup', 'bind Shift+Enter newline in your terminal'],
  ['/ide', 'connect to a running IDE'],
  ['/install-github-app', 'wire Claude into GitHub PRs'],
  ['/pr-comments', 'pull PR review comments into context'],
  ['/review', 'review a pull request'],
  ['/code-review ultra', 'multi-agent cloud review of the branch or a PR'],
  ['/security-review', 'security-focused review of pending changes'],
  ['/todos', 'show the current task list'],
  ['/bashes', 'list background shells'],
  ['/cost', 'token spend for this session'],
  ['/usage', 'plan usage and rate-limit status'],
  ['/export', 'copy / save the conversation'],
  ['/doctor', 'health-check the installation'],
  ['/bug', 'report a bug to Anthropic'],
  ['/login', 'switch Anthropic account'],
  ['/exit', 'leave the REPL'],
]

export const CLI_FLAGS = [
  ['claude', 'interactive session in the current directory'],
  ['claude -c', 'continue the most recent conversation here'],
  ['claude -r', 'resume: picker, or pass a session id'],
  ['claude -p "…"', 'headless: print the response and exit'],
  ['--model <m>', 'pin the model (full id beats an alias)'],
  ['--effort <l>', 'reasoning effort: low → max'],
  ['--permission-mode', 'manual · acceptEdits · plan · dontAsk · auto'],
  ['-w, --worktree', 'run in a fresh git worktree'],
  ['-n, --name <n>', 'name the session for the /resume picker'],
  ['--bg', 'launch as a background agent (claude agents)'],
  ['--cloud', 'create or attach a cloud session'],
  ['--from-pr <n>', 'resume the session linked to a PR'],
  ['--fork-session', 'resume as a copy, keep the original intact'],
  ['--add-dir <d>', 'allow tool access to more directories'],
  ['--allowedTools', 'allowlist tools (e.g. "Bash(git *) Edit")'],
  ['--mcp-config <f>', 'load MCP servers from JSON'],
  ['--output-format json', 'headless: structured result (list of messages)'],
  ['--max-budget-usd', 'hard dollar cap for a headless run'],
  ['--fallback-model', 'auto-fallback when the model is overloaded'],
  ['--safe-mode', 'boot with all customizations disabled'],
  ['--bare', 'minimal mode: no hooks / plugins / auto-memory'],
  ['claude doctor', 'health-check the install from the shell'],
  ['claude update', 'update the CLI'],
  ['claude mcp', 'manage MCP servers from the shell'],
  ['claude agents', 'manage background agents'],
]

export const CLAUDE_TABS = [
  { key: 'keys', title: 'session keys', items: [...REPL_KEYS, ...PROMPT_TRICKS] },
  { key: 'slash', title: 'slash commands', items: SLASH_COMMANDS },
  { key: 'cli', title: 'cli', items: CLI_FLAGS },
]

// flat feed for the palette's searchable shortcut section
export const PALETTE_SHORTCUTS = [...REPL_KEYS, ...PROMPT_TRICKS, ...SLASH_COMMANDS, ...CLI_FLAGS]
