"""End-to-end tests against real Yarle.

Requires Node.js and network access (first run downloads Yarle via npx).
Default-on per design §13. Skipped only if `node`/`npx` not on PATH.

Each test runs Yarle on one fixture and asserts the produced output has
the expected shape (folder structure, frontmatter, attachments).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from evernote_exporter import YARLE_PINNED_VERSION
from evernote_exporter.orchestrator import InvocationPlan, run_invocation
from evernote_exporter.yarle_config import write_template

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _node_available() -> bool:
    return shutil.which("node") is not None and shutil.which("npx") is not None


pytestmark = pytest.mark.skipif(not _node_available(), reason="node/npx not on PATH")


@pytest.fixture(scope="session")
def template_file(tmp_path_factory) -> Path:
    """Write the note template once per test session."""
    path = tmp_path_factory.mktemp("yarle-template") / "template.tmpl"
    write_template(path)
    return path


def _list_md_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.md") if p.is_file())


def _read_frontmatter(md_path: Path) -> dict[str, str]:
    """Tiny YAML frontmatter parser — only handles flat key: value entries."""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def _convert(fixture_name: str, tmp_path: Path, template: Path) -> Path:
    """Convert a single fixture and return the output directory."""
    src = tmp_path / "in"
    src.mkdir()
    shutil.copy(FIXTURES_DIR / fixture_name, src / fixture_name)

    out = tmp_path / "out"
    plan = InvocationPlan(stack_name=None, enex_source=src, output_dir=out)
    result = run_invocation(plan, template_file=template, yarle_version=YARLE_PINNED_VERSION)
    if result.returncode != 0:
        raise RuntimeError(
            f"yarle exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return out


def test_simple_note_converts_to_markdown_with_frontmatter(tmp_path: Path, template_file: Path) -> None:
    out = _convert("simple.enex", tmp_path, template_file)
    md_files = _list_md_files(out)
    assert len(md_files) == 1, f"expected 1 .md, got {[p.name for p in md_files]}"

    md = md_files[0]
    fm = _read_frontmatter(md)
    assert "created" in fm
    assert "updated" in fm
    body = md.read_text(encoding="utf-8")
    assert "Hello world" in body


def test_note_with_attachment_writes_image_to_attachments_folder(
    tmp_path: Path, template_file: Path
) -> None:
    out = _convert("with-attachment.enex", tmp_path, template_file)
    md_files = _list_md_files(out)
    assert len(md_files) == 1

    # Find the _attachments folder
    attachments = list(out.rglob("_attachments"))
    assert len(attachments) >= 1, f"no _attachments folder under {out}"
    files_in_attachments = [
        p for p in attachments[0].iterdir() if p.is_file()
    ]
    assert len(files_in_attachments) >= 1
    # Markdown should reference the attachment
    body = md_files[0].read_text(encoding="utf-8")
    assert "_attachments" in body or files_in_attachments[0].name in body


def test_web_clip_produces_clean_markdown(tmp_path: Path, template_file: Path) -> None:
    out = _convert("web-clip.enex", tmp_path, template_file)
    md_files = _list_md_files(out)
    assert len(md_files) == 1
    body = md_files[0].read_text(encoding="utf-8")
    fm = _read_frontmatter(md_files[0])
    # Source URL preserved in frontmatter
    assert "source" in fm
    assert "example.com" in fm["source"]
    # Tags preserved
    assert "tags" in fm
    # Inline color/font styles should be aggressively stripped
    # (heuristic: should not contain raw style attribute strings)
    assert "font-family" not in body.lower()
    assert "rgb(" not in body.lower()


def test_tags_become_yaml_array(tmp_path: Path, template_file: Path) -> None:
    out = _convert("tag-edge-cases.enex", tmp_path, template_file)
    md_files = _list_md_files(out)
    assert len(md_files) == 1
    body = md_files[0].read_text(encoding="utf-8")
    # YAML array form, not inline #tags
    fm = _read_frontmatter(md_files[0])
    assert "tags" in fm
    tag_value = fm["tags"]
    # Expect bracketed YAML list form
    assert tag_value.startswith("["), f"tags not a YAML array: {tag_value!r}"
    # And the body itself should not have `#tag` inline tag soup at the top
    # (We allow `#` to appear as part of a heading or markdown body.)


def test_code_block_becomes_fenced_block(tmp_path: Path, template_file: Path) -> None:
    out = _convert("code-block.enex", tmp_path, template_file)
    md_files = _list_md_files(out)
    assert len(md_files) == 1
    body = md_files[0].read_text(encoding="utf-8")
    # Either fenced block markers or at least monospace content preserved
    assert "function add" in body
    assert "```" in body or "    function add" in body  # fenced or indented code


def test_multi_note_produces_one_md_per_note(tmp_path: Path, template_file: Path) -> None:
    out = _convert("multi-note.enex", tmp_path, template_file)
    md_files = _list_md_files(out)
    assert len(md_files) == 10
    for md in md_files:
        fm = _read_frontmatter(md)
        assert "created" in fm
        assert "updated" in fm
