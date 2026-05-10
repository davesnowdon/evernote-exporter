"""Tests for cli module: argument parsing, prompt, top-level orchestration.

Yarle subprocess is mocked here. Real Yarle invocation is in test_e2e.
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evernote_exporter import cli


def _make_vault(path: Path) -> Path:
    path.mkdir()
    (path / ".obsidian").mkdir()
    return path


def _make_enex_dir(path: Path) -> Path:
    path.mkdir()
    (path / "Inbox.enex").write_text(
        '<?xml version="1.0"?><en-export>'
        '<note><title>x</title>'
        '<content><![CDATA[<en-note>x</en-note>]]></content>'
        '<created>20200101T000000Z</created><updated>20200101T000000Z</updated></note>'
        '</en-export>'
    )
    return path


def test_parse_args_requires_enex_dir_and_vault_and_root_folder() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_parse_args_accepts_required_flags(tmp_path: Path) -> None:
    args = cli.parse_args(
        [
            "--enex-dir",
            str(tmp_path / "enex"),
            "--vault",
            str(tmp_path / "vault"),
            "--root-folder",
            "Evernote",
        ]
    )
    assert args.enex_dir == tmp_path / "enex"
    assert args.vault == tmp_path / "vault"
    assert args.root_folder == "Evernote"
    assert args.yes is False
    assert args.dry_run is False
    assert args.no_vault_check is False


def test_parse_args_accepts_optional_flags(tmp_path: Path) -> None:
    args = cli.parse_args(
        [
            "--enex-dir",
            "x",
            "--vault",
            "y",
            "--root-folder",
            "z",
            "--yes",
            "--dry-run",
            "--verbose",
            "--no-vault-check",
            "--yarle-version",
            "1.2.3",
        ]
    )
    assert args.yes is True
    assert args.dry_run is True
    assert args.verbose is True
    assert args.no_vault_check is True
    assert args.yarle_version == "1.2.3"


def test_main_exits_1_when_preflight_fails(tmp_path: Path, capsys) -> None:
    # No .obsidian/ directory -> obsidian vault check fails
    vault = tmp_path / "vault"
    vault.mkdir()
    enex_dir = _make_enex_dir(tmp_path / "enex")

    with patch("evernote_exporter.cli.check_node_available") as cna, patch(
        "evernote_exporter.cli.check_yarle_available"
    ) as cya:
        cna.return_value = MagicMock(passed=True, message="ok")
        cya.return_value = MagicMock(passed=True, message="ok")
        rc = cli.main(
            [
                "--enex-dir",
                str(enex_dir),
                "--vault",
                str(vault),
                "--root-folder",
                "Evernote",
                "--yes",
            ]
        )
    assert rc == 1


def test_main_exits_0_on_dry_run(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path / "vault")
    enex_dir = _make_enex_dir(tmp_path / "enex")

    with patch("evernote_exporter.cli.check_node_available") as cna, patch(
        "evernote_exporter.cli.check_yarle_available"
    ) as cya:
        cna.return_value = MagicMock(passed=True, message="ok")
        cya.return_value = MagicMock(passed=True, message="ok")
        rc = cli.main(
            [
                "--enex-dir",
                str(enex_dir),
                "--vault",
                str(vault),
                "--root-folder",
                "Evernote",
                "--dry-run",
            ]
        )
    assert rc == 0
    # Dry run does NOT create the output directory
    assert not (vault / "Evernote").exists()


def test_main_exits_1_when_user_declines_prompt(tmp_path: Path, monkeypatch) -> None:
    vault = _make_vault(tmp_path / "vault")
    enex_dir = _make_enex_dir(tmp_path / "enex")

    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))

    with patch("evernote_exporter.cli.check_node_available") as cna, patch(
        "evernote_exporter.cli.check_yarle_available"
    ) as cya:
        cna.return_value = MagicMock(passed=True, message="ok")
        cya.return_value = MagicMock(passed=True, message="ok")
        rc = cli.main(
            [
                "--enex-dir",
                str(enex_dir),
                "--vault",
                str(vault),
                "--root-folder",
                "Evernote",
            ]
        )
    assert rc == 1
    assert not (vault / "Evernote").exists()


def test_main_runs_full_pipeline_with_yes_flag(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path / "vault")
    enex_dir = _make_enex_dir(tmp_path / "enex")
    stub_yarle = tmp_path / "stub-yarle.js"
    stub_yarle.write_text("// stub")

    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = ""
    fake.stderr = ""

    with patch("evernote_exporter.cli.check_node_available") as cna, patch(
        "evernote_exporter.cli.check_yarle_available"
    ) as cya, patch(
        "evernote_exporter.orchestrator.subprocess.run", return_value=fake
    ) as run, patch(
        "evernote_exporter.orchestrator.ensure_yarle", return_value=stub_yarle
    ):
        cna.return_value = MagicMock(passed=True, message="ok")
        cya.return_value = MagicMock(passed=True, message="ok")
        rc = cli.main(
            [
                "--enex-dir",
                str(enex_dir),
                "--vault",
                str(vault),
                "--root-folder",
                "Evernote",
                "--yes",
            ]
        )
    # Yarle was invoked (mocked)
    assert run.call_count >= 1
    # Reports and marker were written
    assert (vault / "Evernote" / "migration-report.txt").exists()
    assert (vault / "Evernote" / "migration-report.json").exists()
    assert (vault / "Evernote" / ".evernote-export-marker").exists()
    # rc 3 because Yarle is mocked and produces no output, so notes_out=0 mismatches notes_in=1
    assert rc == 3


def test_main_refuses_existing_dir_without_marker(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path / "vault")
    enex_dir = _make_enex_dir(tmp_path / "enex")
    # Pre-existing root-folder content WITHOUT marker
    (vault / "Evernote").mkdir()
    (vault / "Evernote" / "user-file.md").write_text("user data")

    with patch("evernote_exporter.cli.check_node_available") as cna, patch(
        "evernote_exporter.cli.check_yarle_available"
    ) as cya:
        cna.return_value = MagicMock(passed=True, message="ok")
        cya.return_value = MagicMock(passed=True, message="ok")
        rc = cli.main(
            [
                "--enex-dir",
                str(enex_dir),
                "--vault",
                str(vault),
                "--root-folder",
                "Evernote",
                "--yes",
            ]
        )
    assert rc == 1
    # User data preserved
    assert (vault / "Evernote" / "user-file.md").read_text() == "user data"
