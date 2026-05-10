# evernote-exporter

A personal one-shot tool to migrate an entire Evernote knowledge store into a subfolder of an existing Obsidian vault. Preserves Stack → Notebook hierarchy, attachments, tags, source URLs, and creation/modification timestamps.

Wraps [Yarle](https://github.com/akosbalasko/yarle) for the ENML → Markdown conversion and orchestrates it per stack so the vault layout matches the Evernote organisation.

Personal use. Not packaged for distribution.

---

## Requirements

- Ubuntu 24.04 (or any Linux with Python 3.10+ and Node.js)
- Python 3.10 or newer
- Node.js + npm: `sudo apt install nodejs npm`
- pipx (for the prerequisite tool): `sudo apt install pipx`
- An existing Obsidian vault to import into

The tool itself has zero Python runtime dependencies. Only `pytest` is needed for tests.

---

## Stage 1: Get your notes out of Evernote (one-time)

This stage is handled by [`evernote-backup`](https://github.com/vzhd1701/evernote-backup), an excellent existing tool. It logs in to Evernote (OAuth in your browser), downloads everything to a local SQLite database, and then exports per-notebook ENEX files preserving stacks as subdirectories.

### 1.1 Install

```bash
pipx install evernote-backup
```

### 1.2 Authenticate

Pick a working directory for the backup (this is where the SQLite DB and the ENEX files will land):

```bash
mkdir -p ~/evernote-export
cd ~/evernote-export

evernote-backup init-db
```

`init-db` will open your default browser for Evernote's OAuth flow. Log in normally and approve the request. The tool returns to the terminal once authorised and creates `en_backup.db` in the current directory. (For Yinxiang / 印象笔记, see the evernote-backup README for the `--backend china` flag.)

### 1.3 Download everything

```bash
evernote-backup sync
```

This downloads every note and attachment into the local SQLite database via the Evernote Cloud API. **For a large library this can take hours** — Evernote's API has per-minute rate limits. The tool shows a progress bar.

Sync is **resumable**: if it stops (network drops, you Ctrl-C, your laptop sleeps), just run `evernote-backup sync` again and it continues from where it left off.

### 1.4 Export to ENEX files

```bash
evernote-backup export ./evernote-backup-output/
```

This is offline — it just reads the SQLite DB and writes ENEX files. Fast.

### 1.5 Verify

Spot-check that the export looks right before going to stage 2:

```bash
# Should be a non-zero number — one .enex per notebook
find ./evernote-backup-output -name '*.enex' | wc -l

# Should mirror your Evernote stacks
ls ./evernote-backup-output/
```

The directory shape should look like:

```
evernote-backup-output/
├── Work/                    # stack
│   ├── Meetings.enex        # notebook in stack
│   └── Projects.enex
├── Personal/                # stack
│   └── Recipes.enex
└── Inbox.enex               # notebook NOT in any stack
```

You only need to run stage 1 once. Later, if you want refreshed state, re-run `evernote-backup sync` (incremental — only new changes) and then `evernote-backup export` (always full re-export).

---

## Stage 2: Convert into your Obsidian vault

### 2.1 Get the tool

```bash
git clone <this repo>
cd evernote-exporter
```

No install step — the tool runs as `python3 -m evernote_exporter` directly from the repo. Runtime dependencies are stdlib only.

### 2.2 Dry run first

Before doing anything destructive, validate the inputs:

```bash
python3 -m evernote_exporter \
  --enex-dir ~/evernote-export/evernote-backup-output \
  --vault   /path/to/your/Obsidian/Vault \
  --root-folder Evernote \
  --dry-run
```

This runs all preflight checks and prints what *would* happen without touching anything. Fix any reported issues before continuing.

### 2.3 Run for real

```bash
python3 -m evernote_exporter \
  --enex-dir ~/evernote-export/evernote-backup-output \
  --vault   /path/to/your/Obsidian/Vault \
  --root-folder Evernote
```

You'll see a confirmation prompt; type `y` to proceed.

**First run downloads Yarle** into `~/.cache/evernote-exporter/yarle-<version>/` (one-time, ~100 MB). Subsequent runs reuse it. After Yarle is cached, the conversion itself is fast — typically minutes for thousands of notes.

### 2.4 Verify

When the tool exits, check the report:

```bash
cat /path/to/your/Obsidian/Vault/Evernote/migration-report.txt
```

It will show counts in vs. out per notebook. Exit code 0 + "Result: SUCCESS" means everything matched.

### 2.5 Open in Obsidian

Open your vault in Obsidian. The `Evernote/` folder will appear in the file explorer. Obsidian may take a few seconds to index the new files the first time.

If you use **Dataview** and want to query by notebook/stack later, you can re-run the tool with a custom config — see DESIGN.md §15 for the rationale on why notebook/stack are folder-based by default and not in frontmatter.

### CLI flags

| Flag | Required | Default | Purpose |
|---|---|---|---|
| `--enex-dir <path>` | yes | — | Stage 1 output directory |
| `--vault <path>` | yes | — | Existing Obsidian vault root |
| `--root-folder <name>` | yes | — | Subfolder name to create inside the vault (e.g. `Evernote`) |
| `--yes` | no | off | Skip the confirmation prompt |
| `--dry-run` | no | off | Validate inputs and print plan, then exit |
| `--verbose` | no | off | Verbose logging |
| `--no-vault-check` | no | off | Skip the `.obsidian/` directory check |
| `--yarle-version <ver>` | no | `6.17.0` | Override the pinned Yarle version |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success — all sanity checks passed |
| 1 | Preflight failure or user declined the prompt |
| 2 | One or more Yarle invocations exited non-zero |
| 3 | Verification failure (counts mismatch, missing frontmatter, etc.) |

---

## Output structure

```
<vault>/
├── .obsidian/                          # untouched
├── (your existing folders)             # untouched
└── Evernote/
    ├── .evernote-export-marker         # JSON: timestamp, source, versions
    ├── migration-report.txt            # human-readable summary
    ├── migration-report.json           # machine-readable
    ├── migration-errors.log            # captured Yarle stderr (often empty)
    ├── Work/                           # stack
    │   └── Meetings/                   # notebook
    │       ├── _attachments/
    │       │   └── photo.jpg
    │       ├── 2024-Q1-planning.md
    │       └── Standup-notes.md
    └── Inbox/                          # notebook without a stack
        └── Note-1.md
```

A converted note looks like:

```markdown
---
created: 2018-04-05T10:23:00Z
updated: 2024-11-30T19:12:00Z
tags: ["recipe","pasta"]
source: https://example.com/recipe
---

# Original Note Title

Note body. Inline image: ![](./_attachments/photo.jpg)

Linked note: [[Other Note Title]]
```

- File mtime/ctime are restored to the Evernote `updated`/`created` values.
- Attachments use standard markdown links with explicit relative paths, so they work regardless of your Obsidian attachment settings.
- Note-to-note links (when present in Evernote) become Obsidian wikilinks.
- `notebook` and `stack` are intentionally NOT in the frontmatter — they are encoded by folder location. Add them later if you want Dataview queries.

---

## Re-running

A re-run wipes `<vault>/<root-folder>/` and regenerates from scratch. The marker file (`.evernote-export-marker`) is the safety mechanism: the tool refuses to delete a directory it doesn't recognise as one it created.

If you point at a folder that exists but has no marker (e.g., a typo, or you renamed something), the run aborts before any destructive operation. Remove or rename the folder by hand and try again.

---

## Limitations

- **Encrypted notes** (Evernote's `<en-crypt>` blocks) cannot be decrypted by Yarle. Decrypt them in Evernote first, then re-export.
- **Complex tables** (with merged cells, nested elements, or row/column styling) lose structure — Markdown tables are basic.
- **Web clip fidelity**: aggressive HTML cleanup is enabled by default. Inline styles, fonts, and colours from the original page are stripped. Text and structure remain.
- **Language hints in code blocks**: Evernote does not store them, so converted code blocks are generic ` ``` ` fences.
- **Filename collisions** (two notes with the same title in the same notebook) are resolved with a numeric suffix: `Note.md`, `Note-1.md`, `Note-2.md`.
- **Filenames preserve accents and emoji**. Modern Linux filesystems handle Unicode fine. If you sync the vault to something stricter (some mobile apps, certain cloud providers), rename them by hand.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `node not found on PATH` | `sudo apt install nodejs npm` |
| `yarle-evernote-to-md@X not found on npm registry` | Wrong `--yarle-version`. Default is `6.17.0`; available versions: `npm view yarle-evernote-to-md versions` |
| `<vault> doesn't look like an Obsidian vault` | Use `--no-vault-check` to override, or point at a real vault root |
| `<dir> exists but lacks marker file` | Either you've pointed at a folder you don't want overwritten, or a previous run failed mid-way. Delete or rename the folder to proceed |
| `npm install` hangs on first run | First-run install is ~100 MB and can be slow. Subsequent runs use the cached copy |
| Yarle emits `npx` hang | Known: Yarle's bin script has a multi-arg shebang that Linux mishandles. This tool bypasses it — it runs `node <script.js>` directly |

---

## Development

```bash
# Run all tests (unit + integration + E2E against real Yarle)
pytest

# Run only fast tests (no Yarle install)
pytest --ignore=tests/test_e2e.py

# Regenerate fixture ENEX files
python3 tests/build_fixtures.py
```

The full suite runs in ~2 seconds for unit/integration; ~7 seconds adding E2E (after first Yarle install).

---

## See also

- `DESIGN.md` — full design with decision log and the rationale behind every config choice.
- [`evernote-backup`](https://github.com/vzhd1701/evernote-backup) — stage 1 prerequisite.
- [Yarle](https://github.com/akosbalasko/yarle) — the underlying ENML → Markdown converter.
