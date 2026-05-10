"""Command-line interface and top-level orchestration."""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import YARLE_PINNED_VERSION, __version__
from .orchestrator import run_invocations
from .preflight import (
    check_enex_dir_has_files,
    check_node_available,
    check_obsidian_vault,
    check_output_dir_safe,
    check_vault_directory,
    check_writable,
    check_yarle_available,
)
from .reporter import build_report, write_reports
from .safety import MarkerInfo, write_marker
from .yarle_config import write_template


@dataclass(frozen=True)
class Args:
    enex_dir: Path
    vault: Path
    root_folder: str
    yes: bool
    dry_run: bool
    verbose: bool
    no_vault_check: bool
    yarle_version: str


def parse_args(argv: list[str]) -> Args:
    parser = argparse.ArgumentParser(
        prog="python -m evernote_exporter",
        description="Convert Evernote ENEX files into an Obsidian vault subfolder.",
    )
    parser.add_argument("--enex-dir", required=True, type=Path,
                        help="Directory of ENEX files (output of evernote-backup export).")
    parser.add_argument("--vault", required=True, type=Path,
                        help="Existing Obsidian vault root.")
    parser.add_argument("--root-folder", required=True,
                        help="Subfolder name within the vault for the import.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and print plan, then exit.")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output.")
    parser.add_argument("--no-vault-check", action="store_true",
                        help="Skip the .obsidian/ existence check.")
    parser.add_argument("--yarle-version", default=YARLE_PINNED_VERSION,
                        help=f"Override the pinned Yarle version (default: {YARLE_PINNED_VERSION}).")
    ns = parser.parse_args(argv)
    return Args(
        enex_dir=ns.enex_dir,
        vault=ns.vault,
        root_folder=ns.root_folder,
        yes=ns.yes,
        dry_run=ns.dry_run,
        verbose=ns.verbose,
        no_vault_check=ns.no_vault_check,
        yarle_version=ns.yarle_version,
    )


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_preflight(args: Args, output_dir: Path) -> tuple[bool, list[str]]:
    """Run all preflight checks. Returns (passed, messages)."""
    checks = [
        ("node", check_node_available()),
        ("yarle", check_yarle_available(args.yarle_version)),
        ("enex-dir", check_enex_dir_has_files(args.enex_dir)),
        ("vault", check_vault_directory(args.vault)),
    ]
    if not args.no_vault_check:
        checks.append(("obsidian", check_obsidian_vault(args.vault)))
    checks.append(("output-dir", check_output_dir_safe(output_dir)))
    checks.append(("writable", check_writable(output_dir)))

    messages = [f"  [{name}] {r.message}" for name, r in checks]
    passed = all(r.passed for _, r in checks)
    return passed, messages


def _confirm(prompt: str) -> bool:
    """Read a yes/no answer from stdin. Returns False on EOF or 'n'."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        return False
    return line.strip().lower() in ("y", "yes")


def _wipe_and_recreate(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)

    output_dir = args.vault / args.root_folder

    print(f"evernote-exporter {__version__}")
    print(f"  enex-dir:      {args.enex_dir}")
    print(f"  vault:         {args.vault}")
    print(f"  root-folder:   {args.root_folder}")
    print(f"  output-dir:    {output_dir}")
    print(f"  yarle-version: {args.yarle_version}")
    print()
    print("Running preflight checks...")
    passed, messages = _run_preflight(args, output_dir)
    for line in messages:
        print(line)
    if not passed:
        print()
        print("Preflight failed. See messages above.")
        return 1

    if args.dry_run:
        print()
        print("Dry run: preflight OK; not invoking Yarle.")
        return 0

    if not args.yes:
        prompt = (
            f"\nThis will create or replace: {output_dir}\n"
            f"Source: {args.enex_dir}\n"
            "Continue? [y/N] "
        )
        if not _confirm(prompt):
            print("Aborted by user.")
            return 1

    run_started = _now_iso()
    _wipe_and_recreate(output_dir)

    template_file = output_dir / ".yarle-template.tmpl"
    write_template(template_file)

    invocations = run_invocations(
        enex_dir=args.enex_dir,
        output_root=output_dir,
        template_file=template_file,
        yarle_version=args.yarle_version,
    )
    run_finished = _now_iso()

    invocation_failures: list[str] = []
    error_log_lines: list[str] = []
    for inv in invocations:
        label = inv.plan.stack_name or "(root)"
        if inv.returncode != 0:
            invocation_failures.append(
                f"{label}: yarle exit {inv.returncode}: {inv.stderr.strip()[:200]}"
            )
        if inv.stderr:
            error_log_lines.append(f"=== {label} ===\n{inv.stderr}\n")

    # Write captured stderr
    if error_log_lines:
        (output_dir / "migration-errors.log").write_text(
            "\n".join(error_log_lines), encoding="utf-8"
        )

    report = build_report(
        source_dir=args.enex_dir,
        output_dir=output_dir,
        run_started=run_started,
        run_finished=run_finished,
        yarle_version=args.yarle_version,
        invocation_failures=invocation_failures,
    )
    write_reports(report, output_dir=output_dir)

    write_marker(
        output_dir,
        MarkerInfo(
            tool="evernote-exporter",
            tool_version=__version__,
            yarle_version=args.yarle_version,
            created_at=run_started,
            source_dir=str(args.enex_dir),
        ),
    )

    # Cleanup: drop the template file (it lives in vault, but is internal)
    try:
        template_file.unlink()
    except OSError:
        pass

    code = report.exit_code()
    print()
    print(f"Migration complete. Report: {output_dir / 'migration-report.txt'}")
    print(f"Exit code: {code}")
    return code
