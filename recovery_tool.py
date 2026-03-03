#!/usr/bin/env python3
"""Disk recovery orchestrator.

This utility follows a conservative workflow used in data recovery:
1) Clone source block device to an image (ddrescue preferred, dd fallback)
2) Attempt non-destructive filesystem checks on cloned artifact
3) If mountable, copy files while preserving tree and tracking failures
4) Produce a JSON report with actions, outcomes, and recovered-tree summary

Note: This script orchestrates external tools; it does not replace full forensic suites.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


@dataclass
class CommandResult:
    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    ended_at: str


class RecoveryError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_cmd(cmd: List[str], dry_run: bool = False) -> CommandResult:
    started = utc_now()
    if dry_run:
        return CommandResult(cmd=cmd, returncode=0, stdout="", stderr="DRY_RUN", started_at=started, ended_at=utc_now())

    proc = subprocess.run(cmd, text=True, capture_output=True)
    return CommandResult(
        cmd=cmd,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        started_at=started,
        ended_at=utc_now(),
    )


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def copy_tree_with_report(src: Path, dst: Path, with_hashes: bool = False) -> dict:
    copied = []
    failed = []

    for root, _, files in os.walk(src):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        out_root = dst / rel
        out_root.mkdir(parents=True, exist_ok=True)

        for name in files:
            s = root_path / name
            d = out_root / name
            entry = {"src": str(s), "dst": str(d)}
            try:
                shutil.copy2(s, d)
                entry["size"] = d.stat().st_size
                if with_hashes:
                    entry["sha256"] = hash_file(d)
                copied.append(entry)
            except Exception as exc:  # broad by design for recovery workflows
                entry["error"] = str(exc)
                failed.append(entry)

    return {
        "copied": copied,
        "failed": failed,
        "copied_count": len(copied),
        "failed_count": len(failed),
    }


def tree_stats(root: Path) -> dict:
    total_files = 0
    total_dirs = 0
    total_bytes = 0
    sample_paths = []

    for current_root, dirs, files in os.walk(root):
        total_dirs += len(dirs)
        total_files += len(files)
        for f in files:
            fp = Path(current_root) / f
            try:
                total_bytes += fp.stat().st_size
            except OSError:
                pass
            if len(sample_paths) < 200:
                sample_paths.append(str(fp.relative_to(root)))

    return {
        "files": total_files,
        "directories": total_dirs,
        "bytes": total_bytes,
        "sample_paths": sample_paths,
    }


def attempt_fs_repair(target: Path, dry_run: bool) -> List[dict]:
    """Attempt non-destructive checks on clone/image only.

    We intentionally avoid force-write repair operations.
    """
    ops = []
    system = platform.system().lower()

    if system == "darwin" and command_exists("fsck_apfs"):
        res = run_cmd(["fsck_apfs", "-n", str(target)], dry_run=dry_run)
        ops.append({"tool": "fsck_apfs", **asdict(res)})
    elif command_exists("fsck"):
        res = run_cmd(["fsck", "-N", str(target)], dry_run=dry_run)
        ops.append({"tool": "fsck", **asdict(res)})
    else:
        ops.append({"tool": "none", "note": "No filesystem checker available"})

    return ops


def clone_source(source: str, image_path: Path, map_path: Path, block_size: str, retries: int, dry_run: bool) -> dict:
    if command_exists("ddrescue"):
        first_pass = run_cmd(["ddrescue", "-f", "-n", source, str(image_path), str(map_path)], dry_run=dry_run)
        retry_pass = run_cmd(["ddrescue", "-d", f"-r{retries}", source, str(image_path), str(map_path)], dry_run=dry_run)
        return {
            "tool": "ddrescue",
            "first_pass": asdict(first_pass),
            "retry_pass": asdict(retry_pass),
            "image": str(image_path),
            "map": str(map_path),
        }

    # fallback (less resilient)
    dd_cmd = ["dd", f"if={source}", f"of={image_path}", f"bs={block_size}", "conv=noerror,sync", "status=progress"]
    res = run_cmd(dd_cmd, dry_run=dry_run)
    return {
        "tool": "dd",
        "clone": asdict(res),
        "warning": "ddrescue not found; using dd fallback",
        "image": str(image_path),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Conservative disk recovery orchestrator")
    p.add_argument("--source", required=True, help="Damaged source block device (example: /dev/disk6)")
    p.add_argument("--destination", required=True, help="Destination directory or mounted recovery drive")
    p.add_argument("--mount-source", help="Mounted path to clone/image for file extraction stage")
    p.add_argument("--session-name", default=f"recovery_{int(time.time())}")
    p.add_argument("--block-size", default="64K")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--with-hashes", action="store_true", help="Compute SHA-256 for copied files")
    p.add_argument("--dry-run", action="store_true", help="Plan and log actions without executing tools")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    session_root = Path(args.destination).expanduser().resolve() / args.session_name
    session_root.mkdir(parents=True, exist_ok=True)

    image_path = session_root / "clone.img"
    map_path = session_root / "clone.map"
    extracted_dir = session_root / "recovered_files"
    report_path = session_root / "recovery_report.json"

    report = {
        "meta": {
            "started_at": utc_now(),
            "host": platform.node(),
            "platform": platform.platform(),
            "python": sys.version,
            "dry_run": args.dry_run,
        },
        "inputs": {
            "source": args.source,
            "destination": str(session_root),
            "mount_source": args.mount_source,
            "with_hashes": args.with_hashes,
        },
        "stages": {},
    }

    try:
        report["stages"]["clone"] = clone_source(
            source=args.source,
            image_path=image_path,
            map_path=map_path,
            block_size=args.block_size,
            retries=args.retries,
            dry_run=args.dry_run,
        )

        report["stages"]["repair_check"] = {
            "operations": attempt_fs_repair(image_path, dry_run=args.dry_run),
            "note": "Checks are performed only against cloned image",
        }

        if args.mount_source:
            src = Path(args.mount_source).expanduser().resolve()
            extracted_dir.mkdir(parents=True, exist_ok=True)
            recover_report = copy_tree_with_report(src, extracted_dir, with_hashes=args.with_hashes)
            report["stages"]["file_recovery"] = recover_report
            report["stages"]["recovered_tree"] = tree_stats(extracted_dir)
        else:
            report["stages"]["file_recovery"] = {
                "skipped": True,
                "reason": "No --mount-source provided. Mount clone/image read-only then rerun extraction stage.",
            }

    except Exception as exc:
        report["error"] = str(exc)
    finally:
        report["meta"]["ended_at"] = utc_now()
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Session folder: {session_root}")
    print(f"Report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
