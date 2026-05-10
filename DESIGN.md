# Evernote → Obsidian Exporter — Design

A personal one-shot tool to migrate an entire Evernote knowledge store into a subfolder of an existing Obsidian vault, preserving notebook hierarchy, metadata, attachments, and timestamps.

Personal use only. Not intended for distribution.

---

## 1. Scope

**In scope**
- One-shot migration of all Evernote notes + attachments into a designated subfolder of an existing Obsidian vault.
- Preserves Evernote's Stack → Notebook → Note hierarchy as folders.
- Preserves creation/modification timestamps (in YAML frontmatter and on the filesystem).
- Preserves Evernote tags as Obsidian YAML tags.
- Aggressive cleanup of web clip HTML.
- Re-runnable: subsequent runs wipe and regenerate the export subfolder safely.

**Out of scope**
- Ongoing sync (Evernote → Obsidian as source of truth).
- Decryption of encrypted ENML blocks (`<en-crypt>`).
- Reminder/task fidelity (Evernote's task model differs from Obsidian's).
- Distribution as a packaged tool (no PyPI, no CI, no GitHub Actions).
- Mutating anything outside the designated export subfolder of the user's vault.

---

## 2. Pipeline

Two stages. Stage 1 is an existing tool the user runs manually. Stage 2 is what we build.

```
[Evernote cloud]
      │
      ▼  Stage 1: evernote-backup (existing tool, pipx-installed)
      │  init-db → sync → export
      ▼
[<enex-dir>/<Stack>/<Notebook>.enex]
[<enex-dir>/<Notebook>.enex]                  (notebooks not in any stack)
      │
      ▼  Stage 2: our tool (Python)
      │  preflight → prompt → wipe → orchestrate Yarle invocations →
      │  verify → write reports + marker file
      ▼
[<vault>/<root-folder>/<Stack>/<Notebook>/<Note>.md + _attachments/]
```

### Stage 1: ENEX acquisition (manual, one-time)

Documented in `README.md`. The user runs:

```bash
sudo apt install nodejs npm pipx
pipx install evernote-backup
evernote-backup init-db          # OAuth in browser
evernote-backup sync             # downloads to local SQLite
evernote-backup export ./enex-output/
```

`evernote-backup` preserves the Stack → Notebook hierarchy: stack subfolders contain ENEX files, and notebooks not in a stack land at the root (verified in source: `parent_dir = [notebook.stack] if notebook.stack else []`).

### Stage 2: Conversion (this tool)

Wraps Yarle (TypeScript ENEX→Markdown converter, ~1.7k stars, actively maintained, native Obsidian target). Yarle is invoked as a subprocess via `npx`, with a pinned version for reproducibility.

---

## 3. CLI

Single command, flags only — no subcommands.

```
python -m evernote_exporter \
  --enex-dir <PATH>                # required: stage 1 output dir
  --vault <PATH>                   # required: existing Obsidian vault root
  --root-folder <NAME>             # required: subfolder name within vault (e.g. "Evernote")
  [--yes]                          # skip confirmation prompt
  [--dry-run]                      # validate + plan + exit, no destructive ops
  [--verbose]                      # debug logging
  [--yarle-version <VERSION>]      # override pinned Yarle version
  [--no-vault-check]               # skip the .obsidian/ existence check
```

Exit codes:
- `0` — success, all sanity checks passed
- `1` — preflight failure or user declined prompt
- `2` — Yarle subprocess failure (one or more invocations exited non-zero)
- `3` — verification failure (counts mismatch, missing frontmatter, etc.)

---

## 4. Repo Layout

