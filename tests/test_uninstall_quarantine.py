"""Uninstall must preserve quarantined evidence without restoring payloads."""
import pathlib
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "uninstall.sh"


class UninstallQuarantineTest(unittest.TestCase):
    @staticmethod
    def run_backup(source, destination):
        script = SCRIPT.read_text()
        function = script.split("_preserve_quarantine() {\n", 1)[1].split("\n}\n", 1)[0]
        command = (
            "_preserve_quarantine() {\n" + function + "\n}\n"
            "pkg_error() { echo \"$1\" >&2; }\n"
            "pkg_item() { echo \"$1: $2\"; }\n"
            '_preserve_quarantine "$1" "$2"\n'
        )
        return subprocess.run(
            ["bash", "-c", command, "test", str(source), str(destination)],
            capture_output=True, text=True,
        )

    def test_preserves_payload_info_and_history_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp, "install")
            destination = pathlib.Path(tmp, "backups")
            (source / "quarantine").mkdir(parents=True)
            (source / "sess").mkdir()
            (source / "quarantine" / "sample.123").write_bytes(b"suspect")
            (source / "quarantine" / "sample.123.info").write_text("metadata")
            (source / "sess" / "quarantine.hist").write_text("history")
            (source / "sess" / "quarantine.hist.1.gz").write_bytes(b"older")

            result = self.run_backup(source, destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            backup = next(destination.iterdir())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
            for relative in ("quarantine/sample.123", "quarantine/sample.123.info",
                             "sess/quarantine.hist", "sess/quarantine.hist.1.gz"):
                self.assertEqual((source / relative).read_bytes(),
                                 (backup / relative).read_bytes())
            self.assertTrue((source / "quarantine" / "sample.123").exists())

    def test_no_evidence_does_not_create_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp, "install")
            destination = pathlib.Path(tmp, "backups")
            source.mkdir()
            result = self.run_backup(source, destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(destination.exists())

    def test_backup_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp, "install")
            (source / "quarantine").mkdir(parents=True)
            destination = pathlib.Path(tmp, "symlink")
            destination.symlink_to(pathlib.Path(tmp))
            result = self.run_backup(source, destination)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)

    def test_uninstall_never_deletes_backups_by_glob(self):
        script = SCRIPT.read_text()
        self.assertNotIn("rm -rf ${inspath}*", script)
        self.assertIn('_preserve_quarantine "$inspath" /var/backups/maldetect || exit 1',
                      script)

    def test_installation_copies_real_uninstaller_not_empty_placeholder(self):
        installer = (SCRIPT.parent / "install.sh").read_text()
        self.assertIn('command cp -f uninstall.sh "$inspath/uninstall.sh" || return $?',
                      installer)
        self.assertIn('chmod 755 "$inspath/uninstall.sh"', installer)
        self.assertGreater(SCRIPT.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
