#!/usr/bin/env python3
"""Save live USB descriptors and one RAM dump from normal macOS Terminal."""

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import bt600_probe
import descriptor_capture


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        self.console.write(text)
        self.log.write(text)
        self.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.log.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=lambda value: int(value, 0), default=descriptor_capture.RAM_START)
    parser.add_argument("--words", type=lambda value: int(value, 0), default=16384)
    args = parser.parse_args(argv)
    try:
        descriptor_capture.validate_range(args.start, args.words)
    except ValueError as error:
        parser.error(str(error))
    root = Path(__file__).resolve().parent
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = root / "results" / f"descriptor-{run_id}"
    output.mkdir(parents=True)
    run = {
        "started_utc": run_id,
        "start_address": f"0x{args.start:08x}", "words_requested": args.words,
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                          for name in ("bt600_probe.py", "descriptor_capture.py", "run_descriptor_experiment.py")},
    }
    code = 3
    with (output / "transcript.txt").open("x") as log, \
            contextlib.redirect_stdout(Tee(sys.stdout, log)), \
            contextlib.redirect_stderr(Tee(sys.stderr, log)):
        print(f"Descriptor/RAM capture: {output}", flush=True)
        try:
            code = bt600_probe.main([
                "--capture-usb-ram", str(output),
                "--capture-range", hex(args.start), str(args.words),
            ])
        except KeyboardInterrupt:
            code = 130
            print("Interrupted; completed reads have been saved.")
        except (RuntimeError, ValueError, OSError) as error:
            run["error"] = str(error)
            print(f"Capture stopped: {error}")
        finally:
            run["exit_code"] = code
            run["finished_utc"] = datetime.now(timezone.utc).isoformat()
            (output / "run.json").write_text(json.dumps(run, indent=2) + "\n")
            print(f"Saved results: {output}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
