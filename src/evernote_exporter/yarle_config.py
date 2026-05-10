"""Yarle configuration: per-invocation config dict + the note template.

Per design §7. Each invocation of Yarle gets its own config dict (the
enex_source and output_dir vary per stack) but the rest of the config is
constant.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Yarle template syntax (see Templates.md). Two block-handling functions
# behave differently:
#   - applyConditionalTemplate (created-at, updated-at, source-url):
#       removes only start/end markers; the empty-removal regex uses
#       `(.*)` which does NOT cross newlines, but DOES consume one trailing
#       `\r?\n?`. So: keep block on one line, put `\n` OUTSIDE.
#   - applyTemplateOnBlock (tags-array, title, content):
#       removes across newlines via `[\d\D]...(?=end)`, but does NOT consume
#       a trailing newline. So: put the `\n` INSIDE the block instead.
NOTE_TEMPLATE = (
    "---\n"
    "{created-at-block}created: {created-at}{end-created-at-block}\n"
    "{updated-at-block}updated: {updated-at}{end-updated-at-block}\n"
    "{tags-array-block}tags: {tags-array}\n{end-tags-array-block}"
    "{source-url-block}source: {source-url}{end-source-url-block}\n"
    "---\n"
    "\n"
    "{title-block}# {title}\n\n{end-title-block}"
    "{content-block}{content}{end-content-block}"
)


def build_yarle_config(
    *,
    enex_source: Path,
    output_dir: Path,
    template_file: Path,
) -> dict[str, Any]:
    """Build a single Yarle config dict ready for json.dump.

    `enex_source` may be a directory of .enex files (Yarle reads top-level)
    or a single .enex file. `output_dir` is where Yarle writes the
    notebook subfolders. `template_file` is the path to the rendered
    note template.
    """
    return {
        "enexSources": [str(enex_source)],
        "outputDir": str(output_dir),
        "templateFile": str(template_file),
        "outputFormat": "OBSIDIAN_MD",

        # Hierarchy and resources
        "isNotebookNameNeeded": True,
        "haveEnexLevelResources": True,
        "resourcesDir": "_attachments",

        # Metadata
        "isMetadataNeeded": True,
        "skipAuthor": True,
        "skipLocation": True,
        "skipPlaceName": True,
        "skipReminderTime": True,
        "skipReminderOrder": True,
        "skipReminderDoneTime": True,
        "skipApplicationData": True,
        "skipContentClass": True,
        "dateFormat": "YYYY-MM-DDTHH:mm:ssZ",

        # Tags
        "useHashTags": False,
        "nestedTags": {"separatorInEN": "/", "replaceSeparatorWith": "/"},

        # Filename and content sanitization
        "keepMDCharactersOfENNotes": False,
        "replacementChar": "-",
        # replacementCharacterMap is applied to titles before sanitize-filename.
        # Keep spaces out of filenames (DESIGN.md §9).
        "replacementCharacterMap": {" ": "-"},
        "sanitizeResourceNameSpaces": True,
        "useUniqueUnknownFileNames": True,

        # Web clips
        "skipWebClips": False,
        "keepOriginalHtml": False,

        # Code blocks
        "monospaceIsCodeBlock": True,

        # Internal links
        "obsidianSettings": {"omitLinkDisplayName": False},
        "addExtensionToInternalLinks": False,
        "keepEvernoteLinkIfNoNoteFound": False,
    }


def write_template(path: Path) -> None:
    """Write the note template file Yarle will read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NOTE_TEMPLATE, encoding="utf-8")
