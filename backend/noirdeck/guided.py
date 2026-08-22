"""Guided Build: the professional-in-the-loop inversion for non-technical
operators. The tool asks the professional questions (intake), compiles them
into a build brief, parks the pipeline after planning for plain-English
approval, and ends with acceptance criteria + a deterministic evidence pack.

Everything here is zero-egress: the interview, brief compilation, criteria and
evidence assembly are pure functions; only the build phases themselves run LLM
sessions (through the existing guarded pipeline)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Single page, plain English (no jargon), each answer strengthens the brief.
INTAKE_QUESTIONS = [
    {
        "id": "purpose",
        "label": "What are you building?",
        "help": "One or two sentences, like you'd tell a friend.",
        "type": "text",
        "required": True,
        "placeholder": "e.g. A booking page where my clients pick a time and I get an email",
    },
    {
        "id": "users",
        "label": "Who will use it?",
        "help": "Just you? Your customers? Your team?",
        "type": "text",
        "required": True,
        "placeholder": "e.g. my customers, on their phones",
    },
    {
        "id": "auth",
        "label": "Should people sign in?",
        "type": "choice",
        "required": True,
        "options": [
            ["none", "No: anyone can use it"],
            ["simple", "A single shared password is enough"],
            ["accounts", "Yes: individual accounts"],
        ],
    },
    {
        "id": "data",
        "label": "What information does it keep?",
        "help": "Names? Bookings? Files? Say if any of it is sensitive.",
        "type": "text",
        "required": True,
        "placeholder": "e.g. names, emails and chosen time slots",
    },
    {
        "id": "never",
        "label": "What must it never do?",
        "help": "The hard lines. These become non-negotiable rules for the builder.",
        "type": "text",
        "required": False,
        "placeholder": "e.g. never show one customer's details to another",
    },
    {
        "id": "success",
        "label": "What will you check to call it working?",
        "help": "Up to five concrete things. These become your acceptance checklist.",
        "type": "list",
        "required": True,
        "max_items": 5,
        "placeholder": "e.g. I can make a booking from my phone",
    },
    {
        "id": "polish",
        "label": "How polished should this first version be?",
        "type": "choice",
        "required": True,
        "options": [
            ["prototype", "Rough is fine: I want to try the idea"],
            ["solid", "Solid: I'll use it for real"],
            ["production", "Polished: other people will rely on it"],
        ],
    },
    {
        "id": "extra",
        "label": "Anything else the builder should know?",
        "type": "text",
        "required": False,
        "placeholder": "colours you like, tools you already use, examples to copy…",
    },
]

# Recipe cards: complete, editable answer sets for the commonest asks. Answers
# reference INTAKE_QUESTIONS ids so the form and brief compiler can never drift
# (tests enforce every recipe validates cleanly). The operator still names the
# build and can change any answer before submitting.
RECIPES = [
    {
        "id": "booking-page",
        "title": "A booking page",
        "blurb": "Customers pick a time, you get an email.",
        "answers": {
            "purpose": "A booking page where my customers pick an available time slot and I get an email for each booking",
            "users": "my customers, mostly on their phones",
            "auth": "none",
            "data": "names, email addresses and chosen time slots",
            "never": "never show one customer's details to another; never double-book a slot",
            "success": [
                "I can make a booking from my phone",
                "I get an email when someone books",
                "A taken slot can't be booked twice",
            ],
            "polish": "solid",
            "extra": "",
        },
    },
    {
        "id": "small-website",
        "title": "A small website",
        "blurb": "A few pages and a contact form for a business or club.",
        "answers": {
            "purpose": "A small website for my business: a home page, an about page, what we offer, and a contact form",
            "users": "anyone who finds us online, on phones and computers",
            "auth": "none",
            "data": "just the messages people send through the contact form",
            "never": "never look broken on a phone",
            "success": ["Every page reads well on my phone", "The contact form reaches me", "It looks professional"],
            "polish": "solid",
            "extra": "",
        },
    },
    {
        "id": "team-tracker",
        "title": "A team tracker",
        "blurb": "Track jobs, tasks or stock with your team.",
        "answers": {
            "purpose": "A simple tracker where my team logs items (jobs, tasks or stock), updates their status, and sees what's outstanding",
            "users": "me and my team, a handful of people",
            "auth": "simple",
            "data": "item names, statuses, who last updated them, and dates",
            "never": "never lose an item someone entered",
            "success": [
                "I can add an item and change its status",
                "The team sees the same up-to-date list",
                "I can see what's still outstanding at a glance",
            ],
            "polish": "solid",
            "extra": "",
        },
    },
    {
        "id": "quote-calculator",
        "title": "A quote calculator",
        "blurb": "Customers get an instant price estimate.",
        "answers": {
            "purpose": "A calculator where customers pick options and see an instant price estimate, with a button to send the quote to me",
            "users": "potential customers who don't want to phone just for a price",
            "auth": "none",
            "data": "the options chosen and, if they send the quote, their contact details",
            "never": "never show a wrong price; if unsure, say 'contact us'",
            "success": [
                "The price matches my price list for three test picks",
                "A sent quote reaches me with the customer's details",
            ],
            "polish": "solid",
            "extra": "",
        },
    },
    {
        "id": "signup-sheet",
        "title": "A signup sheet",
        "blurb": "People sign up for an event, you get the list.",
        "answers": {
            "purpose": "A signup page for an event where people enter their name and details, and I can view and download the full list",
            "users": "people I invite, plus me as the organiser",
            "auth": "none",
            "data": "names, contact details, and any dietary or plus-one notes",
            "never": "never show the signup list to anyone but me",
            "success": [
                "Someone can sign up from a shared link",
                "I can see everyone who signed up",
                "I can download the list",
            ],
            "polish": "prototype",
            "extra": "",
        },
    },
    {
        "id": "private-dashboard",
        "title": "A private dashboard",
        "blurb": "Your numbers from a spreadsheet, on one page.",
        "answers": {
            "purpose": "A private dashboard that reads a spreadsheet (CSV) I upload and shows my key numbers and simple charts on one page",
            "users": "just me, maybe one business partner",
            "auth": "simple",
            "data": "the uploaded spreadsheet contents: business figures, possibly sensitive",
            "never": "never be reachable without the password",
            "success": [
                "I can upload my spreadsheet and see the numbers",
                "The totals match what the spreadsheet says",
                "Nobody without the password can see anything",
            ],
            "polish": "solid",
            "extra": "",
        },
    },
]

_POLISH = {
    "prototype": "This is a first prototype: favour simplicity and speed over completeness.",
    "solid": "This will be used for real: correct, tested, and pleasant, without gold-plating.",
    "production": "Other people will rely on this: production-quality code, tests, error "
    "handling, and operational docs throughout.",
}

_AUTH = {
    "none": "No sign-in. Do not build authentication.",
    "simple": "Protect the app with a single shared password (fail closed; no accounts).",
    "accounts": "Individual user accounts with secure password handling.",
}


def validate_answers(answers: dict) -> list[str]:
    """Missing required answers, by question id (empty list = valid)."""
    missing = []
    for q in INTAKE_QUESTIONS:
        if not q.get("required"):
            continue
        v = answers.get(q["id"])
        if (
            v is None
            or (isinstance(v, str) and not v.strip())
            or (isinstance(v, list) and not [x for x in v if str(x).strip()])
        ):
            missing.append(q["id"])
    return missing


def compose_brief(answers: dict) -> str:
    """Compile plain-English answers into a professional build brief."""
    success = [s.strip() for s in (answers.get("success") or []) if str(s).strip()]
    lines = [
        "BUILD BRIEF (compiled from a guided intake interview: the operator is "
        "non-technical; every later report about this build must be plain English).",
        "",
        f"PURPOSE: {answers['purpose'].strip()}",
        f"USERS: {answers['users'].strip()}",
        f"SIGN-IN: {_AUTH[answers['auth']]}",
        f"DATA IT KEEPS: {answers['data'].strip()}",
    ]
    if (answers.get("never") or "").strip():
        lines.append(f"HARD RULES: the software must NEVER: {answers['never'].strip()}")
    lines += [
        f"QUALITY BAR: {_POLISH[answers['polish']]}",
        "",
        "ACCEPTANCE CRITERIA the operator will personally check:",
        *[f"  {i + 1}. {s}" for i, s in enumerate(success)],
    ]
    if (answers.get("extra") or "").strip():
        lines.append(f"\nOPERATOR NOTES: {answers['extra'].strip()}")
    lines.append(
        "\nIn the PLAN phase, MASTER_PLAN.md must open with a section titled "
        "'## The plan in plain English': 8-15 short lines a non-technical reader "
        "can approve: what will exist, what it will look like, what is out of "
        "scope, and any assumption you made about an unanswered question."
    )
    return "\n".join(lines)


def acceptance_criteria(answers: dict) -> list[dict]:
    """Operator's own checks + the standard professional ones."""
    out = [
        {"id": f"user-{i + 1}", "text": s.strip(), "kind": "operator"}
        for i, s in enumerate(answers.get("success") or [])
        if str(s).strip()
    ]
    out += [
        {"id": "std-tests", "text": "The automated test suite passes", "kind": "standard"},
        {"id": "std-gates", "text": "No blocking quality-gate failures", "kind": "standard"},
        {"id": "std-run", "text": "The software was run end-to-end at least once", "kind": "standard"},
    ]
    return out


