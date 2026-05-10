"""Tests for enex_parser: counts notes and resources from ENEX files."""
from pathlib import Path
from textwrap import dedent

import pytest

from evernote_exporter.enex_parser import (
    EnexCounts,
    count_enex,
    count_enex_dir,
    discover_stacks,
)


def write_enex(path: Path, n_notes: int, n_resources_per_note: int = 0) -> None:
    notes_xml = ""
    for i in range(n_notes):
        resources = ""
        for j in range(n_resources_per_note):
            resources += dedent(
                f"""\
                <resource>
                  <data encoding="base64">aGVsbG8=</data>
                  <mime>image/png</mime>
                  <resource-attributes>
                    <file-name>img{j}.png</file-name>
                  </resource-attributes>
                </resource>
                """
            )
        notes_xml += dedent(
            f"""\
            <note>
              <title>Note {i}</title>
              <content><![CDATA[<en-note>body {i}</en-note>]]></content>
              <created>20180405T102300Z</created>
              <updated>20241130T191200Z</updated>
              {resources}
            </note>
            """
        )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export4.dtd">\n'
        f'<en-export application="Evernote" version="10.0">\n{notes_xml}</en-export>\n',
        encoding="utf-8",
    )


def test_count_enex_returns_zeros_for_empty_export(tmp_path: Path) -> None:
    enex = tmp_path / "empty.enex"
    write_enex(enex, n_notes=0)

    counts = count_enex(enex)

    assert counts == EnexCounts(notes=0, resources=0, path=enex)


def test_count_enex_counts_notes_and_resources(tmp_path: Path) -> None:
    enex = tmp_path / "sample.enex"
    write_enex(enex, n_notes=3, n_resources_per_note=2)

    counts = count_enex(enex)

    assert counts.notes == 3
    assert counts.resources == 6
    assert counts.path == enex


def test_count_enex_handles_notes_without_resources(tmp_path: Path) -> None:
    enex = tmp_path / "notes-only.enex"
    write_enex(enex, n_notes=5, n_resources_per_note=0)

    counts = count_enex(enex)

    assert counts.notes == 5
    assert counts.resources == 0


def test_count_enex_raises_for_malformed_xml(tmp_path: Path) -> None:
    enex = tmp_path / "broken.enex"
    enex.write_text("<en-export><note><title>x</title></note", encoding="utf-8")

    with pytest.raises(Exception):  # noqa: BLE001 - any XML error is fine
        count_enex(enex)


def test_count_enex_dir_aggregates_per_file(tmp_path: Path) -> None:
    write_enex(tmp_path / "a.enex", n_notes=2, n_resources_per_note=1)
    write_enex(tmp_path / "b.enex", n_notes=4, n_resources_per_note=0)
    # subdirectory ignored at this level (we look at one dir)
    sub = tmp_path / "sub"
    sub.mkdir()
    write_enex(sub / "c.enex", n_notes=99)

    counts = count_enex_dir(tmp_path)

    assert {c.path.name for c in counts} == {"a.enex", "b.enex"}
    by_name = {c.path.name: c for c in counts}
    assert by_name["a.enex"].notes == 2
    assert by_name["a.enex"].resources == 2  # 2 notes × 1 resource each
    assert by_name["b.enex"].notes == 4
    assert by_name["b.enex"].resources == 0


def test_discover_stacks_returns_subdirs_and_root_files(tmp_path: Path) -> None:
    # stack with notebooks
    work = tmp_path / "Work"
    work.mkdir()
    write_enex(work / "Meetings.enex", n_notes=1)
    write_enex(work / "Projects.enex", n_notes=1)
    # another stack
    personal = tmp_path / "Personal"
    personal.mkdir()
    write_enex(personal / "Recipes.enex", n_notes=1)
    # root-level notebook (no stack)
    write_enex(tmp_path / "Inbox.enex", n_notes=1)
    # empty subdirectory should be skipped
    (tmp_path / "Empty").mkdir()
    # non-enex files ignored
    (tmp_path / "README.txt").write_text("ignore me")

    stacks = discover_stacks(tmp_path)

    stack_names = sorted(s.name for s in stacks if s.name is not None)
    assert stack_names == ["Personal", "Work"]
    root = next((s for s in stacks if s.name is None), None)
    assert root is not None
    assert {f.name for f in root.enex_files} == {"Inbox.enex"}
    work_stack = next(s for s in stacks if s.name == "Work")
    assert {f.name for f in work_stack.enex_files} == {"Meetings.enex", "Projects.enex"}


def test_discover_stacks_omits_root_when_no_root_enex(tmp_path: Path) -> None:
    work = tmp_path / "Work"
    work.mkdir()
    write_enex(work / "Notes.enex", n_notes=1)

    stacks = discover_stacks(tmp_path)

    assert all(s.name is not None for s in stacks)
    assert [s.name for s in stacks] == ["Work"]


def test_discover_stacks_returns_empty_for_empty_dir(tmp_path: Path) -> None:
    assert discover_stacks(tmp_path) == []
