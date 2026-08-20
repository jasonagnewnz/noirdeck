"""The evidence gate is what stands between a model's guess and a file appearing
in the operator's AI workspace. The centrepiece here is regression-by-history:
the ten slugs the old keyword generator actually wrote into ~/.claude are fed
back in, and every one must be rejected with a stated reason."""

from __future__ import annotations

import pytest

from noirdeck.miner.evidence import admissible, reject_reason

GOOD_EVIDENCE = (
    "Asked three times across sessions: 'deploy the wazuh agent to the new DC'. "
    "Each time the steps were: check 1514 reachability, register the agent, "
    "confirm it shows Active in agent_control -l, then verify events arrive."
)
GOOD_DESCRIPTION = "Use when rolling a Wazuh agent onto a new server and you need the registration verified end to end."


def cand(**over) -> dict:
    base = {
        "slug": "deploy-wazuh-agent",
        "evidence": GOOD_EVIDENCE,
        "draft_description": GOOD_DESCRIPTION,
        "source": "abc123.jsonl",
        "occurrences": 3,
    }
    base.update(over)
    return base


def test_a_well_evidenced_candidate_is_admissible():
    assert reject_reason(cand()) is None


# --- regression by history -------------------------------------------------

# The slugs found in ~/.claude/skills/ on 2026-08-19 carrying the
# "DRAFT (noirdeck)" marker, i.e. written by the removed keyword generator.
# Operator-identifying tokens are anonymised; each slug keeps the exact SHAPE
# that got it generated (pasted Windows path, server/compose path, username).
HISTORICAL_JUNK = [
    "autophone",
    "ddonald01",
    "username-password",
    "check-looks-correct",
    "commit-please",
    "mntcusersjdoeexamplecorpbinchitexe-force",
    "acmesaasacmeos-optacmeoscode-docker-compose",
    "startupsh",
    "going",
    "continue",
    "wewre-going-intelligent-across",
    "commit-these-changes",
    "projects-autocontract",
]


@pytest.mark.parametrize("slug", HISTORICAL_JUNK)
def test_every_slug_the_old_generator_shipped_is_rejected(slug):
    """Even handed PERFECT evidence and description, these names must not pass:
    a procedure is not named after a pasted path, a username, a credential field
    or a politeness fragment."""
    reason = reject_reason(cand(slug=slug))
    assert reason, f"{slug!r} should have been rejected"
    assert len(reason) > 10, "a rejection must say why, for the audit trail"


# --- slug shape -----------------------------------------------------------


@pytest.mark.parametrize(
    "slug,fragment",
    [
        ("", "no slug"),
        ("Deploy_Wazuh", "not a hyphenated"),
        ("deploy wazuh agent", "not a hyphenated"),
        ("wazuh", "not a hyphenated"),  # SLUG_RE requires >=2 words, so it fails there first
        ("a-b-c-d-e-f-g-h", "pasted phrase"),
        ("rotate-agentkeyonthenewdomaincontrollerbox", "run-together"),
        ("ticket-20260817", "id or date"),
        ("restart-service-tmp", "filesystem path"),
        ("fetch-api-token", "credential field"),
        ("commit-these-changes", "refers to the conversation"),
        ("projects-autocontract", "does not start with a verb"),
        ("wazuh-agent-rollout", "does not start with a verb"),
    ],
)
def test_slug_shape_rules(slug, fragment):
    reason = reject_reason(cand(slug=slug))
    assert reason and fragment in reason, f"{slug!r}: got {reason!r}"


# --- the evidential bar ---------------------------------------------------


def test_thin_evidence_is_rejected():
    assert "evidence too thin" in reject_reason(cand(evidence="they did it twice"))


def test_uncited_claim_is_rejected():
    """A claim with no transcript behind it is the exact failure mode of the old
    generator: confident output, nothing underneath."""
    assert "no source cited" in reject_reason(cand(source=""))


def test_thin_description_is_rejected():
    assert "too thin" in reject_reason(cand(draft_description="Deploys wazuh."))


def test_description_must_be_a_trigger():
    long_but_not_a_trigger = "This skill deploys the Wazuh agent onto servers and verifies the registration afterwards."
    assert "not a trigger" in reject_reason(cand(draft_description=long_but_not_a_trigger))


def test_one_off_is_not_a_procedure():
    assert "below the" in reject_reason(cand(occurrences=1))


def test_existing_skill_is_not_reproposed():
    reason = reject_reason(cand(), existing_slugs={"deploy-wazuh-agent"})
    assert "already exists" in reason


# --- batch behaviour ------------------------------------------------------


def test_admissible_splits_and_explains():
    kept, dropped = admissible([cand(), cand(slug="ddonald01"), cand(slug="wazuh")])
    assert [k["slug"] for k in kept] == ["deploy-wazuh-agent"]
    assert len(dropped) == 2
    assert all(d.reason for d in dropped)


def test_duplicates_within_a_batch_are_dropped_once():
    kept, dropped = admissible([cand(), cand()])
    assert len(kept) == 1
    assert len(dropped) == 1 and "duplicate" in dropped[0].reason


def test_non_objects_do_not_crash_the_gate():
    kept, dropped = admissible(["just a string", None, 42])
    assert kept == []
    assert len(dropped) == 3


def test_empty_input_is_the_normal_case():
    assert admissible([]) == ([], [])
    assert admissible(None) == ([], [])
