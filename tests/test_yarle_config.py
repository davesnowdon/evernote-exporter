"""Tests for yarle_config: per-invocation config dict + template generation."""
from __future__ import annotations

import json
from pathlib import Path

from evernote_exporter.yarle_config import (
    NOTE_TEMPLATE,
    build_yarle_config,
    write_template,
)


def test_build_yarle_config_sets_input_and_output_paths(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    enex_dir.mkdir()
    out_dir = tmp_path / "out"
    template = tmp_path / "tpl.tmpl"

    cfg = build_yarle_config(
        enex_source=enex_dir,
        output_dir=out_dir,
        template_file=template,
    )

    assert cfg["enexSources"] == [str(enex_dir)]
    assert cfg["outputDir"] == str(out_dir)
    assert cfg["templateFile"] == str(template)


def test_build_yarle_config_uses_obsidian_output_format(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["outputFormat"] == "OBSIDIAN_MD"


def test_build_yarle_config_enables_per_notebook_folders_and_attachments(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["isNotebookNameNeeded"] is True
    assert cfg["haveEnexLevelResources"] is True
    assert cfg["resourcesDir"] == "_attachments"


def test_build_yarle_config_uses_yaml_tags_not_inline_hashtags(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["useHashTags"] is False


def test_build_yarle_config_strips_unwanted_metadata(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    for key in (
        "skipAuthor",
        "skipLocation",
        "skipPlaceName",
        "skipReminderTime",
        "skipReminderOrder",
        "skipReminderDoneTime",
        "skipApplicationData",
        "skipContentClass",
    ):
        assert cfg[key] is True, f"expected {key} to be True"


def test_build_yarle_config_keeps_web_clips_with_aggressive_cleanup(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["skipWebClips"] is False
    assert cfg["keepOriginalHtml"] is False


def test_build_yarle_config_replaces_forbidden_chars_with_hyphen(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["replacementChar"] == "-"
    assert cfg["keepMDCharactersOfENNotes"] is False


def test_build_yarle_config_maps_space_to_hyphen_in_filenames(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["replacementCharacterMap"] == {" ": "-"}


def test_build_yarle_config_treats_monospace_as_code_block(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["monospaceIsCodeBlock"] is True


def test_build_yarle_config_drops_unresolvable_internal_links(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    assert cfg["keepEvernoteLinkIfNoNoteFound"] is False


def test_build_yarle_config_is_json_serialisable(tmp_path: Path) -> None:
    cfg = build_yarle_config(
        enex_source=tmp_path,
        output_dir=tmp_path / "out",
        template_file=tmp_path / "tpl",
    )
    # Must round-trip through JSON to be writable as Yarle config file.
    s = json.dumps(cfg)
    assert json.loads(s) == cfg


def test_note_template_uses_yaml_frontmatter() -> None:
    assert NOTE_TEMPLATE.startswith("---\n")
    # Must contain frontmatter delimiters
    assert "---" in NOTE_TEMPLATE


def test_note_template_includes_required_blocks() -> None:
    for block_name in (
        "{created-at-block}",
        "{updated-at-block}",
        "{tags-array-block}",
        "{source-url-block}",
        "{title-block}",
        "{content-block}",
    ):
        assert block_name in NOTE_TEMPLATE, f"missing block: {block_name}"


def test_note_template_uses_array_tags_for_obsidian() -> None:
    # Obsidian YAML tags must be the array form, not the prose form.
    assert "{tags-array}" in NOTE_TEMPLATE
    # The plain {tags} form would emit space-separated #tags inline — not what we want.
    # We allow it to be absent. Just ensure tags-array is the chosen form.


def test_write_template_writes_file_with_template_contents(tmp_path: Path) -> None:
    target = tmp_path / "tpl.tmpl"
    write_template(target)
    assert target.exists()
    assert target.read_text() == NOTE_TEMPLATE
