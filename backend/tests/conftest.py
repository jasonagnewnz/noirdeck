import json
import os
import sys

# fixtures build a '-home-user' namespace tree; pin the derived namespace so
# the suite is hermetic on any machine/home directory
os.environ["NOIRDECK_PRIMARY_NAMESPACE"] = "-home-user"
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_claude(root: Path) -> Path:
    """Fixture tree mirroring the real ~/.claude layout the readers contract on."""
    claude = root / "claude"
    (claude / "skills" / "deploy-wazuh").mkdir(parents=True)
    (claude / "skills" / "deploy-wazuh" / "SKILL.md").write_text(
        "---\nname: deploy-wazuh\ndescription: Deploy wazuh agents fleet-wide.\nmodel: opus\n---\n\n# body\n"
    )
    (claude / "agents").mkdir()
    (claude / "agents" / "backup-operator.md").write_text(
        "---\nname: backup-operator\ndescription: Designs, runs and verifies backups across the fleet with restore testing discipline.\ntools: Read, Bash\n---\nbody"
    )

    mem = claude / "projects" / "-home-user" / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# index\n")
    for i, name in enumerate(
        ["fb_wazuh_rules_one", "fb_wazuh_rules_two", "fb_wazuh_agent_three", "wazuh_health_four", "misc_note"]
    ):
        (mem / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: note {i}\nmetadata:\n  type: feedback\n---\nbody {i}\n"
        )

    ns = claude / "projects" / "-home-user-projects-demo"
    ns.mkdir(parents=True)
    records = [
        {"type": "user", "message": {"content": "Build the invoice sync feature"}},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Done. Next steps: shall I wire the webhook?"}]},
        },
    ]
    (ns / "aaaa-session.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")

    hist_lines = []
    base_ts = 1754900000000
    for i in range(4):
        hist_lines.append(
            {
                "display": "summarise unresolved sentinelone threats for the weekly report",
                "timestamp": base_ts + i * 1000,
                "project": "/home/user/projects/demo",
            }
        )
    hist_lines.append({"display": "/operate ", "timestamp": base_ts, "project": "/home/user"})
    hist_lines.append({"display": "deploy wazuh agents fleet-wide", "timestamp": base_ts, "project": "/home/user"})
    (claude / "history.jsonl").write_text("\n".join(json.dumps(r) for r in hist_lines) + "\n")
    return claude


@pytest.fixture
def claude_dir(tmp_path):
    return make_claude(tmp_path)
