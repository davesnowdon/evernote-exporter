"""Tests for reporter: counts diff, anomalies, text + JSON output."""
from __future__ import annotations

import json
from pathlib import Path

from evernote_exporter.enex_parser import EnexCounts
from evernote_exporter.reporter import (
    Anomaly,
    NotebookReport,
    OutputCounts,
    ReportData,
    StackReport,
    build_report,
    count_output,
    detect_anomalies,
    format_text_report,
    write_reports,
)


# ---- count_output --------------------------------------------------------


def test_count_output_counts_md_files_in_a_notebook_folder(tmp_path: Path) -> None:
    nb = tmp_path / "Meetings"
    nb.mkdir()
    (nb / "a.md").write_text("---\ncreated: x\n---\nbody")
    (nb / "b.md").write_text("---\ncreated: x\n---\nbody")
    (nb / "_attachments").mkdir()
    (nb / "_attachments" / "img.png").write_bytes(b"PNG")

    counts = count_output(nb)

    assert counts.notes == 2
    assert counts.attachments == 1


def test_count_output_excludes_marker_and_report_files(tmp_path: Path) -> None:
    nb = tmp_path / "Meetings"
    nb.mkdir()
    (nb / "real.md").write_text("---\nx\n---\nbody")
    # These should not be counted as notes
    (nb / "migration-report.txt").write_text("report")
    (nb / "migration-errors.log").write_text("err")
    (nb / ".evernote-export-marker").write_text("{}")

    counts = count_output(nb)
    assert counts.notes == 1


def test_count_output_returns_zeros_for_missing_dir(tmp_path: Path) -> None:
    counts = count_output(tmp_path / "missing")
    assert counts.notes == 0
    assert counts.attachments == 0


def test_count_output_skips_files_without_frontmatter_marker(tmp_path: Path) -> None:
    nb = tmp_path / "nb"
    nb.mkdir()
    (nb / "with-fm.md").write_text("---\nfoo: 1\n---\nx")
    (nb / "no-fm.md").write_text("plain markdown without frontmatter")

    counts = count_output(nb)
    assert counts.notes == 1  # only the one with frontmatter
    assert counts.notes_missing_frontmatter == 1


# ---- detect_anomalies ---------------------------------------------------


def test_detect_anomalies_flags_short_outputs(tmp_path: Path) -> None:
    nb = tmp_path / "nb"
    nb.mkdir()
    # Output is 50 chars but ENEX node was very large
    short = nb / "Tiny.md"
    short.write_text("---\ncreated: x\n---\nbody")  # ~22 char body
    # ENEX-side is large
    enex_byte_size = 6000

    anomalies = detect_anomalies(nb, enex_byte_size_per_note=enex_byte_size)

    assert len(anomalies) == 1
    assert anomalies[0].kind == "short_output"


def test_detect_anomalies_returns_empty_when_outputs_are_proportional(tmp_path: Path) -> None:
    nb = tmp_path / "nb"
    nb.mkdir()
    big = nb / "Big.md"
    big.write_text("---\ncreated: x\n---\n" + "a" * 5000)
    anomalies = detect_anomalies(nb, enex_byte_size_per_note=6000)
    assert anomalies == []


# ---- build_report --------------------------------------------------------


