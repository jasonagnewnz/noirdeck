import json

import pytest

from app.builds import PHASES, BuildRunner
from app.db import connect
from app.guided import (INTAKE_QUESTIONS, acceptance_criteria, compose_brief,
                        read_plain_plan, validate_answers)
from tests.test_builds import _wait_status, settings  # noqa: F401 — fixture reuse

ANSWERS = {
    "purpose": "A booking page for my salon",
    "users": "my customers on their phones",
    "auth": "none",
    "data": "names, emails and time slots",
    "never": "show one customer's booking to another",
    "success": ["I can make a booking from my phone", "I get an email when someone books"],
    "polish": "solid",
    "extra": "",
}

STUB_DONE = ["bash", "-c",
             'printf \'## The plan in plain English\\nA one-page booking site.\\nNo sign-in.\\n\' > MASTER_PLAN.md; '
             'echo \'VERDICT: {"status":"done","summary":"phase ok"}\'; true; #']


def test_intake_validation_and_brief():
    assert validate_answers(ANSWERS) == []
    assert "purpose" in validate_answers({**ANSWERS, "purpose": "  "})
    assert "success" in validate_answers({**ANSWERS, "success": ["", " "]})
    brief = compose_brief(ANSWERS)
    assert "booking page" in brief and "NEVER" in brief
    assert "plain English" in brief  # plan phase contract
    crit = acceptance_criteria(ANSWERS)
    assert [c["kind"] for c in crit].count("operator") == 2
    assert any(c["id"] == "std-tests" for c in crit)
    # every intake question id is unique
    ids = [q["id"] for q in INTAKE_QUESTIONS]
    assert len(ids) == len(set(ids))


def test_read_plain_plan_extracts_section(tmp_path):
    (tmp_path / "MASTER_PLAN.md").write_text(
        "# plan\n\n## The plan in plain English\nline one\nline two\n\n## Tech detail\nstack")
    assert read_plain_plan(tmp_path) == "line one\nline two"
    assert read_plain_plan(tmp_path / "nowhere") == ""


def test_gated_build_parks_at_plan_and_approve_finishes(settings):  # noqa: F811
    runner = BuildRunner(settings, claude_argv_base=STUB_DONE)
    build_id = runner.start("salon", compose_brief(ANSWERS), gated=True,
                            intake=ANSWERS, acceptance=acceptance_criteria(ANSWERS))
    row = _wait_status(settings.db_path, build_id, {"awaiting_plan"})
    assert "plain English" not in (row["plan_summary"] or "")  # extracted section, not header
    assert "booking site" in row["plan_summary"]

    runner.decide_plan(build_id, "approve")
    row = _wait_status(settings.db_path, build_id, {"done", "attention"})
    log = json.loads(row["log"])
    assert [e["phase"] for e in log] == [p[0] for p in PHASES]  # plan ran exactly once
    evidence = json.loads(row["evidence"])
    assert "qa_overall" in evidence and len(evidence["phases"]) == len(PHASES)


def test_gated_build_revise_reruns_plan(settings):  # noqa: F811
    runner = BuildRunner(settings, claude_argv_base=STUB_DONE)
    build_id = runner.start("salon2", compose_brief(ANSWERS), gated=True)
    _wait_status(settings.db_path, build_id, {"awaiting_plan"})

    runner.decide_plan(build_id, "revise", "make it pink")
    row = _wait_status(settings.db_path, build_id, {"awaiting_plan"})
    conn = connect(settings.db_path)
    prompt = conn.execute("SELECT prompt FROM builds WHERE id=?", (build_id,)).fetchone()["prompt"]
    conn.close()
    assert "make it pink" in prompt
    log = json.loads(row["log"])
    assert [e["phase"] for e in log] == ["plan", "plan"]  # re-planned, still parked

    runner.decide_plan(build_id, "approve")
    row = _wait_status(settings.db_path, build_id, {"done", "attention"})
    phases_run = [e["phase"] for e in json.loads(row["log"])]
    # two plan entries then each later phase exactly once — no phase skipped
    assert phases_run == ["plan", "plan"] + [p[0] for p in PHASES[1:]]


def test_plan_decision_guards(settings):  # noqa: F811
    runner = BuildRunner(settings, claude_argv_base=STUB_DONE)
    build_id = runner.start("ungated", "An ordinary ungated build brief long enough to pass.")
    _wait_status(settings.db_path, build_id, {"done", "attention"})
    with pytest.raises(ValueError):
        runner.decide_plan(build_id, "approve")  # not awaiting_plan
    build2 = runner.start("gated2", "x" * 50, gated=True)
    _wait_status(settings.db_path, build2, {"awaiting_plan"})
    with pytest.raises(ValueError):
        runner.decide_plan(build2, "revise", "")  # feedback required
    with pytest.raises(ValueError):
        runner.decide_plan(build2, "explode")


# --- recipe cards -------------------------------------------------------------

def test_every_recipe_validates_and_matches_question_ids():
    from app.guided import INTAKE_QUESTIONS, RECIPES, compose_brief, validate_answers
    qids = {q["id"] for q in INTAKE_QUESTIONS}
    choice_opts = {q["id"]: {v for v, _ in q["options"]}
                   for q in INTAKE_QUESTIONS if q["type"] == "choice"}
    assert len(RECIPES) >= 4
    assert len({r["id"] for r in RECIPES}) == len(RECIPES)
    for r in RECIPES:
        assert r["title"] and r["blurb"]
        assert set(r["answers"]) <= qids, f"{r['id']} references unknown question ids"
        assert validate_answers(r["answers"]) == [], f"{r['id']} would not submit cleanly"
        for qid, opts in choice_opts.items():
            assert r["answers"][qid] in opts, f"{r['id']}.{qid} picks a nonexistent option"
        # the compiled brief must accept every recipe unchanged
        assert "PURPOSE:" in compose_brief(r["answers"])
