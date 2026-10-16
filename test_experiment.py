import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_bt600_experiment as experiment


class ExperimentTests(unittest.TestCase):
    def run_simulated(self, results):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(experiment, "__file__", str(root / "run_bt600_experiment.py")), \
                 patch("sys.argv", ["run_bt600_experiment.py"]), \
                 patch.object(experiment.subprocess, "run", side_effect=results) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                code = experiment.main()
            reports = list((root / "results").glob("*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text())
            self.assertTrue(list((root / "results").glob("*.txt")))
            return code, report, run.call_count

    def test_usb_denial_is_saved_and_stops_before_upload(self):
        result = subprocess.CompletedProcess([], 2, "USB access returned zero devices.\n", "")
        code, report, calls = self.run_simulated([result])
        self.assertEqual((code, calls), (2, 1))
        self.assertFalse(report["stock_running"])
        self.assertEqual(report["phases"][0]["exit_code"], 2)

    def test_unsupported_memory_query_does_not_skip_stock_experiment(self):
        results = [
            subprocess.CompletedProcess([], 0, "Diagnostic complete.\n", ""),
            subprocess.CompletedProcess([], 3, "HCI fc61 rejected with status 0x01\n", ""),
            subprocess.CompletedProcess([], 0, "Stock patch is running.\n", ""),
            subprocess.CompletedProcess([], 0, "Diagnostic complete.\n", ""),
            subprocess.CompletedProcess([], 0, "Memory 0x00217e88: 55 ab 23 87\n", ""),
        ]
        code, report, calls = self.run_simulated(results)
        self.assertEqual((code, calls), (0, 5))
        self.assertTrue(report["stock_running"])
        self.assertTrue(report["memory_read_supported"])

    def test_failed_upload_stops_before_after_upload_queries(self):
        good = subprocess.CompletedProcess([], 0, "Diagnostic complete.\n", "")
        bad = subprocess.CompletedProcess([], 3, "Expected stock patch is not running.\n", "")
        code, report, calls = self.run_simulated([good, good, bad])
        self.assertEqual((code, calls), (3, 3))
        self.assertFalse(report["stock_running"])


if __name__ == "__main__":
    unittest.main()
