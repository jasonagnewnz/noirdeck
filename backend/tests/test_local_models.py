"""Local model setup. Two things carry real risk and are pinned hardest:

1. Nothing downloads or installs without confirm=True. This code fetches an
   executable over the network and runs it; a page load must never start that.
2. A model is never recommended that the machine cannot actually run, and
   "we could not measure the machine" is never reported as "it fits".
"""

from __future__ import annotations

import tarfile

import pytest

from noirdeck import local_models as lm


def cap(usable, ram=16.0, gpu=None, vram=None, basis="test"):
    return lm.Capacity(ram_gb=ram, gpu_name=gpu, gpu_vram_gb=vram, usable_gb=usable, basis=basis)


# --- capacity gating ------------------------------------------------------


def test_only_models_that_fit_are_recommended():
    r = lm.recommend("code", cap(8.0))
    assert r["start_with"]["needs_gb"] <= 8.0
    assert all(e["needs_gb"] <= 8.0 for e in r["fits"])
    assert all(e["needs_gb"] > 8.0 for e in r["out_of_reach"])


def test_a_tiny_machine_gets_tiny_models_only():
    r = lm.recommend("code", cap(4.0))
    assert {e["tag"] for e in r["fits"]} <= {"qwen2.5-coder:1.5b", "llama3.2:3b", "nomic-embed-text"}
    assert r["start_with"]["tag"] in {"qwen2.5-coder:1.5b", "llama3.2:3b"}


def test_a_big_machine_is_offered_the_biggest():
    r = lm.recommend("code", cap(40.0))
    assert r["out_of_reach"] == []
    assert r["start_with"]["tag"] == "qwen2.5-coder:32b", "locally, bigger is better right up to the memory line"


def test_unmeasurable_capacity_never_claims_a_fit():
    """⛔ 'Could not measure' must not be reported as 'fits'. A model sized past the
    machine's memory swaps, and swapping is indistinguishable from broken."""
    r = lm.recommend("code", cap(None, ram=None))
    assert r["fits"] == []
    assert r["start_with"] is None
    assert all("Cannot tell" in e["note"] for e in r["out_of_reach"])


def test_capacity_leaves_headroom_and_says_so():
    c = lm.capacity()
    if c.ram_gb and not c.gpu_vram_gb:
        assert c.usable_gb < c.ram_gb, "must not size a model to the machine's total RAM"
        assert "keeping" in c.basis, "the basis has to be legible, not a bare number"


def test_gpu_vram_wins_over_system_ram_when_present(monkeypatch):
    monkeypatch.setattr(lm, "_ram_gb", lambda: 64.0)
    monkeypatch.setattr(lm, "_gpu", lambda: ("Test GPU", 12.0))
    c = lm.capacity()
    assert c.usable_gb == 12.0 and "graphics memory" in c.basis


# --- work-kind ordering ---------------------------------------------------


def test_work_kind_inferred_from_actual_usage():
    assert lm.infer_work_kind([["/review", 9]], [["api-service", 4]]) == "code"
    assert lm.infer_work_kind([["/note", 2]], [["recipes", 1]]) == "mixed"


def test_ordering_prefers_the_matching_purpose_but_never_breaks_the_fit_rule():
    code = lm.recommend("code", cap(10.0))
    mixed = lm.recommend("mixed", cap(10.0))
    assert "code" in code["start_with"]["kinds"]
    assert "general" in mixed["start_with"]["kinds"]
    # a wrong guess about the work may reorder, but must never offer a misfit
    for r in (code, mixed):
        assert all(e["needs_gb"] <= 10.0 for e in r["fits"])


def test_already_pulled_is_flagged_per_tag_not_per_family():
    """…:7b and …:14b are different downloads. Keying by family let one silently
    mask the other."""
    r = lm.recommend("code", cap(40.0), already=["qwen2.5-coder:7b"])
    by_tag = {e["tag"]: e for e in r["fits"]}
    assert by_tag["qwen2.5-coder:7b"]["already_pulled"] is True
    assert by_tag["qwen2.5-coder:14b"]["already_pulled"] is False


def test_bare_name_matches_latest_the_way_ollama_does():
    r = lm.recommend("code", cap(40.0), already=["nomic-embed-text:latest"])
    by_tag = {e["tag"]: e for e in r["fits"]}
    assert by_tag["nomic-embed-text"]["already_pulled"] is True


# --- nothing happens without confirmation ---------------------------------


def test_install_requires_confirmation(monkeypatch):
    monkeypatch.setattr(lm, "_binary", lambda: None)
    out = lm.install(confirm=False)
    assert out["performed"] is False and "confirm" in out["reason"]


