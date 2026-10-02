"""Monitored folders API tests (monitor_paths_extra)."""
import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maldet_gui", ROOT / "gui" / "maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class MonitorPathsTest(unittest.TestCase):
    def _conf(self, temp, extra_file):
        conf = pathlib.Path(temp, "conf.maldet")
        conf.write_text('monitor_paths_extra="%s"\n' % extra_file)
        return conf

    def test_paths_round_trip_is_sorted_and_deduped(self):
        with tempfile.TemporaryDirectory() as temp:
            extra_file = pathlib.Path(temp, "monitor_paths.extra")
            conf = self._conf(temp, extra_file)
            first = pathlib.Path(temp, "zeta")
            second = pathlib.Path(temp, "alpha")
            first.mkdir()
            second.mkdir()
            with patch.object(gui, "get_conf_path", return_value=str(conf)):
                status, result = gui.MaldetAPI.handle("GET", "/api/monitor/paths")
                self.assertEqual((status, result["paths"]), (200, []))
                status, result = gui.MaldetAPI.handle("PUT", "/api/monitor/paths", {
                    "paths": [str(first) + "/", str(second), str(first), ""],
                })
                self.assertEqual((status, result["restart_required"]), (200, True))
                self.assertEqual(result["paths"], sorted([str(first), str(second)]))
                self.assertEqual(
                    extra_file.read_text(),
                    "\n".join(sorted([str(first), str(second)])) + "\n")
                status, result = gui.MaldetAPI.handle("GET", "/api/monitor/paths")
                self.assertEqual(status, 200)
                self.assertEqual(result["paths"], sorted([str(first), str(second)]))
                self.assertEqual(result["path"], str(extra_file))

    def test_empty_list_clears_the_file(self):
        with tempfile.TemporaryDirectory() as temp:
            extra_file = pathlib.Path(temp, "monitor_paths.extra")
            folder = pathlib.Path(temp, "www")
            folder.mkdir()
            extra_file.write_text(str(folder) + "\n")
            conf = self._conf(temp, extra_file)
            with patch.object(gui, "get_conf_path", return_value=str(conf)):
                status, result = gui.MaldetAPI.handle(
                    "PUT", "/api/monitor/paths", {"paths": []})
                self.assertEqual((status, result["paths"]), (200, []))
                self.assertEqual(extra_file.read_text(), "")
                self.assertEqual(
                    gui.MaldetAPI.handle("GET", "/api/monitor/paths")[1]["paths"], [])

    def test_existing_file_comments_and_blanks_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            extra_file = pathlib.Path(temp, "monitor_paths.extra")
            extra_file.write_text("# comment\n\n/srv/www\n")
            conf = self._conf(temp, extra_file)
            with patch.object(gui, "get_conf_path", return_value=str(conf)):
                status, result = gui.MaldetAPI.handle("GET", "/api/monitor/paths")
                self.assertEqual((status, result["paths"]), (200, ["/srv/www"]))

    def test_default_file_location_when_unset(self):
        with tempfile.TemporaryDirectory() as temp:
            conf = pathlib.Path(temp, "conf.maldet")
            conf.write_text('inotify_docroot=""\n')
            with patch.object(gui, "get_conf_path", return_value=str(conf)), \
                    patch.object(gui, "get_base_dir", return_value=temp):
                status, result = gui.MaldetAPI.handle("GET", "/api/monitor/paths")
                self.assertEqual(status, 200)
                self.assertEqual(result["paths"], [])
                self.assertEqual(result["path"], os.path.join(temp, "monitor_paths.extra"))

    def test_rejects_relative_missing_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            extra_file = pathlib.Path(temp, "monitor_paths.extra")
            conf = self._conf(temp, extra_file)
            folder = pathlib.Path(temp, "ok")
            folder.mkdir()
            with patch.object(gui, "get_conf_path", return_value=str(conf)):
                for payload in (
                    {"paths": "not-a-list"},
                    {"paths": [123]},
                    {"paths": ["relative/dir"]},
                    {"paths": [str(pathlib.Path(temp, "missing"))]},
                    {"paths": [str(folder) + "\n/evil"]},
                    {"paths": [str(folder) + "\x00evil"]},
                ):
                    status, result = gui.MaldetAPI.handle(
                        "PUT", "/api/monitor/paths", payload)
                    self.assertEqual(status, 400, payload)
                    self.assertIn("error", result)
                # A rejected request must not touch the existing file.
                self.assertFalse(extra_file.exists())

    def test_method_not_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            conf = self._conf(temp, pathlib.Path(temp, "monitor_paths.extra"))
            with patch.object(gui, "get_conf_path", return_value=str(conf)):
                status, _ = gui.MaldetAPI.handle("DELETE", "/api/monitor/paths")
                self.assertEqual(status, 405)


if __name__ == "__main__":
    unittest.main()
