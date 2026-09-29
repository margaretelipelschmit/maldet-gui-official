"""Tests for installer progress and service status without running install.sh."""
import pathlib
import subprocess
import unittest


INSTALLER = pathlib.Path(__file__).resolve().parents[1] / "install.sh"


def installer_function(name):
    text = INSTALLER.read_text()
    return text.split(name + "() {\n", 1)[1].split("\n}\n", 1)[0]


class InstallStatusTest(unittest.TestCase):
    def run_shell(self, code):
        return subprocess.run(["bash", "-c", code], text=True, capture_output=True)

    def test_steps_report_success_failure_and_exit_code(self):
        shell = (
            "_install_step() {\n" + installer_function("_install_step") + "\n}\n"
            "pkg_info() { printf '%s\\n' \"$1\"; }\n"
            "pkg_error() { printf '%s\\n' \"$1\" >&2; }\n"
        )
        good = self.run_shell(shell + "_install_step 'Copy files' true")
        self.assertEqual(good.returncode, 0)
        self.assertIn("[running] Copy files", good.stdout)
        self.assertIn("[ok] Copy files (", good.stdout)
        bad = self.run_shell(shell + "_install_step 'Copy files' bash -c 'exit 7'")
        self.assertEqual(bad.returncode, 7)
        self.assertIn("[failed] Copy files (exit 7,", bad.stderr)

    def test_systemd_status_shows_state_and_pid(self):
        shell = (
            "_install_service_status() {\n"
            + installer_function("_install_service_status") + "\n}\n"
            "pkg_is_systemd() { return 0; }\n"
            "systemctl() {\n"
            "  case \"$1\" in\n"
            "    is-active) echo active ;;\n"
            "    show) echo 1234 ;;\n"
            "  esac\n"
            "}\n"
            "pkg_item() { printf '%s: %s\\n' \"$1\" \"$2\"; }\n"
            "_install_service_status maldet-gui\n"
        )
        result = self.run_shell(shell)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("maldet-gui: active (PID 1234)", result.stdout)

    def test_inactive_service_is_reported_without_failing_install(self):
        shell = (
            "_install_service_status() {\n"
            + installer_function("_install_service_status") + "\n}\n"
            "pkg_is_systemd() { return 0; }\n"
            "systemctl() {\n"
            "  case \"$1\" in\n"
            "    is-active) echo inactive; return 3 ;;\n"
            "    show) echo 0 ;;\n"
            "  esac\n"
            "}\n"
            "pkg_item() { printf '%s: %s\\n' \"$1\" \"$2\"; }\n"
            "_install_service_status maldet\n"
        )
        result = self.run_shell(shell)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("maldet: inactive (PID -)", result.stdout)

    def test_monitor_restart_finishes_before_status_is_reported(self):
        shell = (
            "_restart_monitor() {\n" + installer_function("_restart_monitor") + "\n}\n"
            "monmode=1\n"
            "pkg_is_systemd() { return 0; }\n"
            "pkg_info() { printf '%s\\n' \"$1\"; }\n"
            "systemctl() {\n"
            "  case \"$1\" in\n"
            "    is-enabled) return 0 ;;\n"
            "    restart) printf '%s\\n' restarted; return 4 ;;\n"
            "  esac\n"
            "}\n"
            "_restart_monitor\n"
        )
        result = self.run_shell(shell)
        self.assertEqual(result.returncode, 4)
        self.assertIn("restarted", result.stdout)


if __name__ == "__main__":
    unittest.main()
