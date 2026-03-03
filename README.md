# Disk Recovery Orchestrator (Open Workflow)

This tool is designed to reduce risk when recovering from a damaged drive:

1. define source (damaged disk) + destination (healthy disk),
2. clone source first,
3. run checks on the clone only,
4. recover files from mounted clone,
5. produce a report with counts and sample tree paths.

## Script

- `recovery_tool.py`

## Safety model

- The source is treated as **read-only input** by clone commands (`ddrescue`/`dd`).
- Filesystem checks are run against `clone.img`, not the original source.
- `--dry-run` does not execute clone/check commands.
- `--show-commands` prints exactly what would run (or is running).

> Important: this script cannot protect against user mistakes like choosing the wrong source path. Always verify disk identifiers before running.

## Requirements

- Python 3.9+
- Recommended: `ddrescue`
- Optional: filesystem checker tools (`fsck_apfs` on macOS, `fsck` on Linux)

---

## What commands are used under the hood?

Clone stage:
- Preferred:
  - `ddrescue -f -n <source> <clone.img> <clone.map>`
  - `ddrescue -d -r<retries> <source> <clone.img> <clone.map>`
- Fallback when `ddrescue` is unavailable:
  - `dd if=<source> of=<clone.img> bs=<block-size> conv=noerror,sync status=progress`

Check stage (clone only):
- macOS APFS: `fsck_apfs -n <clone.img>`
- Other systems fallback: `fsck -N <clone.img>`

Use `--show-commands` to print these commands at runtime.

---

## Modes

### 1) Full mode (default)
Runs clone + check (+ optional extraction if `--mount-source` is given).

### 2) Extract-only mode
Skips clone/check and only copies recoverable files from `--mount-source` into `recovered_files/` with per-file error logging.

---

## How to test safely (recommended first)

### A. Dry run (no clone/check execution)

```bash
python3 recovery_tool.py \
  --mode full \
  --source /dev/disk6 \
  --destination /Volumes/RecoveryDrive \
  --session-name wd_case_plan \
  --dry-run \
  --show-commands
```

What to verify:
- printed command lines look correct,
- `recovery_report.json` exists,
- `stderr` fields in report say `DRY_RUN: command not executed`.

### B. Functional test without touching a real disk

1) create sample files,
2) run extract-only,
3) confirm copied files + hashes + report counts.

```bash
mkdir -p /tmp/recovery_demo/src/photos
printf 'a' > /tmp/recovery_demo/src/doc.txt
printf 'b' > /tmp/recovery_demo/src/photos/img.jpg

python3 recovery_tool.py \
  --mode extract-only \
  --destination /tmp/recovery_demo/out \
  --session-name extract_test \
  --mount-source /tmp/recovery_demo/src \
  --with-hashes
```

### C. Real run (after verifying identifiers)

```bash
python3 recovery_tool.py \
  --mode full \
  --source /dev/disk6 \
  --destination /Volumes/RecoveryDrive \
  --session-name wd_case_real \
  --show-commands
```

---

## Typical recovery sequence on your case

1. run **dry run** first,
2. run full clone/check,
3. mount clone image read-only,
4. run extract-only with `--mount-source` pointed to mounted clone,
5. review `recovery_report.json`.

---

## Output

Each session folder contains:

- `clone.img` (when full mode is used)
- `clone.map` (when ddrescue is used)
- `recovered_files/` (when extraction runs)
- `recovery_report.json`

## Limitations

- Not a replacement for hardware/firmware lab recovery.
- If filesystem metadata is severely corrupted, folder names/structure may not be fully recoverable.
