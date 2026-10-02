"""WebGUI reload API tests; systemctl is always mocked."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maldet_gui", ROOT / "gui/maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def _which(name):
    return {"systemctl": "/usr/bin/systemctl", "sh": "/bin/sh"}.get(name)


class ReloadTest(unittest.TestCase):
    def test_http_requires_session_same_origin_and_json(self):
        for authenticated, origin, content_type, expected in (
                (False, "http://localhost:8080", "application/json", 401),
                (True, "http://attacker:8080", "application/json", 403),
                (True, "http://localhost:8080", "text/plain", 415)):
            response = []
            handler = SimpleNamespace(
                path="/api/system/reload", headers={
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

    def test_requires_post_and_root_without_restarting(self):
        with patch.object(gui.subprocess, "Popen") as popen, \
                patch.object(gui.os, "geteuid", return_value=0):
            self.assertEqual(gui.MaldetAPI.handle("GET", "/api/system/reload")[0], 405)
            popen.assert_not_called()
        with patch.object(gui.subprocess, "Popen") as popen, \
                patch.object(gui.os, "geteuid", return_value=1000):
            self.assertEqual(gui.MaldetAPI.handle("POST", "/api/system/reload")[0], 403)
            popen.assert_not_called()

    def test_schedules_detached_restart_after_delay(self):
        with patch.object(gui.os, "geteuid", return_value=0), \
                patch.object(gui.shutil, "which", side_effect=_which), \
                patch.object(gui.subprocess, "Popen") as popen:
            status, body = gui.MaldetAPI.handle("POST", "/api/system/reload")
            self.assertEqual(status, 200)
            self.assertEqual(body["delay"], gui.GUI_RELOAD_DELAY_SECONDS)
            self.assertIn("%d seconds" % gui.GUI_RELOAD_DELAY_SECONDS, body["message"])
            popen.assert_called_once()
            argv = popen.call_args.args[0]
            self.assertEqual(argv[0], "/bin/sh")
            self.assertEqual(argv[1], "-c")
            self.assertIn("sleep %d" % gui.GUI_RELOAD_DELAY_SECONDS, argv[2])
            self.assertIn("/usr/bin/systemctl restart maldet-gui.service", argv[2])
            self.assertTrue(popen.call_args.kwargs.get("start_new_session"))

    def test_missing_systemctl_reports_unavailable(self):
        with patch.object(gui.os, "geteuid", return_value=0), \
                patch.object(gui.shutil, "which", return_value=None), \
                patch.object(gui.subprocess, "Popen") as popen:
            status, body = gui.MaldetAPI.handle("POST", "/api/system/reload")
            self.assertEqual(status, 503)
            self.assertIn("systemctl", body["error"])
            popen.assert_not_called()

    def test_popen_failure_reports_error(self):
        with patch.object(gui.os, "geteuid", return_value=0), \
                patch.object(gui.shutil, "which", side_effect=_which), \
                patch.object(gui.subprocess, "Popen", side_effect=OSError("nope")):
            status, body = gui.MaldetAPI.handle("POST", "/api/system/reload")
            self.assertEqual(status, 503)
            self.assertIn("nope", body["error"])


if __name__ == "__main__":
    unittest.main()
