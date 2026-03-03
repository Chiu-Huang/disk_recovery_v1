# Disk Recovery Orchestrator (Open Workflow)

This repository contains a practical, automation-first workflow that mirrors what professional recovery apps generally do at a high level:

1. Define damaged source drive + safe destination
2. Clone source to image (non-destructive, resumable when possible)
3. Run filesystem checks on clone only
4. If mountable, copy as many files as possible with per-file error tolerance
5. Emit a machine-readable report (JSON) with recovered tree/statistics

## Script

`recovery_tool.py`

## Requirements

- Python 3.9+
- Recommended: `ddrescue`
- Optional filesystem tools (`fsck_apfs` on macOS, `fsck` elsewhere)

## Usage

### Dry run (safe planning)

```bash
python3 recovery_tool.py \
  --source /dev/disk6 \
  --destination /Volumes/RecoveryDrive \
  --session-name wd_case_001 \
  --dry-run
```

### Actual clone + report

```bash
python3 recovery_tool.py \
  --source /dev/disk6 \
  --destination /Volumes/RecoveryDrive \
  --session-name wd_case_001
```

### Extraction from mounted clone/image

```bash
python3 recovery_tool.py \
  --source /dev/disk6 \
  --destination /Volumes/RecoveryDrive \
  --session-name wd_case_001_extract \
  --mount-source /Volumes/MountedClone \
  --with-hashes
```

## Output

Each run creates a session folder:

- `clone.img` (target image)
- `clone.map` (ddrescue map/log, when ddrescue is used)
- `recovered_files/` (if extraction performed)
- `recovery_report.json`

## Safety notes

- Never repair/write against original damaged device.
- Perform all checks/recovery on clone/image.
- Keep original disconnected after imaging.

## Limitations

This does not replace lab-grade firmware-level recovery for severe hardware failure.