```
evernote-exporter/
├── README.md                       # user-facing docs
├── DESIGN.md                       # this file
├── pyproject.toml                  # dev deps only (pytest); not for distribution
├── src/evernote_exporter/
│   ├── __init__.py
│   ├── __main__.py                 # `python -m evernote_exporter`
│   ├── cli.py                      # argparse, prompt, top-level orchestration
│   ├── safety.py                   # marker file, vault checks
│   ├── preflight.py                # node/npx/yarle/path/writability checks
│   ├── orchestrator.py             # discovers stacks, runs Yarle per stack
│   ├── yarle_config.py             # builds config dict per invocation
│   ├── enex_parser.py              # stdlib xml.etree, count notes/resources
│   └── reporter.py                 # text + JSON migration reports
└── tests/
    ├── fixtures/                   # 7 hand-crafted ENEX files
    ├── golden/                     # expected output for E2E
    ├── build_fixtures.py
    ├── test_safety.py
    ├── test_preflight.py
    ├── test_orchestrator.py        # mocks subprocess
    ├── test_yarle_config.py
    ├── test_enex_parser.py
    ├── test_reporter.py
    └── test_e2e.py                 # real Yarle, runs by default
```

**Dependencies**
- Runtime: Python stdlib only (no `requirements.txt`).
- Dev: `pytest` only, declared in `pyproject.toml [project.optional-dependencies]`.
- External (user-installed): Node.js + npx; Yarle (auto-fetched by npx on first run, cached thereafter).

---

## 5. Preflight Checks

All checks run before any destructive operation. Each failure produces a clear, actionable message.

| # | Check | Failure message |
|---|---|---|
| 1 | `node` and `npx` on PATH | `Install Node.js: sudo apt install nodejs npm` |
| 2 | `npx -p yarle-evernote-to-md@<pinned> yarle --version` succeeds | First run downloads Yarle; if it fails, suggest checking network/permissions |
| 3 | `--enex-dir` exists and contains ≥1 `.enex` file (recursively) | `No ENEX files found in <dir>. Did you run evernote-backup export?` |
| 4 | `--vault` exists and is a directory | Generic helpful message |
| 5 | `<vault>/.obsidian/` exists (skipped with `--no-vault-check`) | `<vault> doesn't look like an Obsidian vault (no .obsidian/). Use --no-vault-check to override.` |
| 6 | `<vault>/<root-folder>/` either doesn't exist OR contains `.evernote-export-marker` | `Folder exists but lacks marker file. Aborting to protect your data. Remove or rename it manually.` |
| 7 | Output dir is writable (test creating + deleting a tempfile in parent) | Generic permissions message |

`--dry-run` runs preflight, prints the plan (which stacks, how many ENEX files, target paths), and exits 0 without prompting or executing.

---

## 6. Orchestration Logic

Yarle does not recurse subdirectories of `enexSources` (verified in source: `dropTheRopeRunner.ts` reads only top-level `.enex` files). To handle the Stack → Notebook hierarchy, we invoke Yarle once per stack subdirectory plus once for any root-level ENEX files.

```python
# Pseudocode
def orchestrate(enex_dir, output_root, yarle_version):
    invocations = []

    # One invocation per stack subdirectory
    for stack_dir in enex_dir.iterdir():
        if stack_dir.is_dir() and any(stack_dir.glob("*.enex")):
            invocations.append(YarleInvocation(
                enex_sources=[stack_dir],
                output_dir=output_root / stack_dir.name,
                stack_name=stack_dir.name,
            ))

    # One invocation for root-level ENEX files (notebooks without a stack)
    root_enex = list(enex_dir.glob("*.enex"))
    if root_enex:
        invocations.append(YarleInvocation(
            enex_sources=[enex_dir],
            output_dir=output_root,
            stack_name=None,
        ))

    results = []
    for inv in invocations:
        config_path = write_yarle_config_to_tempfile(inv, yarle_version)
        result = subprocess.run(
            ["npx", "-p", f"yarle-evernote-to-md@{yarle_version}",
             "yarle", "--configFile", str(config_path)],
            capture_output=True, text=True,
        )
        results.append(result)
    return results
```

For typical scale (10-30 stacks), Yarle invocation overhead is ~1s each after the first cached install. Total runtime is dominated by Yarle's per-note conversion work, not orchestration overhead.

---

## 7. Yarle Configuration

Per-invocation config dict, written to a temp file before each Yarle call. Keys derived directly from design decisions.

