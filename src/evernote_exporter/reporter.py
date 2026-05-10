"""Verification + report generation.

After Yarle runs, walk the output, compare counts against ENEX-side counts,
detect anomalies, and produce migration-report.txt / migration-report.json.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .enex_parser import count_enex, count_enex_dir, discover_stacks
from .safety import MARKER_FILENAME
from .yarle_config import yarle_filename_for

# Files inside the output dir that are NOT note files
_REPORT_AND_MARKER_FILES = {
    MARKER_FILENAME,
    "migration-report.txt",
    "migration-report.json",
    "migration-errors.log",
}

# Anomaly thresholds (per design §16)
SHORT_OUTPUT_BYTE_THRESHOLD = 100
LARGE_INPUT_BYTE_THRESHOLD = 5000


@dataclass(frozen=True)
class OutputCounts:
    notebooks_in: int
    notebooks_out: int
    notes_in: int
    notes_out: int
    attachments_in: int
    attachments_out: int
    frontmatter_valid: int


@dataclass(frozen=True)
class NotebookCounts:
    notes: int = 0
    attachments: int = 0
    notes_missing_frontmatter: int = 0


@dataclass(frozen=True)
class NotebookReport:
    name: str
    notes_in: int
    notes_out: int
    attachments_in: int
    attachments_out: int
    frontmatter_valid: int


@dataclass(frozen=True)
class StackReport:
    name: str
    notebooks: list[NotebookReport]


@dataclass(frozen=True)
class Anomaly:
    kind: str
    path: str
    detail: str


@dataclass(frozen=True)
class ReportData:
    source_dir: str
    output_dir: str
    run_started: str
    run_finished: str
    yarle_version: str
    stacks: list[StackReport]
    totals: OutputCounts
    anomalies: list[Anomaly]
    invocation_failures: list[str] = field(default_factory=list)

    def exit_code(self) -> int:
        if self.invocation_failures:
            return 2
        t = self.totals
        # Notes / notebooks / frontmatter must match exactly.
        # Attachments may exceed input count: Yarle extracts inline data-URL
        # images (e.g. SVGs in web-clipped HTML) which aren't <resource>
        # elements in the ENEX. Only flag *fewer* attachments out as a loss.
        if (
            t.notes_in != t.notes_out
            or t.attachments_out < t.attachments_in
            or t.notebooks_in != t.notebooks_out
            or t.frontmatter_valid != t.notes_out
        ):
            return 3
        return 0


def _has_frontmatter(md_path: Path) -> bool:
    try:
        with md_path.open("r", encoding="utf-8") as f:
            head = f.readline()
        return head.strip() == "---"
    except OSError:
        return False


def count_output(notebook_dir: Path) -> NotebookCounts:
    """Count .md notes and attachment files inside a single notebook folder.

    Excludes report and marker files. A .md without frontmatter is counted
    as `notes_missing_frontmatter` and not as a regular note.
    """
    if not notebook_dir.exists() or not notebook_dir.is_dir():
        return NotebookCounts()

    notes = 0
    missing_fm = 0
    for md in notebook_dir.glob("*.md"):
        if md.name in _REPORT_AND_MARKER_FILES:
            continue
        if _has_frontmatter(md):
            notes += 1
        else:
            missing_fm += 1

    attachments = 0
    attachments_dir = notebook_dir / "_attachments"
    if attachments_dir.is_dir():
        attachments = sum(1 for p in attachments_dir.iterdir() if p.is_file())

    return NotebookCounts(
        notes=notes, attachments=attachments, notes_missing_frontmatter=missing_fm
    )


def detect_anomalies(
    notebook_dir: Path,
    *,
    enex_byte_size_per_note: int = 0,
) -> list[Anomaly]:
    """Flag .md files that look suspiciously short relative to ENEX input."""
    anomalies: list[Anomaly] = []
    if not notebook_dir.is_dir():
        return anomalies
    if enex_byte_size_per_note < LARGE_INPUT_BYTE_THRESHOLD:
        return anomalies
    for md in notebook_dir.glob("*.md"):
        if md.name in _REPORT_AND_MARKER_FILES:
            continue
        size = md.stat().st_size
        if size < SHORT_OUTPUT_BYTE_THRESHOLD:
            anomalies.append(
                Anomaly(
                    kind="short_output",
                    path=str(md),
                    detail=f"output {size} bytes; ENEX input ~{enex_byte_size_per_note} bytes",
                )
            )
    return anomalies


def build_report(
    *,
    source_dir: Path,
    output_dir: Path,
    run_started: str,
    run_finished: str,
    yarle_version: str,
    invocation_failures: list[str],
) -> ReportData:
    """Walk source + output and compute the migration report."""
    stacks: list[StackReport] = []
    totals = {
        "notebooks_in": 0,
        "notebooks_out": 0,
        "notes_in": 0,
        "notes_out": 0,
        "attachments_in": 0,
        "attachments_out": 0,
        "frontmatter_valid": 0,
    }
    anomalies: list[Anomaly] = []

    for group in discover_stacks(source_dir):
        if group.name is None:
            stack_label = "(root)"
            stack_output = output_dir
        else:
            stack_label = group.name
            stack_output = output_dir / group.name

        notebooks: list[NotebookReport] = []
        for enex_file in group.enex_files:
            counts_in = count_enex(enex_file)
            # ENEX stem may contain spaces / forbidden chars that Yarle
            # rewrites in its output folder. Mirror that sanitization to
            # locate the actual output directory.
            notebook_name = yarle_filename_for(enex_file.stem)
            notebook_out_dir = stack_output / notebook_name
            counts_out = count_output(notebook_out_dir)

            # Per-note enex byte size (rough average) for anomaly detection
            avg_size = enex_file.stat().st_size // max(counts_in.notes, 1)
            anomalies.extend(
                detect_anomalies(
                    notebook_out_dir,
                    enex_byte_size_per_note=avg_size,
                )
            )

            notebooks.append(
                NotebookReport(
                    name=notebook_name,
                    notes_in=counts_in.notes,
                    notes_out=counts_out.notes,
                    attachments_in=counts_in.resources,
                    attachments_out=counts_out.attachments,
                    frontmatter_valid=counts_out.notes,
                )
            )
            totals["notebooks_in"] += 1
            if notebook_out_dir.exists():
                totals["notebooks_out"] += 1
            totals["notes_in"] += counts_in.notes
            totals["notes_out"] += counts_out.notes
            totals["attachments_in"] += counts_in.resources
            totals["attachments_out"] += counts_out.attachments
            totals["frontmatter_valid"] += counts_out.notes

        stacks.append(StackReport(name=stack_label, notebooks=notebooks))

    return ReportData(
        source_dir=str(source_dir),
        output_dir=str(output_dir),
        run_started=run_started,
        run_finished=run_finished,
        yarle_version=yarle_version,
        stacks=stacks,
        totals=OutputCounts(**totals),
        anomalies=anomalies,
        invocation_failures=list(invocation_failures),
    )


def format_text_report(data: ReportData) -> str:
    t = data.totals
    lines: list[str] = []
    lines.append("Evernote → Obsidian migration report")
    lines.append("=" * 40)
    lines.append(f"Source:        {data.source_dir}")
    lines.append(f"Output:        {data.output_dir}")
    lines.append(f"Run started:   {data.run_started}")
    lines.append(f"Run finished:  {data.run_finished}")
    lines.append(f"Yarle version: {data.yarle_version}")
    lines.append("")

    lines.append(f"Stacks:        {len(data.stacks)}")
    lines.append(
        f"Notebooks:     {t.notebooks_in} "
        f"({t.notebooks_out}/{t.notebooks_in} ENEX → output OK)"
    )
    lines.append(
        f"Notes:         {t.notes_in} in / {t.notes_out} out "
        f"({'OK' if t.notes_in == t.notes_out else 'MISMATCH'})"
    )
    if t.attachments_out < t.attachments_in:
        att_status = "MISMATCH (data loss)"
    elif t.attachments_out > t.attachments_in:
        att_status = "OK (extras: inline data-URL extracts)"
    else:
        att_status = "OK"
    lines.append(
        f"Attachments:   {t.attachments_in} in / {t.attachments_out} out ({att_status})"
    )
    lines.append(
        f"Frontmatter:   {t.frontmatter_valid}/{t.notes_out} valid "
        f"({'OK' if t.frontmatter_valid == t.notes_out else 'MISMATCH'})"
    )
    lines.append("")

    if data.stacks:
        lines.append("Per-stack breakdown:")
        for stack in data.stacks:
            lines.append(f"  {stack.name}/")
            for nb in stack.notebooks:
                status = "OK" if nb.notes_in == nb.notes_out else "MISMATCH"
                lines.append(
                    f"    {nb.name}: notes {nb.notes_in}→{nb.notes_out}, "
                    f"attachments {nb.attachments_in}→{nb.attachments_out} [{status}]"
                )
        lines.append("")

    if data.anomalies:
        lines.append(f"Anomalies ({len(data.anomalies)}):")
        for a in data.anomalies:
            lines.append(f"  [{a.kind}] {a.path}")
            lines.append(f"    {a.detail}")
        lines.append("")
    else:
        lines.append("Anomalies:     none")
        lines.append("")

    if data.invocation_failures:
        lines.append("Yarle invocation failures:")
        for f in data.invocation_failures:
            lines.append(f"  - {f}")
        lines.append("")
    else:
        lines.append("Yarle errors:  0")
        lines.append("")

    code = data.exit_code()
    lines.append(f"Result: {'SUCCESS' if code == 0 else 'FAILURE'} (exit {code})")
    return "\n".join(lines) + "\n"


def write_reports(data: ReportData, *, output_dir: Path) -> None:
    """Write migration-report.txt and migration-report.json side by side."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "migration-report.txt").write_text(
        format_text_report(data), encoding="utf-8"
    )
    payload = asdict(data)
    payload["exit_code"] = data.exit_code()
    (output_dir / "migration-report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
