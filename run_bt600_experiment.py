#!/usr/bin/env python3
"""Collect baseline, memory-read, and stock-patch results in one Terminal run.

Writes timestamped text and JSON results next to this script in results/.
The stock upload is the ordinary host-loaded driver patch. No persistent
flash write, kernel-driver change, or OS configuration change is performed.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", help="Collect the baseline and memory queries without uploading the stock patch")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = root / "results"
    output.mkdir(exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    transcript = output / f"bt600-{run_id}.txt"
    summary = output / f"bt600-{run_id}.json"
    report = {"started_utc": run_id, "read_only": args.read_only, "phases": [], "stock_running": False, "memory_read_supported": False}
    phases = [("baseline", []), ("memory_before", ["--probe-memory"])]
    if not args.read_only:
        phases += [("stock_upload", ["--load-stock"]), ("after_upload", []), ("memory_after", ["--probe-memory"])]
    exit_code = 0
    with transcript.open("x") as log:
        def emit(text):
            print(text, flush=True)
            log.write(text + "\n")
            log.flush()

        emit("ASUS USB-BT600 experiment; USB 0b05:1d70")
        emit(f"Results: {transcript}")
        emit("Mode: read-only" if args.read_only else "Mode: baseline, memory query, stock RAM patch, and repeat queries")
        try:
            for name, options in phases:
                emit(f"\n--- {name} ---")
                command = [sys.executable, "-u", str(root / "bt600_probe.py"), *options]
                try:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
                    stdout, stderr, code = result.stdout, result.stderr, result.returncode
                except subprocess.TimeoutExpired as error:
                    stdout = error.stdout or b""
                    stderr = error.stderr or b""
                    if isinstance(stdout, bytes):
                        stdout = stdout.decode(errors="replace")
                    if isinstance(stderr, bytes):
                        stderr = stderr.decode(errors="replace")
                    code = 124
                    stderr += "\nThe query timed out after 60 seconds.\n"
                emit(stdout.rstrip())
                if stderr:
                    emit(stderr.rstrip())
                emit(f"Exit status: {code}")
                report["phases"].append({"name": name, "arguments": options, "exit_code": code, "stdout": stdout, "stderr": stderr})
                if re.search(r"^Memory 0x[0-9a-f]{8}: (?:[0-9a-f]{2} ){3}[0-9a-f]{2}$", stdout, re.MULTILINE):
                    report["memory_read_supported"] = True
                if name == "stock_upload" and code == 0 and ("Stock patch is running." in stdout or "is already running." in stdout):
                    report["stock_running"] = True
                # An unsupported vendor read must not prevent the independent
                # stock-upload experiment. A failed basic probe/upload does.
                if code and name not in ("memory_before", "memory_after"):
                    exit_code = code
                    emit("Remaining phases skipped because this phase did not complete.")
                    break
        except KeyboardInterrupt:
            exit_code = 130
            emit("Experiment interrupted; completed phase output has been saved.")
        finally:
            report["exit_code"] = exit_code
            report["finished_utc"] = datetime.now(timezone.utc).isoformat()
            summary.write_text(json.dumps(report, indent=2) + "\n")
            emit(f"\nSaved transcript: {transcript}")
            emit(f"Saved summary: {summary}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
