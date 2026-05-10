"""Preflight checks. Each is independent and returns PreflightResult.

Run before any destructive operation. Failures produce actionable messages.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .safety import MARKER_FILENAME


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    message: str

    def __bool__(self) -> bool:
        return self.passed

    @classmethod
    def ok(cls, message: str) -> "PreflightResult":
        return cls(passed=True, message=message)

    @classmethod
    def fail(cls, message: str) -> "PreflightResult":
        return cls(passed=False, message=message)


def check_node_available() -> PreflightResult:
    if shutil.which("node") is None:
        return PreflightResult.fail(
            "node not found on PATH. Install Node.js: sudo apt install nodejs npm"
        )
    if shutil.which("npx") is None:
        return PreflightResult.fail(
            "npx not found on PATH. Install Node.js: sudo apt install nodejs npm"
        )
    return PreflightResult.ok("node and npx available")


def check_yarle_available(yarle_version: str) -> PreflightResult:
    """Verify the pinned Yarle version exists on npm.

    Yarle has no `--version` flag — its only documented invocation is via
    `--configFile`. So we use `npm view` to confirm the registry has the
    version we plan to use. The first real invocation will download it.
    """
    try:
        result = subprocess.run(
            ["npm", "view", f"yarle-evernote-to-md@{yarle_version}", "version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return PreflightResult.fail(f"could not query npm registry: {exc}")

    if result.returncode != 0:
        return PreflightResult.fail(
            f"yarle-evernote-to-md@{yarle_version} not found on npm registry: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    detected = (result.stdout or "").strip() or yarle_version
    return PreflightResult.ok(f"yarle {detected} available")


def check_enex_dir_has_files(enex_dir: Path) -> PreflightResult:
    if not enex_dir.exists() or not enex_dir.is_dir():
        return PreflightResult.fail(
            f"--enex-dir {enex_dir} does not exist. "
            "Did you run evernote-backup export?"
        )
    has_any = any(enex_dir.rglob("*.enex"))
    if not has_any:
        return PreflightResult.fail(
            f"No .enex files found in {enex_dir}. "
            "Did you run evernote-backup export?"
        )
    return PreflightResult.ok(f"enex-dir contains .enex files")


def check_vault_directory(vault: Path) -> PreflightResult:
    if not vault.exists():
        return PreflightResult.fail(f"--vault {vault} does not exist")
    if not vault.is_dir():
        return PreflightResult.fail(f"--vault {vault} is not a directory")
    return PreflightResult.ok(f"vault directory exists")


def check_obsidian_vault(vault: Path) -> PreflightResult:
    if not (vault / ".obsidian").is_dir():
        return PreflightResult.fail(
            f"{vault} doesn't look like an Obsidian vault (no .obsidian/). "
            "Use --no-vault-check to override."
        )
    return PreflightResult.ok(".obsidian/ found")


def check_output_dir_safe(output_dir: Path) -> PreflightResult:
    """Output dir must either not exist OR contain our marker file."""
    if not output_dir.exists():
        return PreflightResult.ok("output dir does not yet exist")
    if (output_dir / MARKER_FILENAME).exists():
        return PreflightResult.ok("output dir has our marker file")
    return PreflightResult.fail(
        f"{output_dir} exists but lacks marker file ({MARKER_FILENAME}). "
        "Aborting to protect your data. Remove or rename it manually."
    )


def check_writable(output_dir: Path) -> PreflightResult:
    parent = output_dir.parent
    if not parent.exists():
        return PreflightResult.fail(f"parent of {output_dir} does not exist: {parent}")
    if not os.access(parent, os.W_OK):
        return PreflightResult.fail(f"parent directory not writable: {parent}")
    return PreflightResult.ok("output location writable")
