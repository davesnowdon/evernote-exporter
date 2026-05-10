"""Lightweight ENEX inspector — counts notes and resources via stdlib XML.

We do not parse note content. We only count `<note>` and `<resource>` elements
to support the verification step (compare ENEX-side counts vs Yarle's output).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class EnexCounts:
    notes: int
    resources: int
    path: Path


@dataclass(frozen=True)
class StackGroup:
    """A stack subdirectory (or the root-level group when name is None)."""

    name: str | None
    directory: Path
    enex_files: tuple[Path, ...] = field(default_factory=tuple)


def count_enex(path: Path) -> EnexCounts:
    """Count <note> and <resource> elements in a single ENEX file."""
    tree = ET.parse(path)
    root = tree.getroot()
    notes = root.findall(".//note")
    resources = root.findall(".//resource")
    return EnexCounts(notes=len(notes), resources=len(resources), path=path)


def count_enex_dir(directory: Path) -> list[EnexCounts]:
    """Count every top-level .enex file in `directory`. Does not recurse."""
    return [count_enex(p) for p in sorted(directory.glob("*.enex"))]


def discover_stacks(enex_dir: Path) -> list[StackGroup]:
    """Discover stack subdirs and root-level ENEX files.

    Mirrors evernote-backup's output layout:
      <enex_dir>/<Stack>/<Notebook>.enex   for stacked notebooks
      <enex_dir>/<Notebook>.enex           for stackless notebooks

    Empty subdirectories are skipped. Subdirectories without any .enex are
    skipped. Returns subdirs with name set, plus a single root group with
    name=None if root-level .enex files exist.
    """
    groups: list[StackGroup] = []

    for sub in sorted(p for p in enex_dir.iterdir() if p.is_dir()):
        enex_files = tuple(sorted(sub.glob("*.enex")))
        if enex_files:
            groups.append(StackGroup(name=sub.name, directory=sub, enex_files=enex_files))

    root_enex = tuple(sorted(enex_dir.glob("*.enex")))
    if root_enex:
        groups.append(StackGroup(name=None, directory=enex_dir, enex_files=root_enex))

    return groups