```jsonc
{
  "enexSources": ["<set per invocation>"],
  "outputDir": "<set per invocation>",
  "outputFormat": "OBSIDIAN_MD",

  // Hierarchy and resources
  "isNotebookNameNeeded": true,        // each notebook gets its own folder
  "haveEnexLevelResources": true,      // per-notebook _attachments folder
  "resourcesDir": "_attachments",

  // Metadata
  "isMetadataNeeded": true,
  "skipAuthor": true,
  "skipLocation": true,
  "skipPlaceName": true,
  "skipReminderTime": true,
  "skipReminderOrder": true,
  "skipReminderDoneTime": true,
  "skipApplicationData": true,
  "skipContentClass": true,
  "dateFormat": "YYYY-MM-DDTHH:mm:ssZ",

  // Tags
  "useHashTags": false,                // YAML array, not inline #tags
  "replaceWhitespacesInTagsByUnderscore": false,  // we use hyphens via nestedTags
  "nestedTags": { "separatorInEN": "/", "replaceSeparatorWith": "/" },

  // Filename and content sanitization
  "keepMDCharactersOfENNotes": false,  // aggressive sanitize (replace forbidden chars)
  "replacementChar": "-",              // forbidden chars + spaces → "-"
  "sanitizeResourceNameSpaces": true,
  "useUniqueUnknownFileNames": true,

  // Web clips
  "skipWebClips": false,               // we want them
  "keepOriginalHtml": false,           // aggressive cleanup of clip HTML

  // Code blocks
  "monospaceIsCodeBlock": true,        // ``` fences

  // Internal links (rare, low priority)
  "obsidianSettings": { "omitLinkDisplayName": false },
  "addExtensionToInternalLinks": false,
  "keepEvernoteLinkIfNoNoteFound": false  // drop unresolved internal links
}
```

A custom Markdown template (Yarle's `templateFile` option) controls frontmatter shape. Template:

```markdown
---
created: {creation-date}
updated: {update-date}
{tags-list-with-prefix:tags: }
{source-url-with-prefix:source: }
---

{title}

{content}
```

Yarle's template syntax: `{...}` is a placeholder; `{...-with-prefix:foo}` means "render only if non-empty, prefixed with foo". Notebook/stack are intentionally omitted from frontmatter (they're encoded by folder location); the user can add them later if Dataview queries demand it.

---

## 8. Output Structure

```
<vault>/<root-folder>/
├── .evernote-export-marker          # JSON: timestamp, source, tool version, yarle version
├── migration-report.txt             # human-readable summary
├── migration-report.json            # machine-readable for future scripting
├── migration-errors.log             # captured Yarle stderr
├── <Stack>/
│   └── <Notebook>/
│       ├── _attachments/
│       │   ├── photo.jpg
│       │   └── doc.pdf
│       ├── <Note-Title>.md
│       └── <Other-Note>.md
└── <Notebook>/                      # for notebooks not in any stack
    └── <Note-Title>.md
```

### Note format

```markdown
---
created: 2018-04-05T10:23:00Z
updated: 2024-11-30T19:12:00Z
tags: [recipe, pasta, dinner]
source: https://example.com/recipe
---

# Original Note Title

Note body. Inline image: ![](./_attachments/photo.jpg)

```python
example_code()
```

Linked note: [[Other Note Title]]
```

- Filesystem mtime/ctime restored to Evernote `updated`/`created` (Yarle handles this when `dateFormat` is set).
- Attachments use **standard markdown** with explicit relative paths (`![](./_attachments/foo.jpg)`) — settings-agnostic.
- Inter-note links use **Obsidian wikilinks** (`[[Note Title]]`) — first-class for graph view and backlinks. Yarle resolves these from `evernote:///` URIs at conversion time. Unresolvable links are dropped (`keepEvernoteLinkIfNoNoteFound: false`).

---

## 9. Filename and Tag Rules

### Filenames

Yarle handles all of these via its built-in sanitization:

