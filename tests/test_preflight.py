"""Tests for preflight checks.

The functions return PreflightResult.ok or .fail(message). Tests cover each
check independently. The runner-level "run all checks" is a thin loop and
is exercised in test_orchestrator / test_cli.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from evernote_exporter.preflight import (
    PreflightResult,
    check_enex_dir_has_files,
    check_node_available,
    check_obsidian_vault,
    check_output_dir_safe,
    check_vault_directory,
    check_writable,
    check_yarle_available,
)


def test_preflight_result_ok_is_truthy() -> None:
    r = PreflightResult.ok("node 22.16.0")
    assert bool(r) is True
    assert r.passed is True
    assert r.message == "node 22.16.0"


def test_preflight_result_fail_is_falsy_and_carries_message() -> None:
    r = PreflightResult.fail("not found")
    assert bool(r) is False
    assert r.passed is False
    assert r.message == "not found"


# ---- check_node_available -------------------------------------------------


def test_check_node_available_passes_when_both_node_and_npx_on_path() -> None:
    with patch("evernote_exporter.preflight.shutil.which") as which:
        which.side_effect = lambda name: f"/usr/bin/{name}" if name in ("node", "npx") else None
        result = check_node_available()
    assert result.passed


def test_check_node_available_fails_when_node_missing() -> None:
    with patch("evernote_exporter.preflight.shutil.which") as which:
        which.side_effect = lambda name: "/usr/bin/npx" if name == "npx" else None
        result = check_node_available()
    assert not result.passed
    assert "node" in result.message.lower()
    assert "apt install" in result.message


def test_check_node_available_fails_when_npx_missing() -> None:
    with patch("evernote_exporter.preflight.shutil.which") as which:
        which.side_effect = lambda name: "/usr/bin/node" if name == "node" else None
        result = check_node_available()
    assert not result.passed
    assert "npx" in result.message


# ---- check_yarle_available -----------------------------------------------


def test_check_yarle_available_passes_when_npm_view_returns_zero() -> None:
    with patch("evernote_exporter.preflight.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "6.17.0\n"
        run.return_value.stderr = ""
        result = check_yarle_available("6.17.0")
    assert result.passed
    assert "6.17.0" in result.message


def test_check_yarle_available_fails_when_version_not_on_registry() -> None:
    with patch("evernote_exporter.preflight.subprocess.run") as run:
        run.return_value.returncode = 1
        run.return_value.stdout = ""
        run.return_value.stderr = "no matching version"
        result = check_yarle_available("99.99.99")
    assert not result.passed
    assert "registry" in result.message.lower() or "yarle" in result.message.lower()


def test_check_yarle_available_fails_when_npm_missing() -> None:
    with patch("evernote_exporter.preflight.subprocess.run", side_effect=FileNotFoundError):
        result = check_yarle_available("6.17.0")
    assert not result.passed


# ---- check_enex_dir_has_files --------------------------------------------


def test_check_enex_dir_finds_top_level_files(tmp_path: Path) -> None:
    (tmp_path / "a.enex").write_text("<x/>")
    result = check_enex_dir_has_files(tmp_path)
    assert result.passed


def test_check_enex_dir_finds_files_in_subdirs(tmp_path: Path) -> None:
    sub = tmp_path / "Stack"
    sub.mkdir()
    (sub / "a.enex").write_text("<x/>")
    result = check_enex_dir_has_files(tmp_path)
    assert result.passed


def test_check_enex_dir_fails_when_no_enex_files(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("nothing")
    result = check_enex_dir_has_files(tmp_path)
    assert not result.passed
    assert "evernote-backup" in result.message


def test_check_enex_dir_fails_when_dir_missing(tmp_path: Path) -> None:
    result = check_enex_dir_has_files(tmp_path / "nope")
    assert not result.passed


# ---- check_vault_directory -----------------------------------------------


def test_check_vault_directory_passes_for_existing_dir(tmp_path: Path) -> None:
    result = check_vault_directory(tmp_path)
    assert result.passed


def test_check_vault_directory_fails_for_missing_dir(tmp_path: Path) -> None:
    result = check_vault_directory(tmp_path / "missing")
    assert not result.passed


def test_check_vault_directory_fails_for_file(tmp_path: Path) -> None:
    f = tmp_path / "file"
    f.write_text("x")
    result = check_vault_directory(f)
    assert not result.passed


# ---- check_obsidian_vault ------------------------------------------------


def test_check_obsidian_vault_passes_when_dot_obsidian_present(tmp_path: Path) -> None:
    (tmp_path / ".obsidian").mkdir()
    result = check_obsidian_vault(tmp_path)
    assert result.passed


def test_check_obsidian_vault_fails_when_dot_obsidian_missing(tmp_path: Path) -> None:
    result = check_obsidian_vault(tmp_path)
    assert not result.passed
    assert "--no-vault-check" in result.message


# ---- check_output_dir_safe -----------------------------------------------


def test_check_output_dir_safe_passes_when_dir_does_not_exist(tmp_path: Path) -> None:
    result = check_output_dir_safe(tmp_path / "nope")
    assert result.passed


def test_check_output_dir_safe_passes_when_marker_present(tmp_path: Path) -> None:
    target = tmp_path / "Evernote"
    target.mkdir()
    (target / ".evernote-export-marker").write_text("{}")
    result = check_output_dir_safe(target)
    assert result.passed


def test_check_output_dir_safe_fails_when_dir_exists_without_marker(tmp_path: Path) -> None:
    target = tmp_path / "Notes"
    target.mkdir()
    (target / "file.md").write_text("x")
    result = check_output_dir_safe(target)
    assert not result.passed
    assert "marker" in result.message.lower()


# ---- check_writable ------------------------------------------------------


def test_check_writable_passes_when_parent_writable(tmp_path: Path) -> None:
    target = tmp_path / "Evernote"
    result = check_writable(target)
    assert result.passed


def test_check_writable_fails_when_parent_does_not_exist(tmp_path: Path) -> None:
    target = tmp_path / "nope" / "Evernote"
    result = check_writable(target)
    assert not result.passed


def test_check_writable_fails_when_parent_not_writable(tmp_path: Path) -> None:
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o555)
    try:
        result = check_writable(parent / "child")
        assert not result.passed
    finally:
        parent.chmod(0o755)
