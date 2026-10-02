"""Reboot API tests; shutdown is always mocked."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maldet_gui", ROOT / "gui/maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class RebootTest(unittest.TestCase):
    def test_http_requires_session_same_origin_and_json(self):
        for authenticated, origin, content_type, expected in (
                (False, "http://localhost:8080", "application/json", 401),
                (True, "http://attacker:8080", "application/json", 403),
                (True, "http://localhost:8080", "text/plain", 415)):
            response = []
            handler = SimpleNamespace(
                path="/api/system/reboot", headers={
                    "Origin": origin, "Host": "localhost:8080",
                    "Content-Type": content_type},
                _read_body=lambda: {},
                _authenticated=lambda: authenticated,
                _auth_response=lambda: response.append(401),
                _send_json=lambda body, status: response.append(status))
            with patch.object(gui.MaldetAPI, "handle") as dispatch:
                gui.Handler.do_POST(handler)
                self.assertEqual(response, [expected])
                dispatch.assert_not_called()

    def test_requires_post_and_root_without_running_shutdown(self):
        with patch.object(gui.subprocess, "run") as run, \
                patch.object(gui.os, "geteuid", return_value=0):
            self.assertEqual(gui.MaldetAPI.handle("GET", "/api/system/reboot")[0], 405)
            run.assert_not_called()
        with patch.object(gui.subprocess, "run") as run, \
                patch.object(gui.os, "geteuid", return_value=1000):
            self.assertEqual(gui.MaldetAPI.handle("POST", "/api/system/reboot")[0], 403)
            run.assert_not_called()

    def test_schedules_reboot_and_reports_failures(self):
        with patch.object(gui.os, "geteuid", return_value=0), \
                patch.object(gui.shutil, "which", return_value="/usr/sbin/shutdown"), \
                patch.object(gui.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            status, body = gui.MaldetAPI.handle("POST", "/api/system/reboot")
            self.assertEqual(status, 200)
            self.assertIn("one minute", body["message"])
            run.assert_called_once_with(
                ["/usr/sbin/shutdown", "-r", "+1", "Maldet GUI requested a system reboot"],
                capture_output=True, text=True, timeout=10)
            run.return_value = subprocess.CompletedProcess([], 1, "", "permission denied")
            status, body = gui.MaldetAPI.handle("POST", "/api/system/reboot")
            self.assertEqual(status, 503)
            self.assertIn("permission denied", body["error"])
            run.side_effect = subprocess.TimeoutExpired([], 10)
            self.assertEqual(gui.MaldetAPI.handle("POST", "/api/system/reboot")[0], 503)
        with patch.object(gui.os, "geteuid", return_value=0), \
                patch.object(gui.shutil, "which", return_value=None), \
                patch.object(gui.subprocess, "run") as run:
            self.assertEqual(gui.MaldetAPI.handle("POST", "/api/system/reboot")[0], 503)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
