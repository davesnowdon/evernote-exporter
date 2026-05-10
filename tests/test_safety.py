"""Tests for safety module: marker file management."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evernote_exporter.safety import (
    MARKER_FILENAME,
    MarkerInfo,
    OutputState,
    inspect_output_dir,
    read_marker,
    write_marker,
)


def test_write_marker_creates_json_with_required_fields(tmp_path: Path) -> None:
    info = MarkerInfo(
        tool="evernote-exporter",
        tool_version="0.1.0",
        yarle_version="7.4.2",
        created_at="2026-05-06T14:30:22Z",
        source_dir="/some/source",
    )

    write_marker(tmp_path, info)

    marker = tmp_path / MARKER_FILENAME
    assert marker.exists()
    payload = json.loads(marker.read_text())
    assert payload == {
        "tool": "evernote-exporter",
        "tool_version": "0.1.0",
        "yarle_version": "7.4.2",
        "created_at": "2026-05-06T14:30:22Z",
        "source_dir": "/some/source",
    }


def test_read_marker_roundtrips_what_write_marker_wrote(tmp_path: Path) -> None:
    info = MarkerInfo(
        tool="evernote-exporter",
        tool_version="0.1.0",
        yarle_version="7.4.2",
        created_at="2026-05-06T14:30:22Z",
        source_dir="/some/source",
    )
    write_marker(tmp_path, info)

    loaded = read_marker(tmp_path)

    assert loaded == info


def test_read_marker_returns_none_when_marker_missing(tmp_path: Path) -> None:
    assert read_marker(tmp_path) is None


def test_read_marker_returns_none_when_marker_unparseable(tmp_path: Path) -> None:
    (tmp_path / MARKER_FILENAME).write_text("this is not json")

    assert read_marker(tmp_path) is None


def test_inspect_output_dir_says_does_not_exist_for_missing_path(tmp_path: Path) -> None:
    target = tmp_path / "nope"

    state = inspect_output_dir(target)

    assert state == OutputState.DOES_NOT_EXIST


def test_inspect_output_dir_says_owned_when_marker_present(tmp_path: Path) -> None:
    target = tmp_path / "owned"
    target.mkdir()
    info = MarkerInfo(
        tool="evernote-exporter",
        tool_version="0.1.0",
        yarle_version="7.4.2",
        created_at="2026-05-06T14:30:22Z",
        source_dir="/x",
    )
    write_marker(target, info)
    # also some content
    (target / "Note.md").write_text("body")

    state = inspect_output_dir(target)

    assert state == OutputState.OWNED


def test_inspect_output_dir_says_foreign_when_dir_exists_without_marker(
    tmp_path: Path,
) -> None:
    target = tmp_path / "foreign"
    target.mkdir()
    (target / "user-file.md").write_text("user data")

    state = inspect_output_dir(target)

    assert state == OutputState.FOREIGN


def test_inspect_output_dir_says_foreign_when_dir_exists_empty(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()

    # An empty directory still lacks a marker — refuse it. The user can rmdir it.
    state = inspect_output_dir(target)

    assert state == OutputState.FOREIGN


def test_inspect_output_dir_raises_if_path_is_a_file(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x")

    with pytest.raises(NotADirectoryError):
        inspect_output_dir(target)
