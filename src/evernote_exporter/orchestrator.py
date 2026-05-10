"""Stack discovery + per-stack Yarle subprocess invocation.

Yarle does not recurse subdirectories of `enexSources`. To handle the
Stack → Notebook hierarchy produced by evernote-backup, we invoke Yarle
once per stack subdirectory, plus once for any root-level .enex files
(notebooks that aren't in a stack).

Yarle wraps its output in an extra `notes/` subdirectory (so notebooks
land at <outputDir>/notes/<notebook>/). We flatten that away after each
invocation so the final layout matches DESIGN.md.

Yarle's bin script has a multi-arg shebang
`#!/usr/bin/env node --max-old-space-size=1024` which Linux does not parse
reliably — `npx`/`npm exec` hang on it. We install Yarle ourselves into
~/.cache/evernote-exporter/yarle-<version>/ and invoke `node <script.js>`
directly, bypassing the broken shebang.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .enex_parser import discover_stacks
from .yarle_config import build_yarle_config


def _cache_root() -> Path:
    """Location for the locally-installed Yarle copy."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "evernote-exporter"


def ensure_yarle(yarle_version: str) -> Path:
    """Install Yarle into our cache dir if needed. Return path to dropTheRope.js."""
    install_dir = _cache_root() / f"yarle-{yarle_version}"
    script = install_dir / "node_modules" / "yarle-evernote-to-md" / "dist" / "dropTheRope.js"
    if script.exists():
        return script
    install_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "npm", "install",
            "--prefix", str(install_dir),
            "--no-audit", "--no-fund", "--no-save",
            f"yarle-evernote-to-md@{yarle_version}",
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not script.exists():
        raise RuntimeError(
            f"Failed to install yarle-evernote-to-md@{yarle_version}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return script


@dataclass(frozen=True)
class InvocationPlan:
    stack_name: str | None  # None = root-level (stackless) notebooks
    enex_source: Path
    output_dir: Path


@dataclass(frozen=True)
class InvocationResult:
    plan: InvocationPlan
    returncode: int
    stdout: str
    stderr: str


def plan_invocations(*, enex_dir: Path, output_root: Path) -> list[InvocationPlan]:
    """Discover stacks and create one InvocationPlan per Yarle invocation."""
    plans: list[InvocationPlan] = []
    for group in discover_stacks(enex_dir):
        if group.name is None:
            output_dir = output_root
        else:
            output_dir = output_root / group.name
        plans.append(
            InvocationPlan(
                stack_name=group.name,
                enex_source=group.directory,
                output_dir=output_dir,
            )
        )
    return plans


def run_invocation(
    plan: InvocationPlan,
    *,
    template_file: Path,
    yarle_version: str,
    yarle_script: Path | None = None,
) -> InvocationResult:
    """Run Yarle once for a single plan. Returns InvocationResult.

    `yarle_script` overrides the auto-installed Yarle path (used by tests).
    """
    plan.output_dir.mkdir(parents=True, exist_ok=True)

    if yarle_script is None:
        yarle_script = ensure_yarle(yarle_version)

    config = build_yarle_config(
        enex_source=plan.enex_source,
        output_dir=plan.output_dir,
        template_file=template_file,
    )

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(config, tmp)
        config_path = Path(tmp.name)

    # Bypass Yarle's broken multi-arg shebang by invoking node directly.
    cmd = [
        "node",
        f"--max-old-space-size=1024",
        str(yarle_script),
        "--configFile",
        str(config_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode == 0:
        _flatten_notes_subdir(plan.output_dir)
        _cleanup_yarle_artefacts(plan.output_dir)

    return InvocationResult(
        plan=plan,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _flatten_notes_subdir(output_dir: Path) -> None:
    """Yarle writes to <output_dir>/notes/<notebook>/. Hoist contents up.

    No-op if the `notes/` wrapper isn't present (e.g., subprocess mocked).
    """
    notes_dir = output_dir / "notes"
    if not notes_dir.is_dir():
        return
    for entry in notes_dir.iterdir():
        target = output_dir / entry.name
        if target.exists():
            # Should not happen — output_dir was just created. Defensive.
            continue
        shutil.move(str(entry), str(target))
    notes_dir.rmdir()


def _cleanup_yarle_artefacts(output_dir: Path) -> None:
    """Remove Yarle's auto-saved `yarle_<timestamp>.config` files.

    Yarle writes a copy of its own config into the output directory after each
    run. We don't want these in the user's vault.
    """
    if not output_dir.is_dir():
        return
    for entry in output_dir.glob("yarle_*.config"):
        try:
            entry.unlink()
        except OSError:
            pass


def run_invocations(
    *,
    enex_dir: Path,
    output_root: Path,
    template_file: Path,
    yarle_version: str,
) -> list[InvocationResult]:
    """Plan + run all invocations. Continues on per-invocation failure.

    Yarle is installed once per top-level run (not per invocation), so the
    install cost is paid once even with many stacks.
    """
    plans = plan_invocations(enex_dir=enex_dir, output_root=output_root)
    if not plans:
        return []
    yarle_script = ensure_yarle(yarle_version)
    return [
        run_invocation(
            p,
            template_file=template_file,
            yarle_version=yarle_version,
            yarle_script=yarle_script,
        )
        for p in plans
    ]
