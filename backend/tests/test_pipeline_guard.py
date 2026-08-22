"""The pipeline guard is the only thing standing between an unattended
headless session and the operator's governance files. These tests pin BOTH
boundaries, and specifically pin the 2026-08-19 hole: the hook used to inspect
Bash only, so Write/Edit sailed straight through under acceptEdits.

HERMETIC ON PURPOSE. The first version of this file assumed the author's own
machine: it used `~/.claude` as a subprocess cwd and hardcoded the author's
home path: and it passed locally and failed in CI, where HOME is /home/runner and
no `.claude` directory exists. A guard test that depends on the developer's home
layout tests the machine, not the guard. Everything below drives the guard's
CLAUDE_CONFIG_DIR at a tmp_path instead, so the protected tree exists, is
writable, and is the same on every machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from noirdeck.guard import GUARD_SCRIPT


@pytest.fixture
def workspace(tmp_path):
    """A stand-in Claude config dir, and the env that points the guard at it."""
    root = tmp_path / "claude-config"
    for sub in ("skills/operate", "agents", "rules", "projects/-demo/memory", "commands"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("governance\n")
    (root / "settings.json").write_text("{}\n")
    (root / "skills/operate/SKILL.md").write_text("skill\n")
    (root / "projects/-demo/memory/MEMORY.md").write_text("index\n")
    return root


def run_guard(tool: str, tool_input: dict, config_dir: Path, cwd: Path | None = None):
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(config_dir))
    return subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


def assert_denied(res) -> None:
    assert res.returncode == 2, f"expected DENY, got {res.returncode}: {res.stdout}{res.stderr}"
    assert "DENIED" in res.stderr or "denying" in res.stderr


def assert_allowed(res) -> None:
    assert res.returncode == 0, f"expected ALLOW, got {res.returncode}: {res.stderr}"


# --- boundary 2: the knowledge tree is read-only ---------------------------

PROTECTED_RELATIVE = [
    "CLAUDE.md",
    "settings.json",
    "agents/breach-investigator.md",  # need not exist
    "rules/schema-and-data.md",
    "skills/operate/SKILL.md",
    "projects/-demo/memory/MEMORY.md",
    "projects/-demo/memory/a-new-file.md",  # need not exist yet
]


@pytest.mark.parametrize("rel", PROTECTED_RELATIVE)
@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_write_tools_cannot_touch_the_knowledge_tree(tool, rel, workspace):
    """THE regression that mattered: these calls were never even shown to the
    hook, and acceptEdits auto-approved them."""
    assert_denied(run_guard(tool, {"file_path": str(workspace / rel), "content": "x"}, workspace))


@pytest.mark.parametrize("rel", PROTECTED_RELATIVE)
def test_notebook_edit_cannot_touch_the_knowledge_tree(rel, workspace):
    assert_denied(run_guard("NotebookEdit", {"notebook_path": str(workspace / rel), "new_source": "x"}, workspace))


def test_the_real_default_home_tree_is_protected_too():
    """Independent of CLAUDE_CONFIG_DIR, ~/.claude is always a protected root:
    otherwise unsetting one env var would disarm the whole guard. Path only: the
    directory need not exist for this to hold."""
    target = Path.home() / ".claude" / "CLAUDE.md"
    env_elsewhere = Path.home() / "definitely-not-the-config-dir"
    assert_denied(run_guard("Write", {"file_path": str(target), "content": "x"}, env_elsewhere))


def test_relative_and_traversal_paths_are_resolved_not_string_matched(workspace):
    # a relative path from inside the tree resolves into it
    assert_denied(run_guard("Write", {"file_path": "./CLAUDE.md", "content": "x"}, workspace, cwd=workspace))
    # traversal back into the tree from a sibling directory
    sibling = workspace.parent / "elsewhere"
    sibling.mkdir(exist_ok=True)
    back_in = f"../{workspace.name}/CLAUDE.md"
    assert_denied(run_guard("Write", {"file_path": back_in, "content": "x"}, workspace, cwd=sibling))


def test_tilde_expansion_is_honoured():
    assert_denied(run_guard("Write", {"file_path": "~/.claude/CLAUDE.md", "content": "x"}, Path.home() / ".claude"))


def test_project_files_are_still_writable(workspace, tmp_path):
    """The pipelines exist to edit code. Guarding the knowledge tree must not turn
    them into read-only sessions."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert_allowed(run_guard("Write", {"file_path": str(repo / "app.py"), "content": "x"}, workspace))
    assert_allowed(
        run_guard("Edit", {"file_path": str(repo / "notes.md"), "old_string": "a", "new_string": "b"}, workspace)
    )
    # a directory whose name merely CONTAINS the protected one must not match:
    # string matching on ".claude" would wrongly deny this
    lookalike = tmp_path / f"{workspace.name}-notes"
    lookalike.mkdir()
    assert_allowed(run_guard("Write", {"file_path": str(lookalike / "README.md"), "content": "x"}, workspace))


