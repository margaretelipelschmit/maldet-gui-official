"""Mail folder detection helpers in lmd_monitor.sh.

Drives the real shell functions against a throwaway filesystem root so the
Dovecot/Postfix/Courier/Cyrus parsing and the well-known spool list are
exercised without touching the real host.
"""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MONITOR_SH = ROOT / "files" / "internals" / "lmd_monitor.sh"


class MailDetectTest(unittest.TestCase):
    """Run _monitor_collect_mail_dirs / mail_detect_report under bash."""

    def _prelude(self, autodetect="1"):
        # lmd_monitor.sh is safe to source: it returns early on the
        # _LMD_MONITOR_LOADED guard and its top level is only function
        # definitions. eout() is stubbed because the helpers log through it.
        return (
            "set -u\n"
            "inotify_docroot_autodetect=1\n"
            "inotify_maildir_autodetect=" + autodetect + "\n"
            "eout() { :; }\n"
            "source " + str(MONITOR_SH) + "\n"
        )

    def _detect(self, body, autodetect="1"):
        return subprocess.run(
            ["bash", "-c", self._prelude(autodetect) + "\n" + body],
            capture_output=True, text=True, timeout=60)

    def _fake_root(self, temp):
        root = pathlib.Path(temp)
        (root / "etc/dovecot").mkdir(parents=True)
        (root / "var/vmail/domaine.com/user").mkdir(parents=True)
        (root / "var/mail").mkdir(parents=True)
        (root / "var/spool/imap").mkdir(parents=True)
        return root

    def test_wellknown_spools_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._fake_root(temp)
            result = self._detect(
                '_monitor_collect_mail_dirs "%s"' % root)
        self.assertEqual(result.returncode, 0, result.stderr)
        found = result.stdout.split()
        self.assertIn(str(root / "var/mail"), found)
        self.assertIn(str(root / "var/spool/imap"), found)
        # Deduped: a path listed by two sources appears exactly once.
        self.assertEqual(len(found), len(set(found)), found)

    def test_dovecot_mail_location_variable_is_trimmed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._fake_root(temp)
            (root / "etc/dovecot/dovecot.conf").write_text(
                "mail_location = maildir:/var/vmail/%%d/%%n/Maildir\n")
            result = self._detect('_monitor_collect_mail_dirs "%s"' % root)
        self.assertEqual(result.returncode, 0, result.stderr)
        # The per-user variables are trimmed back to the existing /var/vmail.
        self.assertIn(str(root / "var/vmail"), result.stdout.split())

    def test_postfix_virtual_mailbox_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._fake_root(temp)
            (root / "etc/postfix").mkdir(parents=True)
            (root / "etc/postfix/main.cf").write_text(
                "virtual_mailbox_base = /var/vmail\n")
            result = self._detect('_monitor_collect_mail_dirs "%s"' % root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(root / "var/vmail"), result.stdout.split())

    def test_courier_cyrus_maildir_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._fake_root(temp)
            (root / "etc").mkdir(parents=True, exist_ok=True)
            (root / "etc/imapd.conf").write_text(
                "maildir:/srv/imap/example.com\n")
            result = self._detect('_monitor_collect_mail_dirs "%s"' % root)
        self.assertEqual(result.returncode, 0, result.stderr)
        # The directory does not exist, so it must not be reported.
        self.assertNotIn("/srv/imap", result.stdout)

    def test_report_reports_autodetect_state(self):
        result = subprocess.run(
            ["bash", "-c",
             self._prelude("1") + "\nmail_detect_report || true"],
            capture_output=True, text=True, timeout=60)
        self.assertIn('inotify_maildir_autodetect="1"', result.stdout)
        self.assertIn("detected mail folders are added", result.stdout)

        result = subprocess.run(
            ["bash", "-c",
             self._prelude("0") + "\nmail_detect_report || true"],
            capture_output=True, text=True, timeout=60)
        self.assertIn('inotify_maildir_autodetect="0"', result.stdout)
        self.assertIn("hint: set inotify_maildir_autodetect", result.stdout)


if __name__ == "__main__":
    unittest.main()
