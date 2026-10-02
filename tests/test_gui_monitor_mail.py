"""Email folder detection API tests; maldet is always mocked."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maldet_gui", ROOT / "gui/maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)

DETECT_OUTPUT = (
    "mail server detected: postfix\n"
    "mail folders:\n"
    "  /var/mail\n"
    "  /var/vmail\n"
    "  /var/mail\n"
    "\n"
    'inotify_maildir_autodetect="1"\n'
)


class MailDetectionTest(unittest.TestCase):
    def test_get_parses_servers_and_dedupes_maildirs(self):
        with patch.object(gui, "get_conf_path", return_value="/tmp/conf.maldet"), \
                patch.object(gui, "parse_config",
                             return_value={"inotify_maildir_autodetect": {"value": "1"}}), \
                patch.object(gui, "run_maldet",
                             return_value=(DETECT_OUTPUT, "", 0)) as run:
            status, body = gui.MaldetAPI.handle("GET", "/api/monitor/mail")
        self.assertEqual(status, 200)
        run.assert_called_once_with(["--mail-detect"], timeout=60)
        self.assertEqual(body["servers"], ["postfix"])
        self.assertTrue(body["detected"])
        # /var/mail appears twice in the report and must be deduped.
        self.assertEqual(body["maildirs"], ["/var/mail", "/var/vmail"])
        self.assertEqual(body["autodetect"], "1")

    def test_get_reports_no_server_without_failing(self):
        output = ("mail server detected: none\n"
                  "mail folders: none found\n"
                  "\n"
                  'inotify_maildir_autodetect="0"\n')
        with patch.object(gui, "get_conf_path", return_value="/tmp/conf.maldet"), \
                patch.object(gui, "parse_config", return_value={}), \
                patch.object(gui, "run_maldet", return_value=(output, "", 1)):
            status, body = gui.MaldetAPI.handle("GET", "/api/monitor/mail")
        self.assertEqual(status, 200)
        self.assertFalse(body["detected"])
        self.assertEqual(body["servers"], [])
        self.assertEqual(body["maildirs"], [])
        self.assertEqual(body["autodetect"], "0")

    def test_get_reports_detection_failure(self):
        with patch.object(gui, "get_conf_path", return_value="/tmp/conf.maldet"), \
                patch.object(gui, "parse_config", return_value={}), \
                patch.object(gui, "run_maldet", side_effect=OSError("boom")):
            status, body = gui.MaldetAPI.handle("GET", "/api/monitor/mail")
        self.assertEqual(status, 503)
        self.assertIn("boom", body["error"])

    def test_method_guard(self):
        self.assertEqual(gui.MaldetAPI.handle("PUT", "/api/monitor/mail")[0], 405)

    def test_post_persists_toggle(self):
        for enabled, value in ((True, "1"), (False, "0")):
            with patch.object(gui, "get_conf_path", return_value="/tmp/conf.maldet"), \
                    patch.object(gui, "write_config_change",
                                 return_value=(True, "ok")) as write:
                status, body = gui.MaldetAPI.handle(
                    "POST", "/api/monitor/mail", {"enabled": enabled})
            self.assertEqual(status, 200)
            self.assertTrue(body["restart_required"])
            self.assertEqual(body["autodetect"], value)
            write.assert_called_once_with(
                "/tmp/conf.maldet", "inotify_maildir_autodetect", value)

    def test_post_rejects_non_boolean(self):
        for payload in ({}, {"enabled": "1"}, {"enabled": 1}, {"enabled": None}):
            with patch.object(gui, "get_conf_path", return_value="/tmp/conf.maldet"), \
                    patch.object(gui, "write_config_change") as write:
                status, _ = gui.MaldetAPI.handle(
                    "POST", "/api/monitor/mail", payload)
            self.assertEqual(status, 400)
            write.assert_not_called()

    def test_post_surfaces_write_failure(self):
        with patch.object(gui, "get_conf_path", return_value="/tmp/conf.maldet"), \
                patch.object(gui, "write_config_change",
                             return_value=(False, "permission denied")):
            status, body = gui.MaldetAPI.handle(
                "POST", "/api/monitor/mail", {"enabled": True})
        self.assertEqual(status, 400)
        self.assertIn("permission denied", body["error"])


if __name__ == "__main__":
    unittest.main()