def test_build_report_aggregates_per_stack(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    work = enex_dir / "Work"
    work.mkdir(parents=True)
    work_meeting = work / "Meetings.enex"
    work_meeting.write_text(
        '<?xml version="1.0"?><en-export>'
        '<note><title>m</title><content><![CDATA[<en-note>x</en-note>]]></content>'
        '<created>20200101T000000Z</created><updated>20200101T000000Z</updated></note>'
        '</en-export>'
    )

    output = tmp_path / "out" / "Work" / "Meetings"
    output.mkdir(parents=True)
    (output / "m.md").write_text("---\ncreated: x\n---\nbody")

    report = build_report(
        source_dir=enex_dir,
        output_dir=tmp_path / "out",
        run_started="2026-05-06T14:30:22Z",
        run_finished="2026-05-06T14:34:39Z",
        yarle_version="7.4.2",
        invocation_failures=[],
    )

    assert report.totals.notes_in == 1
    assert report.totals.notes_out == 1
    assert any(s.name == "Work" for s in report.stacks)


def test_build_report_records_invocation_failures(tmp_path: Path) -> None:
    enex_dir = tmp_path / "enex"
    enex_dir.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    report = build_report(
        source_dir=enex_dir,
        output_dir=out,
        run_started="2026-05-06T14:30:22Z",
        run_finished="2026-05-06T14:30:30Z",
        yarle_version="7.4.2",
        invocation_failures=["Work: yarle exit 2: missing dependency"],
    )

    assert report.invocation_failures == ["Work: yarle exit 2: missing dependency"]


# ---- format_text_report -------------------------------------------------


def test_format_text_report_includes_required_sections() -> None:
    data = ReportData(
        source_dir="/x/in",
        output_dir="/x/out",
        run_started="2026-05-06T14:30:22Z",
        run_finished="2026-05-06T14:34:39Z",
        yarle_version="7.4.2",
        stacks=[
            StackReport(
                name="Work",
                notebooks=[
                    NotebookReport(
                        name="Meetings",
                        notes_in=42,
                        notes_out=42,
                        attachments_in=12,
                        attachments_out=12,
                        frontmatter_valid=42,
                    ),
                ],
            ),
        ],
        totals=OutputCounts(
            notebooks_in=1,
            notebooks_out=1,
            notes_in=42,
            notes_out=42,
            attachments_in=12,
            attachments_out=12,
            frontmatter_valid=42,
        ),
        anomalies=[],
        invocation_failures=[],
    )

    text = format_text_report(data)

    assert "/x/in" in text
    assert "/x/out" in text
    assert "7.4.2" in text
    assert "Work" in text
    assert "42" in text


# ---- write_reports -------------------------------------------------------


def test_write_reports_writes_text_and_json_alongside_each_other(tmp_path: Path) -> None:
    data = ReportData(
        source_dir="/x/in",
        output_dir=str(tmp_path),
        run_started="2026-05-06T14:30:22Z",
        run_finished="2026-05-06T14:30:25Z",
        yarle_version="7.4.2",
        stacks=[],
        totals=OutputCounts(
            notebooks_in=0,
            notebooks_out=0,
            notes_in=0,
            notes_out=0,
            attachments_in=0,
            attachments_out=0,
            frontmatter_valid=0,
        ),
        anomalies=[],
        invocation_failures=[],
    )

    write_reports(data, output_dir=tmp_path)

    assert (tmp_path / "migration-report.txt").exists()
    assert (tmp_path / "migration-report.json").exists()

    payload = json.loads((tmp_path / "migration-report.json").read_text())
    assert payload["source_dir"] == "/x/in"
    assert payload["yarle_version"] == "7.4.2"


# ---- ReportData.exit_code -----------------------------------------------


def test_report_exit_code_is_zero_when_counts_match() -> None:
    data = ReportData(
        source_dir="x",
        output_dir="y",
        run_started="t",
        run_finished="t",
        yarle_version="v",
        stacks=[],
        totals=OutputCounts(
            notebooks_in=1,
            notebooks_out=1,
            notes_in=10,
            notes_out=10,
            attachments_in=2,
            attachments_out=2,
            frontmatter_valid=10,
        ),
        anomalies=[],
        invocation_failures=[],
    )
    assert data.exit_code() == 0


def test_report_exit_code_is_two_when_invocation_failures_present() -> None:
    data = ReportData(
        source_dir="x",
        output_dir="y",
        run_started="t",
        run_finished="t",
        yarle_version="v",
        stacks=[],
        totals=OutputCounts(
            notebooks_in=1,
            notebooks_out=1,
            notes_in=10,
            notes_out=10,
            attachments_in=2,
            attachments_out=2,
            frontmatter_valid=10,
        ),
        anomalies=[],
        invocation_failures=["Work: failed"],
    )
    assert data.exit_code() == 2


def test_report_exit_code_is_three_when_counts_mismatch() -> None:
    data = ReportData(
        source_dir="x",
        output_dir="y",
        run_started="t",
        run_finished="t",
        yarle_version="v",
        stacks=[],
        totals=OutputCounts(
            notebooks_in=1,
            notebooks_out=1,
            notes_in=10,
            notes_out=9,  # mismatch
            attachments_in=2,
            attachments_out=2,
            frontmatter_valid=9,
        ),
        anomalies=[],
        invocation_failures=[],
    )
    assert data.exit_code() == 3


def test_report_exit_code_is_zero_when_more_attachments_out_than_in() -> None:
    # Yarle extracts inline data-URL images (e.g. SVGs in web clips) that
    # aren't <resource> elements in the ENEX. More-out is fine.
    data = ReportData(
        source_dir="x",
        output_dir="y",
        run_started="t",
        run_finished="t",
        yarle_version="v",
        stacks=[],
        totals=OutputCounts(
            notebooks_in=1,
            notebooks_out=1,
            notes_in=10,
            notes_out=10,
            attachments_in=5,
            attachments_out=12,  # 7 extras from inline data-URLs
            frontmatter_valid=10,
        ),
        anomalies=[],
        invocation_failures=[],
    )
    assert data.exit_code() == 0


def test_report_exit_code_is_three_when_attachments_lost() -> None:
    data = ReportData(
        source_dir="x",
        output_dir="y",
        run_started="t",
        run_finished="t",
        yarle_version="v",
        stacks=[],
        totals=OutputCounts(
            notebooks_in=1,
            notebooks_out=1,
            notes_in=10,
            notes_out=10,
            attachments_in=5,
            attachments_out=4,  # one missing
            frontmatter_valid=10,
        ),
        anomalies=[],
        invocation_failures=[],
    )
    assert data.exit_code() == 3
