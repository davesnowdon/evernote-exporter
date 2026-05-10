"""Generate hand-crafted ENEX fixture files deterministically.

Run from repo root:  python tests/build_fixtures.py
Outputs are committed under tests/fixtures/.

Each fixture targets a specific scenario; see DESIGN.md §13.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from textwrap import dedent

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# A 1x1 transparent PNG (pre-computed). Used as the embedded resource binary.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMAAAACAAEAAAAFAAAAAElFTkSuQmCC"
)
TINY_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000000020001000000050000000049454e44ae426082"
)
TINY_PNG_MD5 = hashlib.md5(TINY_PNG_BYTES).hexdigest()


def enex_envelope(notes_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export4.dtd">\n'
        '<en-export export-date="20260506T143022Z" application="Evernote" version="10.0">\n'
        f"{notes_xml}"
        "</en-export>\n"
    )


def note(
    title: str,
    body_html: str,
    *,
    created: str = "20180405T102300Z",
    updated: str = "20241130T191200Z",
    tags: tuple[str, ...] = (),
    source_url: str | None = None,
    resources: tuple[str, ...] = (),
) -> str:
    tag_xml = "".join(f"  <tag>{t}</tag>\n" for t in tags)
    src_xml = (
        f"  <note-attributes>\n    <source-url>{source_url}</source-url>\n  </note-attributes>\n"
        if source_url
        else ""
    )
    res_xml = "".join(resources)
    return (
        "<note>\n"
        f"  <title>{title}</title>\n"
        f"  <content><![CDATA[<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        f"<!DOCTYPE en-note SYSTEM \"http://xml.evernote.com/pub/enml2.dtd\">"
        f"<en-note>{body_html}</en-note>]]></content>\n"
        f"  <created>{created}</created>\n"
        f"  <updated>{updated}</updated>\n"
        f"{tag_xml}{src_xml}{res_xml}"
        "</note>\n"
    )


def png_resource(filename: str) -> str:
    return dedent(
        f"""\
        <resource>
          <data encoding="base64">{TINY_PNG_B64}</data>
          <mime>image/png</mime>
          <width>1</width>
          <height>1</height>
          <resource-attributes>
            <file-name>{filename}</file-name>
          </resource-attributes>
        </resource>
        """
    )


# ---- fixture builders -----------------------------------------------------


def fix_simple() -> str:
    return enex_envelope(
        note(
            title="Simple Plain Note",
            body_html="<div>Hello world.</div><div>This is a plain note.</div>",
        )
    )


def fix_with_attachment() -> str:
    en_media = f'<en-media type="image/png" hash="{TINY_PNG_MD5}"/>'
    return enex_envelope(
        note(
            title="Note With Attachment",
            body_html=f"<div>Inline image follows.</div><div>{en_media}</div>",
            resources=(png_resource("photo.png"),),
        )
    )


def fix_web_clip() -> str:
    body = (
        '<div style="font-family: Arial, sans-serif; color: #333;">'
        '<h1 style="font-size: 24px; color: #f00;">Article title</h1>'
        '<p style="font-size: 14px;">Body of an article with '
        '<span style="background: yellow;">highlighted</span> text.</p>'
        '<div style="border: 1px solid #ccc; padding: 10px;">'
        '<p>Boxed content from the original page.</p>'
        '</div></div>'
    )
    return enex_envelope(
        note(
            title="Web Clipped Article",
            body_html=body,
            tags=("article", "research"),
            source_url="https://example.com/article",
        )
    )


def fix_tag_edge_cases() -> str:
    return enex_envelope(
        note(
            title="Tag Edge Cases",
            body_html="<div>Various tag transformations exercised here.</div>",
            tags=("simple", "two words", "with-hyphen", "work/projects", "café"),
        )
    )


def fix_filename_edge_cases() -> str:
    notes = (
        note(title="Has/Slash In Title", body_html="<div>slash</div>"),
        note(title="Has: Colon", body_html="<div>colon</div>"),
        note(title="Café Accented", body_html="<div>accented</div>"),
        note(title="Duplicate Title", body_html="<div>first</div>"),
        note(title="Duplicate Title", body_html="<div>second</div>"),
        note(title="", body_html="<div>empty title</div>"),
    )
    return enex_envelope("".join(notes))


def fix_code_block() -> str:
    body = (
        "<div>Below is a code block:</div>"
        '<div style="-en-codeblock:true;box-sizing:border-box;'
        "padding:8px;font-family:Monaco,Menlo,Consolas,'Courier New',monospace;"
        'font-size:12px;color:rgb(51,51,51);background-color:rgb(251,250,248);">'
        "<div>function add(a, b) {</div>"
        "<div>  return a + b;</div>"
        "<div>}</div>"
        "</div>"
    )
    return enex_envelope(note(title="Code Block Example", body_html=body))


def fix_multi_note() -> str:
    notes = "".join(
        note(
            title=f"Multi {i}",
            body_html=f"<div>Body of note {i}.</div>",
            created="20200101T120000Z",
            updated=f"202404{i:02d}T120000Z",
        )
        for i in range(1, 11)
    )
    return enex_envelope(notes)


FIXTURES = {
    "simple.enex": fix_simple,
    "with-attachment.enex": fix_with_attachment,
    "web-clip.enex": fix_web_clip,
    "tag-edge-cases.enex": fix_tag_edge_cases,
    "filename-edge-cases.enex": fix_filename_edge_cases,
    "code-block.enex": fix_code_block,
    "multi-note.enex": fix_multi_note,
}


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for name, builder in FIXTURES.items():
        target = FIXTURES_DIR / name
        target.write_text(builder(), encoding="utf-8")
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
