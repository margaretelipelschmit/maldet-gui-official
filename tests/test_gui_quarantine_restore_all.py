"""Regression tests for restoring every quarantined file from the GUI."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "maldet_gui", ROOT / "gui/maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class RestoreAllQuarantineTest(unittest.TestCase):
    def test_restores_each_valid_entry_and_reports_partial_failure(self):
        files = [
            {"name": "restored.1"},
            {"name": "failed.2"},
            {"name": "../invalid"},
            {"name": "restored.3"},
        ]

        def restore(args, timeout):
            if args[-1] == "failed.2":
                return "", "restore destination is unavailable", 1
            return "restored", "", 0

        with patch.object(gui, "parse_quarantine_list", return_value=files), \
                patch.object(gui, "quarantine_details") as details, \
                patch.object(gui, "run_maldet", side_effect=restore) as run:
            status, body = gui.MaldetAPI._handle_quarantine_action(
                "restore-all", {})

        self.assertEqual(status, 207)
        self.assertEqual(body["restored"], 2)
        self.assertEqual(body["failed"], 2)
        self.assertEqual(
            [item["file"] for item in body["results"]],
            ["restored.1", "failed.2", "../invalid", "restored.3"])
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [["-s", "restored.1"], ["-s", "failed.2"], ["-s", "restored.3"]])
        self.assertTrue(all(call.kwargs["timeout"] == 30
                            for call in run.call_args_list))
        self.assertEqual(details.call_count, 3)

    def test_empty_quarantine_returns_successful_zero_count(self):
        with patch.object(gui, "parse_quarantine_list", return_value=[]), \
                patch.object(gui, "run_maldet") as run:
            status, body = gui.MaldetAPI._handle_quarantine_action(
                "restore-all", {})

        self.assertEqual(status, 200)
        self.assertEqual(body, {"restored": 0, "failed": 0, "results": []})
        run.assert_not_called()

    def test_single_restore_endpoint_used_by_gui_validates_and_returns_status(self):
        with patch.object(gui, "quarantine_details") as details, \
                patch.object(gui, "run_maldet", return_value=("restored", "", 0)) as run:
            status, body = gui.MaldetAPI._handle_quarantine_action(
                "restore", {"file": "sample.123"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {
            "returncode": 0, "stdout": "restored", "stderr": ""})
        details.assert_called_once_with("sample.123")
        run.assert_called_once_with(["-s", "sample.123"], timeout=30)

        with patch.object(gui, "run_maldet") as run:
            status, body = gui.MaldetAPI._handle_quarantine_action(
                "restore", {"file": "../sample.123"})
        self.assertEqual(status, 400)
        self.assertIn("file", body["error"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
