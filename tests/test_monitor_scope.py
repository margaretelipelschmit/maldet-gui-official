"""Monitor scope API and webroot-only path selection tests."""
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maldet_gui", ROOT / "gui" / "maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class MonitorScopeTest(unittest.TestCase):
    def test_scope_round_trip_and_custom_config(self):
        with tempfile.TemporaryDirectory() as temp:
            conf = pathlib.Path(temp, "conf.maldet")
            conf.write_text('inotify_docroot="legacy"\n')
            with patch.object(gui, "get_conf_path", return_value=str(conf)):
                status, result = gui.MaldetAPI.handle("GET", "/api/monitor/scope")
                self.assertEqual((status, result["scope"]), (200, "custom"))
                status, result = gui.MaldetAPI.handle(
                    "PUT", "/api/monitor/scope", {"scope": "webroots"})
                self.assertEqual((status, result["restart_required"]), (200, True))
                self.assertEqual(conf.read_text(), 'inotify_docroot="public_html,htdocs"\n')
                self.assertEqual(gui.MaldetAPI.handle("GET", "/api/monitor/scope")[1]["scope"],
                                 "webroots")
                status, _ = gui.MaldetAPI.handle(
                    "PUT", "/api/monitor/scope", {"scope": "recursive"})
                self.assertEqual(status, 200)
                self.assertEqual(conf.read_text(), 'inotify_docroot=""\n')
                status, _ = gui.MaldetAPI.handle(
                    "PUT", "/api/monitor/scope", {"scope": "unexpected"})
                self.assertEqual(status, 400)

    def test_missing_config_is_not_reported_as_recursive(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(gui, "get_conf_path", return_value=str(pathlib.Path(temp, "missing"))):
                status, _ = gui.MaldetAPI.handle("GET", "/api/monitor/scope")
                self.assertEqual(status, 503)

    def test_scope_update_does_not_change_webserver_autodetect(self):
        with tempfile.TemporaryDirectory() as temp:
            conf = pathlib.Path(temp, "conf.maldet")
            conf.write_text('inotify_docroot=""\ninotify_docroot_autodetect="1"\n')
            with patch.object(gui, "get_conf_path", return_value=str(conf)):
                status, _ = gui.MaldetAPI.handle(
                    "PUT", "/api/monitor/scope", {"scope": "webroots"})
            self.assertEqual(status, 200)
            self.assertIn('inotify_docroot_autodetect="1"', conf.read_text())

    def test_webroot_only_excludes_additive_paths(self):
        shell = (ROOT / "files/internals/lmd_monitor.sh").read_text()
        function = shell.split("_monitor_user_webroots_only() {\n", 1)[1].split("\n}\n", 1)[0]
        command = (
            "_monitor_user_webroots_only() {\n" + function + "\n}\n"
            'inopt="$1"; inotify_docroot="$2"; _monitor_user_webroots_only\n'
        )
        for mode, docroot, expected in (
            ("users", "public_html,htdocs", 0),
            ("USERS", "public_html,htdocs", 0),
            ("users", "", 1),
            ("/home", "public_html,htdocs", 1),
        ):
            result = subprocess.run(
                ["bash", "-c", command, "test", mode, docroot], capture_output=True)
            self.assertEqual(result.returncode, expected)
        for fragment in ('! _monitor_user_webroots_only && [ -d "/tmp" ]',
                         '! _monitor_user_webroots_only && [ -d "/var/tmp" ]',
                         '! _monitor_user_webroots_only && [ -d "/dev/shm" ]',
                         'if ! _monitor_user_webroots_only; then\n'
                         '\t\t_monitor_append_extra_paths'):
            self.assertIn(fragment, shell)


if __name__ == "__main__":
    unittest.main()