| Rule | Implementation |
|---|---|
| Replace forbidden chars (`/ \ : * ? " < > \|`) with `-` | `replacementChar: "-"` |
| Replace spaces with `-` | `replacementChar: "-"` (Yarle treats spaces as replaceable) |
| Preserve accented characters (e.g., `café`) | Default — modern Linux ext4 handles unicode fine |
| Preserve emoji | Default |
| Length cap | Yarle's default behavior (varies; should not exceed 255 bytes on ext4) |
| Same-title collisions in same notebook | Numeric suffix: `Note.md`, `Note-1.md`, `Note-2.md` |
| Empty titles | Yarle's default placeholder (typically `untitled` or similar) |

### Tags

| Rule | Implementation |
|---|---|
| YAML array, not inline `#tags` | `useHashTags: false` + template emits `tags: [...]` |
| Spaces in tags → `-` | Template-level transform during config generation; or `replaceWhitespacesInTagsByUnderscore: false` plus a custom replacement |
| Preserve `/` for nested tags | `nestedTags: { separatorInEN: "/", replaceSeparatorWith: "/" }` |
| Strip other punctuation (`:`, `&`, etc.) | Yarle's default tag sanitization |

---

## 10. Idempotency and Safety

### Marker file

`<vault>/<root-folder>/.evernote-export-marker` (JSON):

```json
{
  "tool": "evernote-exporter",
  "tool_version": "0.1.0",
  "yarle_version": "7.4.2",
  "created_at": "2026-05-06T14:30:22Z",
  "source_dir": "/home/dns/enex-output"
}
```

### Re-run behavior

