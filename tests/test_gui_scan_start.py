"""Scan start API tests; Maldet execution is mocked."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maldet_gui", ROOT / "gui/maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class ScanStartTest(unittest.TestCase):
    def setUp(self):
        gui.SCAN_START_RESERVATIONS.clear()

    def tearDown(self):
        gui.SCAN_START_RESERVATIONS.clear()

    def start_scan_with_result(self, result):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch.object(gui, "safe_json_active",
                          return_value={"active_scans": []}), \
                patch.object(gui, "run_maldet", return_value=result):
            status, body = gui.MaldetAPI._handle_scan_start({
                "type": "all", "path": directory.name,
            })
        return status, body

    def test_exit_code_two_is_successful_scan_start(self):
        status, body = self.start_scan_with_result(
            ("Scan launched in background with detections", "", 2))
        self.assertEqual(status, 200)
        self.assertTrue(body["scan_started"])
        self.assertEqual(body["message"], "Scan started in background")

    def test_non_scan_error_remains_failure(self):
        status, body = self.start_scan_with_result(("", "invalid scan path", 1))
        self.assertEqual(status, 500)
        self.assertIn("invalid scan path", body["error"])
        self.assertEqual(gui.SCAN_START_RESERVATIONS, {})


if __name__ == "__main__":
    unittest.main()
