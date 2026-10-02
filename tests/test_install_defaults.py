"""Check defaults used by new installs without touching the installed system."""
import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def setting(path, name):
    match = re.search(r'^' + re.escape(name) + r'="([^"]*)"$',
                      path.read_text(), re.MULTILINE)
    if not match:
        raise AssertionError("Missing default: " + name)
    return match.group(1)


class InstallDefaultsTest(unittest.TestCase):
    def test_packaged_defaults_for_new_install(self):
        config = ROOT / "files" / "conf.maldet"
        self.assertEqual(setting(config, "default_monitor_mode"), "users")
        self.assertEqual(setting(config, "inotify_docroot"), "")
        self.assertEqual(setting(config, "quarantine_hits"), "1")
        self.assertEqual(setting(config, "sigup_interval"), "6")
        self.assertEqual(setting(ROOT / "files" / "service" / "maldet.sysconfig",
                                 "MONITOR_MODE"), "users")
        self.assertIn("MALDET_GUI_PORT=8080", (ROOT / "install.sh").read_text())

    def test_fresh_install_copies_defaults_upgrade_imports_previous_config(self):
        script = (ROOT / "install.sh").read_text()
        self.assertIn('pkg_copy_tree "files" "$inspath"', script)
        upgrade, fresh = script.split("elif [ -d \"files\" ]; then", 1)
        self.assertIn('"$inspath/internals/importconf"', upgrade)
        self.assertNotIn('"$inspath/internals/importconf"', fresh)

    def test_installer_reads_values_from_installed_config(self):
        script = (ROOT / "install.sh").read_text()
        function = script.split("_read_conf_value() {\n", 1)[1].split("\n}\n", 1)[0]
        with tempfile.TemporaryDirectory() as base:
            path = pathlib.Path(base) / "conf.maldet"
            path.write_text('default_monitor_mode="users"\nquarantine_hits="1"\n'
                            'sigup_interval="6"\n')
            command = (
                "_read_conf_value() {\n" + function + "\n}\n"
                'inspath="$1"\n'
                '_read_conf_value default_monitor_mode\n'
                '_read_conf_value quarantine_hits\n'
                '_read_conf_value sigup_interval\n'
            )
            result = subprocess.run(["bash", "-c", command, "test", base],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["users", "1", "6"])


if __name__ == "__main__":
    unittest.main()
