"""Tests for orchestrator: stack discovery + per-stack Yarle invocation.

Subprocess is always mocked here. Real Yarle invocation is exercised by
test_e2e.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evernote_exporter.orchestrator import (
    InvocationPlan,
    InvocationResult,
    ensure_yarle,
    plan_invocations,
    run_invocation,
    run_invocations,
)


def write_enex(path: Path) -> None:
    path.write_text(
        '<?xml version="1.0"?><en-export><note><title>x</title>'
        '<content><![CDATA[<en-note>x</en-note>]]></content>'
        '<created>20200101T000000Z</created>'
        '<updated>20200101T000000Z</updated></note></en-export>'
    )


# ---- plan_invocations ----------------------------------------------------


def test_plan_invocations_creates_one_plan_per_stack(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    output = tmp_path / "out"
    work = enex_dir / "Work"
    work.mkdir(parents=True)
    write_enex(work / "Meetings.enex")
    personal = enex_dir / "Personal"
    personal.mkdir()
    write_enex(personal / "Recipes.enex")

    plans = plan_invocations(enex_dir=enex_dir, output_root=output)

    names = sorted(p.stack_name for p in plans if p.stack_name)
    assert names == ["Personal", "Work"]
    work_plan = next(p for p in plans if p.stack_name == "Work")
    assert work_plan.enex_source == work
    assert work_plan.output_dir == output / "Work"


def test_plan_invocations_creates_root_plan_for_stackless_notebooks(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    enex_dir.mkdir()
    write_enex(enex_dir / "Inbox.enex")

    plans = plan_invocations(enex_dir=enex_dir, output_root=tmp_path / "out")

    assert len(plans) == 1
    assert plans[0].stack_name is None
    assert plans[0].enex_source == enex_dir
    assert plans[0].output_dir == tmp_path / "out"


def test_plan_invocations_includes_both_stacks_and_root(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    enex_dir.mkdir()
    write_enex(enex_dir / "Inbox.enex")
    work = enex_dir / "Work"
    work.mkdir()
    write_enex(work / "Meetings.enex")

    plans = plan_invocations(enex_dir=enex_dir, output_root=tmp_path / "out")

    assert len(plans) == 2
    has_root = any(p.stack_name is None for p in plans)
    has_work = any(p.stack_name == "Work" for p in plans)
    assert has_root and has_work


def test_plan_invocations_returns_empty_for_empty_dir(tmp_path: Path) -> None:
    enex_dir = tmp_path / "empty"
    enex_dir.mkdir()
    plans = plan_invocations(enex_dir=enex_dir, output_root=tmp_path / "out")
    assert plans == []


# ---- ensure_yarle --------------------------------------------------------


def test_ensure_yarle_returns_existing_script_without_install(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    install_dir = tmp_path / "evernote-exporter" / "yarle-6.17.0"
    script = install_dir / "node_modules" / "yarle-evernote-to-md" / "dist" / "dropTheRope.js"
    script.parent.mkdir(parents=True)
    script.write_text("// pre-existing")

    with patch("evernote_exporter.orchestrator.subprocess.run") as run:
        result = ensure_yarle("6.17.0")

    assert result == script
    run.assert_not_called()


def test_ensure_yarle_invokes_npm_install_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def fake_run(cmd, **kwargs):
        # Simulate npm install creating the expected artefact
        install_dir = tmp_path / "evernote-exporter" / "yarle-6.17.0"
        script = install_dir / "node_modules" / "yarle-evernote-to-md" / "dist" / "dropTheRope.js"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("// installed")
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        return m

    with patch("evernote_exporter.orchestrator.subprocess.run", side_effect=fake_run) as run:
        result = ensure_yarle("6.17.0")

    run.assert_called_once()
    cmd = run.call_args[0][0]
    assert cmd[0] == "npm"
    assert cmd[1] == "install"
    assert "yarle-evernote-to-md@6.17.0" in cmd
    assert result.exists()


def test_run_invocation_cleans_up_yarle_config_artefacts(tmp_path: Path) -> None:
    enex = tmp_path / "enex"
    enex.mkdir()
    write_enex(enex / "x.enex")
    plan = InvocationPlan(
        stack_name="Work",
        enex_source=enex,
        output_dir=tmp_path / "out" / "Work",
    )
    template = tmp_path / "tpl.tmpl"
    template.write_text("template")
    fake_yarle_script = tmp_path / "stub.js"
    fake_yarle_script.write_text("// stub")

    def fake_run(cmd, **kwargs):
        # Simulate Yarle leaving an artefact config in the output dir
        plan.output_dir.mkdir(parents=True, exist_ok=True)
        (plan.output_dir / "yarle_20260509_120000.config").write_text("{}")
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        return m

    with patch("evernote_exporter.orchestrator.subprocess.run", side_effect=fake_run):
        run_invocation(
            plan,
            template_file=template,
            yarle_version="6.17.0",
            yarle_script=fake_yarle_script,
        )

    leftovers = list(plan.output_dir.glob("yarle_*.config"))
    assert leftovers == []


def test_ensure_yarle_raises_on_install_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    fake = MagicMock()
    fake.returncode = 1
    fake.stdout = ""
    fake.stderr = "no such version"
    with patch("evernote_exporter.orchestrator.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError):
            ensure_yarle("99.99.99")


# ---- run_invocation -------------------------------------------------------


def test_run_invocation_writes_temp_config_and_invokes_yarle(tmp_path: Path) -> None:
    enex = tmp_path / "enex"
    enex.mkdir()
    write_enex(enex / "x.enex")
    plan = InvocationPlan(
        stack_name="Work",
        enex_source=enex,
        output_dir=tmp_path / "out" / "Work",
    )
    template = tmp_path / "tpl.tmpl"
    template.write_text("template")
    fake_yarle_script = tmp_path / "fake-yarle" / "dropTheRope.js"
    fake_yarle_script.parent.mkdir()
    fake_yarle_script.write_text("// stub")

    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = "yarle ok"
    fake.stderr = ""
    with patch("evernote_exporter.orchestrator.subprocess.run", return_value=fake) as run:
        result = run_invocation(
            plan,
            template_file=template,
            yarle_version="6.17.0",
            yarle_script=fake_yarle_script,
        )

    assert result.returncode == 0
    # Yarle was invoked via node directly (bypassing broken shebang)
    args, _ = run.call_args
    cmd = args[0]
    assert cmd[0] == "node"
    assert str(fake_yarle_script) in cmd
    assert "--configFile" in cmd
    cfg_path = Path(cmd[cmd.index("--configFile") + 1])
    payload = json.loads(cfg_path.read_text())
    assert payload["enexSources"] == [str(enex)]
    assert payload["outputDir"] == str(tmp_path / "out" / "Work")


def test_run_invocation_returns_failure_on_nonzero_exit(tmp_path: Path) -> None:
    enex = tmp_path / "enex"
    enex.mkdir()
    write_enex(enex / "x.enex")
    plan = InvocationPlan(
        stack_name=None,
        enex_source=enex,
        output_dir=tmp_path / "out",
    )
    template = tmp_path / "tpl.tmpl"
    template.write_text("template")
    fake_yarle_script = tmp_path / "stub.js"
    fake_yarle_script.write_text("// stub")

    fake = MagicMock()
    fake.returncode = 2
    fake.stdout = ""
    fake.stderr = "boom"
    with patch("evernote_exporter.orchestrator.subprocess.run", return_value=fake):
        result = run_invocation(
            plan,
            template_file=template,
            yarle_version="6.17.0",
            yarle_script=fake_yarle_script,
        )

    assert result.returncode == 2
    assert result.stderr == "boom"


# ---- run_invocations (top-level loop) -----------------------------------


def test_run_invocations_aggregates_per_plan(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    work = enex_dir / "Work"
    work.mkdir(parents=True)
    write_enex(work / "n.enex")
    write_enex(enex_dir / "Inbox.enex")
    output = tmp_path / "out"
    template = tmp_path / "tpl.tmpl"
    template.write_text("t")
    stub = tmp_path / "stub.js"
    stub.write_text("// stub")

    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = "ok"
    fake.stderr = ""
    with patch(
        "evernote_exporter.orchestrator.subprocess.run", return_value=fake
    ) as run, patch(
        "evernote_exporter.orchestrator.ensure_yarle", return_value=stub
    ):
        results = run_invocations(
            enex_dir=enex_dir,
            output_root=output,
            template_file=template,
            yarle_version="6.17.0",
        )

    assert len(results) == 2
    assert all(isinstance(r, InvocationResult) for r in results)
    assert run.call_count == 2


def test_run_invocations_continues_after_per_invocation_failure(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    a = enex_dir / "A"
    a.mkdir(parents=True)
    write_enex(a / "x.enex")
    b = enex_dir / "B"
    b.mkdir()
    write_enex(b / "y.enex")
    template = tmp_path / "tpl.tmpl"
    template.write_text("t")
    stub = tmp_path / "stub.js"
    stub.write_text("// stub")

    call_count = {"n": 0}

    def fake_run(*args, **kwargs):
        call_count["n"] += 1
        m = MagicMock()
        m.returncode = 1 if call_count["n"] == 1 else 0
        m.stdout = ""
        m.stderr = "first failed" if call_count["n"] == 1 else ""
        return m

    with patch(
        "evernote_exporter.orchestrator.subprocess.run", side_effect=fake_run
    ), patch(
        "evernote_exporter.orchestrator.ensure_yarle", return_value=stub
    ):
        results = run_invocations(
            enex_dir=enex_dir,
            output_root=tmp_path / "out",
            template_file=template,
            yarle_version="6.17.0",
        )

    assert len(results) == 2
    failures = [r for r in results if r.returncode != 0]
    successes = [r for r in results if r.returncode == 0]
    assert len(failures) == 1
    assert len(successes) == 1
