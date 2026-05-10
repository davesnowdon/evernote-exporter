"""Marker file management and output-directory state classification.

The marker file is the single mechanism that lets re-runs know they own a
target directory. Any directory we own contains `.evernote-export-marker`.
Any directory that exists without the marker is treated as foreign and is
refused — to protect user data from a typo.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

MARKER_FILENAME = ".evernote-export-marker"


@dataclass(frozen=True)
class MarkerInfo:
    tool: str
    tool_version: str
    yarle_version: str
    created_at: str
    source_dir: str


class OutputState(Enum):
    DOES_NOT_EXIST = "does_not_exist"
    OWNED = "owned"
    FOREIGN = "foreign"


def write_marker(output_dir: Path, info: MarkerInfo) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    marker = output_dir / MARKER_FILENAME
    marker.write_text(json.dumps(asdict(info), indent=2, sort_keys=True), encoding="utf-8")


def read_marker(output_dir: Path) -> MarkerInfo | None:
    marker = output_dir / MARKER_FILENAME
    if not marker.exists():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        return MarkerInfo(**payload)
    except (json.JSONDecodeError, TypeError):
        return None


def inspect_output_dir(output_dir: Path) -> OutputState:
    """Classify the target directory without modifying it."""
    if not output_dir.exists():
        return OutputState.DOES_NOT_EXIST
    if not output_dir.is_dir():
        raise NotADirectoryError(f"{output_dir} exists but is not a directory")
    if (output_dir / MARKER_FILENAME).exists():
        return OutputState.OWNED
    return OutputState.FOREIGN