1. Preflight check 6 verifies marker is present (or folder doesn't exist).
2. Confirmation prompt:
   ```
   This will create or replace: /home/dns/Vault/Evernote/
   Source: ./enex-output (4 stacks, 23 ENEX files, ~1247 notes)
   Continue? [y/N]
   ```
3. If confirmed (or `--yes`): `shutil.rmtree(<vault>/<root>/)`, recreate, run Yarle, write reports + marker.
4. Never touches anything outside `<vault>/<root>/`.

### Vault safety invariants

- Never write outside `<vault>/<root>/`.
- Never delete `<vault>/<root>/` without seeing the marker (unless folder doesn't exist).
- Never delete `.obsidian/` — preflight check 5 ensures we recognize the vault but never touches it.

---

## 11. Verification and Reports

After all Yarle invocations complete, the runner performs sanity checks and writes three artifacts.

### Sanity checks

| # | Check | Action on mismatch |
|---|---|---|
| 1 | ENEX file count = output notebook folder count | Log per-notebook breakdown of which ENEX files have/lack output folders; exit 3 |
| 2 | Note count: `<note>` tags in ENEX = `.md` files in output | List which notebooks have count mismatches; exit 3 unless within tolerance |
| 3 | Attachment count: `<resource>` tags in ENEX = files in `_attachments/` | List per-notebook deltas; exit 3 if total mismatch |
| 4 | Per-note byte-size sanity | Flag (but don't fail) notes with `.md` < 100 chars when ENEX node was > 5 KB |
| 5 | Frontmatter present on every `.md` (starts with `---`) | List violators; exit 3 |
| 6 | Yarle stderr captured | Append all per-invocation stderr to `migration-errors.log` |

ENEX parsing for these checks uses stdlib `xml.etree.ElementTree`. Counts only — no full content parse.

### `migration-report.txt` (sample)

```
Evernote → Obsidian migration report
====================================
Source:        /home/dns/enex-output (23 ENEX files across 4 stacks + 0 root)
Output:        /home/dns/Vault/Evernote
Run:           2026-05-06T14:30:22Z
Yarle version: 7.4.2
Duration:      4m 17s

Stacks:        4
Notebooks:     23 (23/23 ENEX → output folders OK)
Notes:         1,247 in / 1,247 out (OK)
Attachments:   412 in / 412 out (OK)
Frontmatter:   1,247/1,247 valid (OK)

Anomalies:     3 short notes (output <100 chars from input >5KB)
                 - Work/Meetings/Standup-2024-03-12.md (input 8KB → output 47 chars)
                 - Personal/Recipes/Pasta.md         (input 5KB → output 89 chars)
                 - ...
Yarle errors:  0

Result: SUCCESS (exit 0)
```

### `migration-report.json`

Same data, structured. Schema:
```jsonc
{
  "source_dir": "...",
  "output_dir": "...",
  "run_started": "...",
  "run_finished": "...",
  "yarle_version": "...",
  "stacks": [
    { "name": "Work", "notebooks": [
      { "name": "Meetings", "notes_in": 42, "notes_out": 42, "attachments_in": 12, "attachments_out": 12 }
    ]}
  ],
  "totals": { "notebooks_in": 23, "notebooks_out": 23, "notes_in": 1247, ... },
  "anomalies": [...],
  "yarle_errors": [...],
  "exit_code": 0
}
```

### `migration-errors.log`

Captured stderr from each Yarle invocation, prefixed with stack name. Mostly empty in healthy runs.

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| Preflight check fails | Exit 1 with specific message. Nothing written. |
| User declines prompt | Exit 1. Nothing written. |
| One Yarle invocation (one stack) fails | Continue with remaining invocations. Capture stderr. Final exit code = 2. Report lists which stack failed. |
| All Yarle invocations fail | Exit 2. Output dir may be partially populated; not auto-cleaned (user can inspect). |
| Sanity check fails post-Yarle | Exit 3. Output and reports preserved for diagnosis. |
| Unexpected Python exception | Exit 1 with traceback (verbose mode) or summary (default). Output dir state undefined. |
| Output dir not writable mid-run | Exit 1. State undefined. |

The runner is **not** transactional. A failed run can leave a partial export. The marker file is written **only** on full success — so a partial run looks "unowned" and a re-run will be refused unless the user manually clears the partial state.

This is intentional. For a one-shot personal migration, the user inspecting failure state by hand is more useful than auto-cleanup.

---

## 13. Testing Strategy

Three layers, all run by default in `pytest`:

### Unit tests
- `test_safety.py` — marker file read/write, missing-marker refusal logic
- `test_preflight.py` — each check independently, mocking Path/subprocess
- `test_yarle_config.py` — config dict generation, template substitution, per-invocation values
- `test_enex_parser.py` — count `<note>` and `<resource>` from fixture ENEX files
- `test_reporter.py` — text + JSON report formatting
- `test_orchestrator.py` — stack discovery; subprocess.run mocked

### E2E tests
- `test_e2e.py` — run real Yarle against fixture ENEX files; assert output matches `tests/golden/`. Updates require `pytest --update-goldens` flag (not a built-in pytest flag — implement via env var or custom option).

### Fixtures (`tests/fixtures/`, ~30 KB total, hand-crafted ENEX XML)

| File | Purpose |
|---|---|
| `simple.enex` | 1 plain note, baseline |
| `with-attachment.enex` | 1 note + base64-embedded PNG resource |
| `web-clip.enex` | Note with messy inline-styled HTML |
| `tag-edge-cases.enex` | Tags with spaces, slashes, unicode |
| `filename-edge-cases.enex` | Titles with `/`, accents, duplicates, very long, empty |
| `code-block.enex` | `<pre>` and styled monospace divs |
| `multi-note.enex` | 10 notes for count-verification |

`tests/build_fixtures.py` generates all fixtures deterministically. Generated `.enex` files are committed to the repo so tests run without first generating.

### Coverage target
80%+ on `src/` excluding `cli.py`'s `main()` glue (boilerplate), per CLAUDE.md.

### CI
None. This is a personal one-shot tool.

---

## 14. README Outline

The repo's `README.md` (separate from this design doc) covers:

1. **What this tool does** — one paragraph.
2. **Prerequisites** — Ubuntu 24.04, Python 3.10+, Node.js (`sudo apt install nodejs npm`), pipx.
3. **Stage 1: ENEX acquisition** — link to [`evernote-backup`](https://github.com/vzhd1701/evernote-backup), condensed `init-db` → `sync` → `export` commands, with note that hierarchy (stacks) is preserved by `evernote-backup`.
4. **Stage 2: Conversion** — clone this repo, run `python -m evernote_exporter ...` with example invocation.
5. **CLI reference** — auto-generated from `argparse --help`.
6. **Output structure** — example tree.
7. **Limitations** — encrypted notes (decrypt in Evernote first), complex tables (best-effort), audio playback (works in Obsidian if links resolve), inter-note links may not resolve in 100% of cases.
8. **Troubleshooting** — common Yarle errors, network issues fetching Yarle, vault check overrides.

---

## 15. Decision Log (the "why" behind choices)

| Decision | Why |
|---|---|
| Two-stage pipeline (`evernote-backup` → our tool) | Avoids reinventing Evernote API auth/sync. `evernote-backup` is battle-tested and preserves stack hierarchy. |
| Wrap Yarle (don't build ENEX→MD ourselves) | Yarle has years of edge-case handling (web clips, malformed entities, etc.). Building from scratch is high-risk for low value. |
| Python (stdlib only) | Same ecosystem as `evernote-backup`. Simple subprocess orchestration. CLAUDE.md test coverage achievable with pytest. No runtime deps to manage. |
| Mirror Stack/Notebook layout (option B from Q3) | User thinks in folders. Matches existing mental model. Per-notebook `_attachments/` is the right scope. |
| Standard markdown for attachments, wikilinks for notes | Settings-agnostic for attachments; first-class graph/backlinks for notes. |
| Pin Yarle version | Reproducible. Migration runs months apart produce identical output. |
| Wipe + rewrite with marker file | Predictable re-runs. Marker file prevents catastrophe on user typo. |
| Numeric suffix for filename collisions | Yarle's default; date suffix would require post-processing with link updates (real risk of breakage). Personal use → numeric is fine. |
| Preserve accents and emoji in filenames | Modern Linux ext4 handles unicode. Avoids transliteration character-map maintenance burden. |
| No CI, no PyPI | Personal tool, may not even be published. Local pytest is enough. |
| One Yarle invocation per stack | Yarle doesn't recurse subdirectories. Per-stack invocation is the simplest correct approach. ~1s overhead per stack is acceptable. |
| YAML tags only (no inline) | Cleaner notes, Dataview-native. Inline can be added later by hand if desired. |
| Notebook/Stack NOT in frontmatter (by default) | Redundant with folder location. Keeps frontmatter minimal. Easy to add later if Dataview queries need them. |
| Reports as text + JSON sidecar | Human and machine readable. Cheap to write both. |
| Hours-acceptable runtime | No premature optimization. User confirmed this. |

---

## 16. Open Implementation Questions (defer to coding time)

These were left unresolved in design because they're best answered during implementation against real fixtures or the user's actual ENEX files:

1. **Exact behavior of Yarle's `keepMDCharactersOfENNotes: false`** — does it strip emoji from filenames? E2E tests against fixtures will reveal.
2. **Yarle's empty-title handling** — verify the placeholder it uses; document in README.
3. **Tag sanitization granularity** — Yarle has multiple tag-related options (`useHashTags`, `replaceWhitespacesInTagsByUnderscore`, `removeUnicodeCharsFromTags`). Final config requires testing against `tag-edge-cases.enex`.
4. **Internal-link resolution rate** — for cross-notebook references, Yarle's resolution may fail. Track via verification step; document expectations.
5. **Per-note byte-size threshold** — initial pick: flag notes where output <100 chars and input >5 KB. Tune after first real run.
6. **Yarle template syntax exact form** — verify against Yarle's `Templates.md` doc during implementation.

---

## 17. Implementation Order (suggested)

1. `enex_parser.py` + `test_enex_parser.py` — count notes/resources from ENEX. No external deps.
2. `safety.py` + `test_safety.py` — marker file logic.
3. `preflight.py` + `test_preflight.py` — all checks, mocking subprocess and filesystem.
4. `yarle_config.py` + `test_yarle_config.py` — config dict and template generation.
5. `tests/build_fixtures.py` — generate fixtures.
6. `orchestrator.py` + `test_orchestrator.py` — stack discovery, mocked subprocess.
7. `reporter.py` + `test_reporter.py` — counts diff, text/JSON reports.
8. `cli.py` + `__main__.py` — argparse, prompt, top-level orchestration.
9. `test_e2e.py` — real Yarle against fixtures, golden snapshots.
10. `README.md` — user-facing docs.

Each step ships green tests before moving on.
