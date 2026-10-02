"""`maldet --format json --report list` must list unindexed TSV sessions.

session.index is append-only and only fully rebuilt when absent, so a scan
whose index append was lost (ENOSPC, SIGKILL between the TSV and index
writes, a restored backup) leaves a session.tsv.* on disk that the index pass
never sees. _view_session_list in lmd_session.sh already sweeps those; this
test pins the mirror in _lmd_render_json_list, which is what the WebGUI
Reports page consumes via /api/scans.

The function under test is extracted verbatim from the source so the test
cannot drift from the implementation.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALERT = ROOT / "files/internals/lmd_alert.sh"
LIB = ROOT / "files/internals/lmd.lib.sh"

# TSV field order (see _session_index_rebuild, lmd_lifecycle.sh:612). A real
# session.tsv.<id> has NO header line: the first line IS the metadata row and
# is what `read -r ... < "$_tsv"` picks up. Later lines are hit rows whose
# field 3 holds the quarantine path (what the awk counter tallies).
TSV_FIELDS = [
    "scan_fmt", "alert_type", "scan_id", "hostname", "path", "days",
    "started_hr", "end_hr", "elapsed", "flags", "tot_files", "tot_hits",
    "tot_cleaned", "scanner_ver", "sig_ver", "hashtype", "engine",
    "quarantine", "hostid",
]


def extract_function(path, name):
    """Return the body of a top-level bash function, verbatim."""
    lines = path.read_text().split("\n")
    start = next(i for i, line in enumerate(lines)
                 if line.startswith(name + "() {"))
    for end in range(start + 1, len(lines)):
        if lines[end] == "}":
            return "\n".join(lines[start:end + 1])
    raise AssertionError("unterminated function: " + name)


# Stubs for the two helpers the function calls that are irrelevant here: the
# index rebuild only runs when session.index is missing (these tests always
# create it), and the legacy plaintext parser is only reached by session.<id>
# files, which these tests never create.
STUBS = """
_session_index_rebuild() { printf 'index rebuilt\\n' >&2; }
_parse_session_metadata() { scanid=""; }
"""


def render(sessdir):
    """Run the real _lmd_render_json_list against sessdir; return parsed JSON."""
    script = "\n".join([
        extract_function(LIB, "_json_escape_var"),
        extract_function(LIB, "_json_escape_string"),
        extract_function(ALERT, "_lmd_render_json_list"),
        STUBS,
        'sessdir="$1"',
        'tmpdir="$2"',
        'sigdir="$2"',
        'scanid=""; scan_start_hr=""; scan_end_hr=""; scan_et=""',
        'tot_files=""; tot_hits=""; tot_cl=""; hrspath=""',
        "_lmd_render_json_list",
    ])
    # The renderer derives epochs with `date -d`, which resolves in the host's
    # local zone (coreutils `date` here reads /etc/localtime, not $TZ). The
    # expectations are computed the same way, so the test is zone-independent.
    proc = subprocess.run(
        ["bash", "-c", script, "_sb", str(sessdir), str(sessdir / "tmp")],
        capture_output=True, text=True, timeout=60,
        env={"PATH": os.environ["PATH"]})
    if proc.returncode != 0:
        raise AssertionError("renderer failed: " + proc.stderr)
    return json.loads(proc.stdout)


def epoch(text):
    """Epoch for a 'YYYY-MM-DD HH:MM:SS' string, in the host's local zone.

    Matches how the renderer resolves timestamps (via `date -d`), so the
    assertions hold regardless of the host timezone.
    """
    import time
    return int(time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S")))


def write_index(sessdir, *rows):
    (sessdir / "session.index").write_text(
        "".join("\t".join(str(f) for f in row) + "\n" for row in rows))


def write_tsv(sessdir, suffix, *, scan_id, path="/srv/www",
              started="2024-05-01 10:00:00", elapsed="120", sig="2.0.1",
              engine="clamav", quarantine="1", rows=()):
    """Write a session.tsv.<suffix> in the real on-disk shape (no header)."""
    meta = {name: "-" for name in TSV_FIELDS}
    meta.update({
        "scan_fmt": "1", "alert_type": "scan", "scan_id": scan_id,
        "hostname": "host", "path": path, "days": "1", "started_hr": started,
        "end_hr": "2024-05-01 10:02:00", "elapsed": elapsed, "flags": "-",
        "tot_files": "10", "tot_hits": "1", "tot_cleaned": "0",
        "scanner_ver": "2.0.1", "sig_ver": sig, "hashtype": "sha256",
        "engine": engine, "quarantine": quarantine, "hostid": "-",
    })
    lines = ["\t".join(meta[name] for name in TSV_FIELDS)]
    lines.extend(rows)
    (sessdir / ("session.tsv." + suffix)).write_text("\n".join(lines) + "\n")


def index_row(scan_id, epoch="1714557600", started="2024-05-01 10:00:00",
              elapsed="120"):
    return (scan_id, epoch, started, elapsed, 10, 0, 0, 0, "/srv/www",
            "2.0.1", "1", "2024-05-01 10:02:00", "clamav", "sha256")


def hit_row(scan_id, quarantine="1"):
    return "#HIT\t{0}\t/tmp/{0}\tmalware\t{1}\t{1}".format(scan_id, quarantine)


def epoch(human):
    """Resolve a human timestamp the same way the renderer does (`date -d`).

    Computing this instead of hardcoding keeps the test independent of the
    host timezone, which `date -d` honours.
    """
    return int(subprocess.run(
        ["date", "-d", human, "+%s"], capture_output=True, text=True,
        check=True).stdout.strip())


class UnindexedSessionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sessdir = Path(self._tmp.name)
        (self.sessdir / "tmp").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_tsv_missing_from_index_is_listed(self):
        # The regression: an indexed-only render drops this report entirely.
        write_index(self.sessdir, index_row("050910-1534.21135"))
        write_tsv(self.sessdir, "060101-0900.99999", scan_id="060101-0900.99999",
                  rows=[hit_row("060101-0900.99999")])

        reports = render(self.sessdir)["reports"]
        ids = [r["scan_id"] for r in reports]
        self.assertIn("060101-0900.99999", ids,
                      "unindexed TSV session must appear in the report list")
        entry = next(r for r in reports if r["scan_id"] == "060101-0900.99999")
        self.assertEqual(entry["source"], "tsv-unindexed")
        self.assertEqual(entry["path"], "/srv/www")
        self.assertEqual(entry["sig_version"], "2.0.1")
        self.assertEqual(entry["engine"], "clamav")
        self.assertEqual(entry["hash_type"], "sha256")
        self.assertEqual(entry["quarantine_enabled"], True)
        self.assertEqual(entry["total_quarantined"], 1)
        self.assertEqual(entry["started_epoch"], epoch("2024-05-01 10:00:00"))
        self.assertEqual(entry["elapsed_seconds"], 120)
        self.assertEqual(entry["completed_epoch"],
                         epoch("2024-05-01 10:02:00"))

    def test_indexed_tsv_is_not_duplicated(self):
        write_index(self.sessdir, index_row("050910-1534.21135"))
        write_tsv(self.sessdir, "050910-1534.21135", scan_id="050910-1534.21135",
                  rows=[hit_row("050910-1534.21135")])

        reports = render(self.sessdir)["reports"]
        self.assertEqual([r["scan_id"] for r in reports], ["050910-1534.21135"])
        self.assertNotIn("source", reports[0],
                         "indexed entries keep their existing shape")

    def test_compressed_tsv_is_skipped(self):
        # _session_compress leaves session.tsv.<id>.gz behind; re-reading it
        # would emit a binary-garbage duplicate.
        write_index(self.sessdir, index_row("050910-1534.21135"))
        (self.sessdir / "session.tsv.060101-0900.99999.gz").write_bytes(
            b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03binary")

        reports = render(self.sessdir)["reports"]
        self.assertEqual([r["scan_id"] for r in reports], ["050910-1534.21135"])

    def test_header_only_tsv_is_skipped(self):
        # An empty/garbage session.tsv.<id> (truncated write) leaves no scan ID
        # in the first line, so it must not be emitted as a bogus report.
        write_index(self.sessdir, index_row("050910-1534.21135"))
        (self.sessdir / "session.tsv.060101-0900.99999").write_text("")

        reports = render(self.sessdir)["reports"]
        self.assertEqual([r["scan_id"] for r in reports], ["050910-1534.21135"])

    def test_mixed_indexed_and_unindexed_are_sorted_desc(self):
        write_index(self.sessdir, index_row("050910-1534.21135"))
        # Older start date -> must sort after the indexed entry.
        write_tsv(self.sessdir, "040101-0900.11111", scan_id="040101-0900.11111",
                  started="2024-04-01 09:00:00")

        reports = render(self.sessdir)["reports"]
        self.assertEqual([r["scan_id"] for r in reports],
                         ["050910-1534.21135", "040101-0900.11111"])

    def test_missing_fields_render_as_null(self):
        # A v1-era TSV with "-" placeholders must not emit invalid JSON.
        write_index(self.sessdir, index_row("050910-1534.21135"))
        row = {name: "-" for name in TSV_FIELDS}
        row.update({"scan_id": "060101-0900.99999", "path": "/srv/mail",
                    "started_hr": "2024-05-01 10:00:00", "elapsed": "30"})
        (self.sessdir / "session.tsv.060101-0900.99999").write_text(
            "\t".join(row[name] for name in TSV_FIELDS) + "\n")

        reports = render(self.sessdir)["reports"]
        entry = next(r for r in reports if r["scan_id"] == "060101-0900.99999")
        self.assertEqual(entry["sig_version"], None)
        self.assertEqual(entry["engine"], None)
        self.assertEqual(entry["hash_type"], None)
        self.assertEqual(entry["quarantine_enabled"], False)
        self.assertEqual(entry["total_files"], None)
        self.assertEqual(entry["total_cleaned"], 0)
        self.assertEqual(entry["completed_epoch"],
                         epoch("2024-05-01 10:00:30"))


if __name__ == "__main__":
    unittest.main()