def read_plain_plan(repo: Path) -> str:
    """The plain-English section of MASTER_PLAN.md the plan phase was told to write
    (falls back to the file head so the gate never shows an empty plan)."""
    f = repo / "MASTER_PLAN.md"
    try:
        text = f.read_text(errors="replace")
    except OSError:
        return ""
    m = re.search(r"##\s*The plan in plain English\s*\n(.*?)(?:\n##\s|\Z)", text, re.S | re.I)
    return (m.group(1).strip() if m else text.strip())[:4000]


def evidence_pack(repo: Path, log: list[dict]) -> dict:
    """Deterministic proof-of-work: commits, change size, per-phase account,
    final gate state. No LLM involvement: this is the part the operator can trust
    precisely because no model wrote it."""

    def _git(*args: str) -> str:
        try:
            p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
            return p.stdout.strip() if p.returncode == 0 else ""
        except OSError:
            return ""

    commits = [c for c in _git("log", "--format=%h %s", "-30").splitlines() if c]
    changed = _git("diff", "--shortstat", f"{commits[-1].split()[0]}~1" if commits else "HEAD", "HEAD")
    tests_line = ""
    for entry in reversed(log):
        m = re.search(r"(\d+ (?:passed|tests? passed)[^.;]*)", entry.get("summary", ""))
        if m:
            tests_line = m.group(1)
            break
    from .qa import evaluate_project

    qa = evaluate_project(repo)
    return {
        "commits": commits,
        "commit_count": len(commits),
        "change_size": changed,
        "tests": tests_line or "see the test phase summary",
        "qa_overall": qa["overall"],
        "qa_gates": [{"id": g["id"], "verdict": g["verdict"], "evidence": g["evidence"][:200]} for g in qa["gates"]],
        "phases": [
            {"phase": e.get("phase"), "status": e.get("status"), "seconds": e.get("seconds"), "tokens": e.get("tokens")}
            for e in log
        ],
    }