def test_a_sibling_with_a_shared_prefix_is_not_protected(workspace, tmp_path):
    """`parents` containment, not `startswith`: /a/claude-config-old must not be
    treated as inside /a/claude-config."""
    decoy = tmp_path / f"{workspace.name}-old"
    decoy.mkdir()
    assert_allowed(run_guard("Write", {"file_path": str(decoy / "CLAUDE.md"), "content": "x"}, workspace))


@pytest.mark.parametrize(
    "template",
    [
        "sed -i 's/a/b/' {root}/CLAUDE.md",
        "sed -Ei 's/a/b/' {root}/CLAUDE.md",
        "cat > {root}/CLAUDE.md",
        "echo hi >> {root}/projects/-demo/memory/MEMORY.md",
        'echo hi > "{root}/settings.json"',
        "cp /tmp/x {root}/skills/operate/SKILL.md",
        "mv /tmp/x {root}/agents/foo.md",
        "rm {root}/projects/-demo/memory/MEMORY.md",
        "tee {root}/CLAUDE.md < /tmp/x",
        "python3 -c \"open('{root}/CLAUDE.md','w').write('x')\"",
        "cat <<'EOF' > {root}/CLAUDE.md",
        "chmod 777 {root}/settings.json",
        "mkdir -p {root}/skills/newthing",
        "git apply /tmp/p.patch --directory={root}",
    ],
)
def test_bash_writes_into_the_knowledge_tree_are_denied(template, workspace):
    assert_denied(run_guard("Bash", {"command": template.format(root=workspace)}, workspace))


def test_home_shorthand_forms_are_denied():
    """`~` and `$HOME` reach the same tree and must be caught the same way."""
    cfg = Path.home() / ".claude"
    for cmd in [
        "sed -i 's/a/b/' ~/.claude/CLAUDE.md",
        'echo hi > "$HOME/.claude/settings.json"',
        "cp /tmp/x ~/.claude/skills/operate/SKILL.md",
    ]:
        assert_denied(run_guard("Bash", {"command": cmd}, cfg))


@pytest.mark.parametrize(
    "template",
    [
        "cat {root}/CLAUDE.md",
        "grep -rn wazuh {root}/projects/-demo/memory/",
        "ls -la {root}/skills/",
        "head -50 {root}/settings.json",
        "find {root} -name '*.md'",
        "wc -l {root}/projects/-demo/memory/MEMORY.md",
    ],
)
def test_reading_the_knowledge_tree_is_allowed(template, workspace):
    """Read + inject its own stuff: reading is the whole point of the miner."""
    assert_allowed(run_guard("Bash", {"command": template.format(root=workspace)}, workspace))


def test_write_verb_without_a_protected_path_is_allowed(workspace):
    assert_allowed(run_guard("Bash", {"command": "sed -i 's/a/b/' backend/noirdeck/main.py"}, workspace))
    assert_allowed(run_guard("Bash", {"command": "echo hi > /tmp/out.txt"}, workspace))


# --- boundary 1: code-ready (existing behaviour, still enforced) -----------


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "gh pr create --fill",
        "npm publish",
        "docker push repo/img",
        "terraform apply",
        "ssh someone@host 'ls'",
        "systemctl restart noirdeck",
        "pkill -f uvicorn",
    ],
)
def test_outward_actions_still_denied(command, workspace):
    assert_denied(run_guard("Bash", {"command": command}, workspace))


def test_local_git_still_allowed(workspace):
    assert_allowed(run_guard("Bash", {"command": "git commit -am 'wip'"}, workspace))
    assert_allowed(run_guard("Bash", {"command": "git status --short"}, workspace))


# --- fail-closed ----------------------------------------------------------


def test_unparseable_input_is_denied_loudly():
    res = subprocess.run([sys.executable, str(GUARD_SCRIPT)], input="not json", capture_output=True, text=True)
    assert res.returncode == 2
    assert "fail-closed" in res.stderr


def test_read_only_tools_are_allowed(workspace):
    assert_allowed(run_guard("Read", {"file_path": str(workspace / "CLAUDE.md")}, workspace))
    assert_allowed(run_guard("Grep", {"pattern": "x", "path": str(workspace)}, workspace))
