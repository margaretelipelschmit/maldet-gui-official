"""Scheduled report attribution without running a malware scan."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maldet_gui", ROOT / "gui" / "maldet_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class ScheduleReportsTest(unittest.TestCase):
    def test_installer_schedule_defaults_match_cron_and_gui_model(self):
        cron = (ROOT / "files/cron/maldet-gui-schedules").read_text()
        saved = json.loads((ROOT / "files/cron/gui.schedules.json").read_text())["schedules"]
        self.assertEqual(len(saved), 3)
        with patch.object(gui, "get_base_dir", return_value="/usr/local/maldetect"), \
                patch.object(gui, "get_managed_cron_path",
                             return_value=str(ROOT / "files/cron/maldet-gui-schedules")):
            self.assertEqual(gui.read_managed_cron_schedules(), saved)
            generated = (
                "# Managed by Maldet GUI (Agendamentos) - do not edit manually.\n"
                "# This file is regenerated automatically whenever schedules change.\n"
                + "".join(gui.build_schedule_cron_line(schedule) + "\n"
                          for schedule in saved))
            self.assertEqual(cron, generated)

    def test_cron_only_schedules_are_imported_and_survive_other_deletions(self):
        with tempfile.TemporaryDirectory() as base, \
                patch.object(gui, "get_base_dir", return_value=base), \
                patch.object(gui, "get_schedules_path",
                             return_value=str(Path(base, "gui.schedules.json"))), \
                patch.object(gui, "get_managed_cron_path",
                             return_value=str(Path(base, "maldet-gui-schedules"))):
            original = {
                "id": "sch_123_abcdef", "name": "Saved", "path": "/",
                "scan_type": "all", "frequency": "daily", "enabled": True,
            }
            imported = {
                "id": "sch_456_012abc", "name": "Cron only",
                "path": "/home/space dir", "scan_type": "recent", "days": 2,
                "frequency": "weekly", "minute": 5, "hour": 4, "weekday": 2,
                "enabled": False,
            }
            Path(gui.get_schedules_path()).write_text(
                json.dumps({"schedules": [original]}))
            line = gui.build_schedule_cron_line(imported)
            # Legacy entries do not set MALDET_GUI_SCHEDULE_ID.
            line = line.replace("MALDET_GUI_SCHEDULE_ID=sch_456_012abc ", "")
            unmanaged = "0 0 * * * root /usr/bin/true\n"
            Path(gui.get_managed_cron_path()).write_text(
                gui.build_schedule_cron_line(original) + "\n" + line + "\n" + unmanaged)
            status, result = gui.MaldetAPI.handle("GET", "/api/schedules")
            self.assertEqual(status, 200)
            self.assertEqual(len(result["schedules"]), 2)
            self.assertEqual(result["schedules"][0], original)
            self.assertEqual(result["schedules"][1]["path"], "/home/space dir")
            self.assertEqual(result["schedules"][1]["frequency"], "weekly")
            self.assertFalse(result["schedules"][1]["enabled"])
            self.assertEqual(len(json.loads(Path(gui.get_schedules_path()).read_text())["schedules"]), 2)

            status, _ = gui.MaldetAPI.handle("DELETE", "/api/schedules/" + original["id"])
            self.assertEqual(status, 200)
            self.assertEqual([s["id"] for s in gui.load_schedules()], [imported["id"]])
            self.assertIn(unmanaged, Path(gui.get_managed_cron_path()).read_text())

    def test_cron_only_schedule_without_json_and_custom_timing(self):
        with tempfile.TemporaryDirectory() as base, \
                patch.object(gui, "get_base_dir", return_value=base), \
                patch.object(gui, "get_schedules_path",
                             return_value=str(Path(base, "gui.schedules.json"))), \
                patch.object(gui, "get_managed_cron_path",
                             return_value=str(Path(base, "maldet-gui-schedules"))):
            schedule = {
                "id": "sch_789_aabbcc", "name": "Custom scan", "path": "/",
                "scan_type": "all", "frequency": "custom",
                "cron_expr": "*/15 1-3 * * 1,3", "enabled": True,
            }
            Path(gui.get_managed_cron_path()).write_text(
                gui.build_schedule_cron_line(schedule) + "\n")
            status, result = gui.MaldetAPI.handle("GET", "/api/schedules")
            self.assertEqual(status, 200)
            self.assertEqual(result["schedules"][0]["cron_expr"], schedule["cron_expr"])
            self.assertTrue(Path(gui.get_schedules_path()).exists())

    def test_invalid_managed_cron_does_not_overwrite_existing_schedules(self):
        with tempfile.TemporaryDirectory() as base, \
                patch.object(gui, "get_base_dir", return_value=base), \
                patch.object(gui, "get_schedules_path",
                             return_value=str(Path(base, "gui.schedules.json"))), \
                patch.object(gui, "get_managed_cron_path",
                             return_value=str(Path(base, "maldet-gui-schedules"))):
            cron = Path(gui.get_managed_cron_path())
            invalid = "0 3 * * * root /usr/bin/false  # gui-schedule:sch_123_abcdef Bad\n"
            cron.write_text(invalid)
            status, result = gui.MaldetAPI.handle("GET", "/api/schedules")
            self.assertEqual(status, 500)
            self.assertIn("error", result)
            ok, error = gui.write_managed_cron_file([])
            self.assertFalse(ok)
            self.assertIsNotNone(error)
            self.assertEqual(cron.read_text(), invalid)

    def test_reports_only_from_own_schedule_even_when_paths_match(self):
        with tempfile.TemporaryDirectory() as session:
            own = "sch_123_abcdef"
            other = "sch_456_012abc"
            scans = ["260927-1145.101", "260927-1146.102", "260927-1147.103",
                     "260927-1148.104", "../../etc/passwd"]
            for scan_id, schedule_id in zip(scans, [own, other, None, own]):
                if schedule_id:
                    Path(session, "gui.schedule." + scan_id).write_text(schedule_id)
            entries = [
                {"scan_id": scan_id, "path": "/home/user", "started_epoch": index}
                for index, scan_id in enumerate(scans)
            ]
            with patch.object(gui, "load_schedules", return_value=[
                {"id": own, "path": "/home/user"}
            ]), patch.object(gui, "get_session_dir", return_value=session), \
                    patch.object(gui, "safe_json_list", return_value={"reports": entries}):
                status, result = gui.MaldetAPI.handle(
                    "GET", "/api/schedules/" + own + "/reports")
            self.assertEqual(status, 200)
            self.assertEqual([r["scan_id"] for r in result["reports"]],
                             ["260927-1148.104", "260927-1145.101"])

    def test_cron_passes_schedule_id_to_maldet(self):
        with tempfile.TemporaryDirectory() as base:
            binary = Path(base, "maldet")
            binary.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$MALDET_GUI_SCHEDULE_ID\" \"$@\"\n")
            binary.chmod(0o755)
            schedule = {"id": "sch_123_abcdef", "name": "Daily",
                        "path": "/home/space dir", "scan_type": "recent", "days": 2}
            with patch.object(gui, "get_base_dir", return_value=base):
                line = gui.build_schedule_cron_line(schedule)
            command = line.split(" root ", 1)[1].split(" >>", 1)[0]
            output = subprocess.check_output(["sh", "-c", command], text=True)
            self.assertEqual(output.splitlines(),
                             ["sch_123_abcdef", "-b", "-r", "/home/space dir", "2"])

    def test_scan_tags_only_valid_schedule_ids(self):
        shell = (ROOT / "files/internals/lmd_scan.sh").read_text()
        fragment = shell.split("_scan_record_gui_schedule() {", 1)[1].split("\n}\n", 1)[0]
        function = "_scan_record_gui_schedule() {" + fragment + "\n}\n"
        with tempfile.TemporaryDirectory() as session:
            marker = Path(session, "gui.schedule.260927-1145.101")
            for schedule_id in ["sch_123_abcdef", "invalid/../../id", ""]:
                env = dict(os.environ, MALDET_GUI_SCHEDULE_ID=schedule_id)
                result = subprocess.run(
                    ["bash", "-c", function + '\nsessdir="$1"; scanid=260927-1145.101; '
                     '_scan_record_gui_schedule', "test", session],
                    env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if schedule_id == "sch_123_abcdef":
                    self.assertEqual(marker.read_text(), schedule_id + "\n")
                    marker.unlink()
                else:
                    self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