def test_install_is_a_no_op_when_already_present(monkeypatch):
    monkeypatch.setattr(lm, "_binary", lambda: "/home/u/.local/bin/ollama")
    out = lm.install(confirm=True)
    assert out["performed"] is False and out["reason"] == "already installed"


def test_pull_requires_confirmation_and_states_the_cost():
    out = lm.pull("qwen2.5-coder:7b", confirm=False)
    assert out["started"] is False
    assert out["download_gb"] > 0 and out["needs_gb"] > 0, "the size must be stated before a multi-GB download"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "../../etc/passwd",
        "model; rm -rf /",
        "model && curl evil",
        "$(whoami)",
        "a" * 200,
        "model:tag:extra",
    ],
)
def test_pull_rejects_anything_that_is_not_a_plain_tag(bad):
    """The tag reaches a subprocess. 'It came from our own UI' is not a reason to
    trust it."""
    with pytest.raises(lm.LocalModelError):
        lm.pull(bad, confirm=True)


def test_pull_refuses_a_tag_outside_the_catalogue():
    with pytest.raises(lm.LocalModelError, match="not in the recommended catalogue"):
        lm.pull("some-random-model:70b", confirm=True)


def test_serve_refuses_when_not_installed(monkeypatch):
    monkeypatch.setattr(lm, "_binary", lambda: None)
    with pytest.raises(lm.LocalModelError, match="not installed"):
        lm.serve()


# --- the install itself ---------------------------------------------------


def test_install_plan_needs_no_root_and_explains_why():
    plan = lm.install_plan()
    assert plan["needs_root"] is False
    assert ".local" in plan["target"]
    assert "admin" in plan["why_not_the_official_script"]


def test_install_rejects_an_archive_with_unsafe_paths(monkeypatch, tmp_path):
    """An archive is untrusted input even from a trusted host, and this unpacks
    into the user's home folder."""
    evil = tmp_path / "evil.tgz"
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="../../.bashrc")

    monkeypatch.setattr(lm, "_binary", lambda: None)
    monkeypatch.setattr(lm, "INSTALL_ROOT", tmp_path / "target")

    def fake_urlopen(url, timeout=0):
        return open(evil, "rb")

    monkeypatch.setattr(lm.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(lm.LocalModelError, match="unsafe path"):
        lm.install(confirm=True)
    assert not (tmp_path / ".bashrc").exists()


def test_install_reports_an_unsupported_architecture(monkeypatch):
    monkeypatch.setattr(lm, "TARBALLS", {})
    with pytest.raises(lm.LocalModelError, match="no official Ollama build"):
        lm.install(confirm=True)


# --- one instruction at a time --------------------------------------------


def test_next_step_walks_the_user_through_in_order():
    base_caps = {"capacity": lm.asdict(cap(16.0))}
    recs = lm.recommend("code", cap(16.0))

    not_installed = {"installed": False, "server_running": False, "models": [], **base_caps}
    assert lm._next_step(not_installed, recs)["action"] == "install"

    installed_not_running = {"installed": True, "server_running": False, "models": [], **base_caps}
    assert lm._next_step(installed_not_running, recs)["action"] == "serve"

    running_no_models = {"installed": True, "server_running": True, "models": [], **base_caps}
    step = lm._next_step(running_no_models, recs)
    assert step["action"] == "pull" and step["tag"]

    ready = {"installed": True, "server_running": True, "models": [{"name": "x"}], **base_caps}
    assert lm._next_step(ready, recs)["action"] == "ready"


def test_next_step_is_honest_when_nothing_fits():
    recs = lm.recommend("code", cap(1.0))
    running_no_models = {"installed": True, "server_running": True, "models": [], "capacity": lm.asdict(cap(1.0))}
    step = lm._next_step(running_no_models, recs)
    assert step["action"] == "pull"
    assert "fits" in step["detail"] or "No model" in step["detail"]


def test_models_empty_is_distinguishable_from_server_down(monkeypatch):
    """⛔ [] must never mean both 'nothing pulled' and 'could not ask'."""
    monkeypatch.setattr(lm, "_binary", lambda: "/x/ollama")
    monkeypatch.setattr(lm, "_version", lambda e: "0.0.0")
    monkeypatch.setattr(lm, "server_running", lambda: False)
    st = lm.state()
    assert st["models"] == [] and st["models_known"] is False

    monkeypatch.setattr(lm, "server_running", lambda: True)
    monkeypatch.setattr(lm, "installed_models", lambda: [])
    st2 = lm.state()
    assert st2["models"] == [] and st2["models_known"] is True
