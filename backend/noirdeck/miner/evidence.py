"""Admissibility rules for mined proposals.

A proposal is a request to add a file to the operator's AI workspace, which every
future session then reads. The bar is therefore evidential, not statistical: the
model must have read real transcript material and be able to state the specific
repeated procedure, quoting it, and name a slug that describes the procedure
rather than echoing whatever string happened to be in the prompt.

This module is deliberately a set of REJECTION rules with named reasons, so a
rejected candidate is auditable ("why did nothing get proposed?") instead of
silently absent. Every rule here exists because the previous keyword generator
produced a specific piece of junk that reached ~/.claude — the test suite feeds
those exact ten historical slugs back in and requires each to be rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A slug names a procedure: two or more lowercase words, hyphen separated.
# Single words are rejected because every junk slug was one ("going", "continue",
# "ddonald01", "startupsh") and because a one-word skill name never describes a
# procedure well enough to trigger correctly.
SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$")

MIN_SLUG_WORDS = 2
MAX_SLUG_WORDS = 5
MIN_EVIDENCE_CHARS = 80
MIN_DESCRIPTION_CHARS = 40
MIN_OCCURRENCES = 3

# Shapes that are never a procedure name, however often they recur.
_PATH_LIKE = re.compile(r"(^|-)(mnt|usr|var|tmp|home|opt|etc|dev)(-|$)|\.(exe|sh|py|js|md|json|ya?ml)$|-docker-compose")
_CREDENTIAL_LIKE = re.compile(r"(^|-)(user|username|password|passwd|secret|token|apikey|api-key|creds?)(-|$)")
_GENERIC_VERB_ONLY = re.compile(
    r"^(please|thanks|ok|okay|yes|no|go|going|continue|continues|next|now|do|doing|done|fix|fixed|help)(-.*)?$"
)
# Bare politeness/instruction fragments: "commit-please", "check-looks-correct".
_FRAGMENT = re.compile(r"(^|-)(please|thanks|correct|looks|wewre|were|weve|ive|im)(-|$)")

# Words that point at the conversation rather than at a general procedure.
# "commit-these-changes" reads like a valid name but "these" refers to whatever
# was on screen at the time, so it can never describe a reusable procedure.
_DEICTIC = re.compile(r"(^|-)(this|that|these|those|it|its|them|here|there|my|our|your|the)(-|$)")

# A procedure name begins with what it DOES. This is naming hygiene applied to
# model output, not a detector: whether the procedure exists is decided by the
# evidence fields, never by matching words. It is the rule that rejects
# "projects-autocontract" — two nouns lifted from a path, describing no action.
_VERBS = frozenset(
    """add apply archive audit back backup build bump capture check clean clear close collect
    commit compare configure connect convert copy create deploy diagnose disable discover drain
    dump enable enrich export extract fetch find fix flag generate grant harden import init
    initialise initialize inspect install invoice issue list load log migrate mine monitor move
    onboard open patch pause ping plan prepare probe promote provision publish pull purge push
    query quote reboot rebuild recheck reconcile record refresh register reload remove rename
    renew repair replace report reprice reset resolve restart restore resume retire review
    revoke roll rollout rotate route run scaffold scan schedule seed send set setup ship sign
    start stop submit sweep sync tag test tidy trace track triage tune uninstall unlock update
    upgrade upload validate verify walk watch wire write""".split()
)


@dataclass
class Rejected:
    slug: str
    reason: str


def _words(slug: str) -> list[str]:
    return [w for w in slug.split("-") if w]


def reject_reason(cand: dict, existing_slugs: set[str] | None = None) -> str | None:
    """None means admissible. Anything else is the human-readable reason it is not."""
    slug = str(cand.get("slug") or "").strip().lower()
    evidence = str(cand.get("evidence") or "").strip()
    description = str(cand.get("draft_description") or "").strip()
    occurrences = cand.get("occurrences")

    if not slug:
        return "no slug"
    if not SLUG_RE.match(slug):
        return f"slug is not a hyphenated procedure name: {slug!r}"
    words = _words(slug)
    if len(words) < MIN_SLUG_WORDS:
        return f"slug is a single token, not a procedure: {slug!r}"
    if len(words) > MAX_SLUG_WORDS:
        return f"slug is a pasted phrase, not a name ({len(words)} words): {slug!r}"
    if any(len(w) > 24 for w in words):
        return f"slug contains a run-together token (pasted text, not a name): {slug!r}"
    if _PATH_LIKE.search(slug):
        return f"slug looks like a filesystem path or artefact name: {slug!r}"
    if _CREDENTIAL_LIKE.search(slug):
        return f"slug looks like a credential field, not a procedure: {slug!r}"
    if _GENERIC_VERB_ONLY.match(slug):
        return f"slug is a bare instruction fragment: {slug!r}"
    if _FRAGMENT.search(slug):
        return f"slug is conversational filler, not a procedure: {slug!r}"
    if _DEICTIC.search(slug):
        return f"slug refers to the conversation ('this'/'these'/'my'), so it names no reusable procedure: {slug!r}"
    if re.search(r"\d{4,}", slug):
        return f"slug carries an id or date rather than naming a procedure: {slug!r}"
    if words[0] not in _VERBS:
        return f"slug does not start with a verb, so it names no action: {slug!r}"

    # The evidential bar: the model must show its work.
    if len(evidence) < MIN_EVIDENCE_CHARS:
        return f"evidence too thin to judge ({len(evidence)} chars, need {MIN_EVIDENCE_CHARS})"
    if not str(cand.get("source") or "").strip():
        return "no source cited — a claim with no transcript behind it is not evidence"
    if len(description) < MIN_DESCRIPTION_CHARS:
        return f"draft description too thin ({len(description)} chars, need {MIN_DESCRIPTION_CHARS})"
    if not re.search(r"\b(use when|when you|when the|after |before )\b", description, re.I):
        return "draft description is not a trigger ('Use when ...'), so the skill could never fire correctly"
    if isinstance(occurrences, int) and occurrences < MIN_OCCURRENCES:
        return f"seen {occurrences}x, below the {MIN_OCCURRENCES}x bar for a recurring procedure"
    if existing_slugs and slug in existing_slugs:
        return f"a skill named {slug!r} already exists"
    return None


def admissible(candidates: list[dict], existing_slugs: set[str] | None = None) -> tuple[list[dict], list[Rejected]]:
    """Split model output into what may become proposals and what may not."""
    kept: list[dict] = []
    dropped: list[Rejected] = []
    seen: set[str] = set()
    for cand in candidates or []:
        if not isinstance(cand, dict):
            dropped.append(Rejected(slug=str(cand)[:60], reason="candidate was not an object"))
            continue
        slug = str(cand.get("slug") or "").strip().lower()
        if slug and slug in seen:
            dropped.append(Rejected(slug=slug, reason="duplicate within the same batch"))
            continue
        reason = reject_reason(cand, existing_slugs)
        if reason:
            dropped.append(Rejected(slug=slug or "(none)", reason=reason))
            continue
        seen.add(slug)
        cand["slug"] = slug
        kept.append(cand)
    return kept, dropped
