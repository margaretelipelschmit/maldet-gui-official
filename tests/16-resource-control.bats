#!/usr/bin/env bats

load '/usr/local/lib/bats/bats-support/load'
load '/usr/local/lib/bats/bats-assert/load'
source /opt/tests/helpers/lmd-config.sh

LMD_INSTALL="/usr/local/maldetect"
SAMPLES_DIR="/opt/tests/samples"
TEST_SCAN_DIR="/tmp/lmd-test-resource"

setup() {
    source /opt/tests/helpers/reset-lmd.sh
    mkdir -p "$TEST_SCAN_DIR"
}

teardown() {
    rm -rf "$TEST_SCAN_DIR"
}

@test "nice binary exists on system" {
    command -v nice
}

@test "ionice binary exists on system" {
    command -v ionice || skip "ionice not available on this OS"
}

@test "internals.conf discovers nice via command -v" {
    run grep 'nice=.*command -v nice' "$LMD_INSTALL/internals/internals.conf"
    assert_success
}

@test "internals.conf discovers ionice via command -v" {
    run grep 'ionice=.*command -v ionice' "$LMD_INSTALL/internals/internals.conf"
    assert_success
}

@test "scan_cpunice defaults to 19" {
    source "$LMD_INSTALL/conf.maldet"
    [ "$scan_cpunice" = "19" ]
}

@test "scan_ionice defaults to 6" {
    source "$LMD_INSTALL/conf.maldet"
    [ "$scan_ionice" = "6" ]
}

@test "scan reports nice scheduler priorities" {
    cp "$SAMPLES_DIR/clean-file.txt" "$TEST_SCAN_DIR/"
    run maldet -a "$TEST_SCAN_DIR"
    assert_success
    assert_output --partial "nice scheduler priorities"
}

@test "scan_cpulimit=0 means cpulimit disabled" {
    source "$LMD_INSTALL/conf.maldet"
    [ "$scan_cpulimit" = "0" ]
}

# scan_cpunice/scan_ionice/scan_cpulimit only wrap the clamdscan CLIENT
# process maldet spawns; the actual scanning CPU work runs inside the
# pre-existing clamd DAEMON over its socket, which those settings never
# touch. _clamd_apply_throttle()/_clamd_restore_throttle() close that gap by
# directly renicing (and, if configured, cpulimit-ing) the live clamd PID for
# the duration of maldet-triggered scans. These tests fake a "clamd" process
# via a symlink so pgrep -x clamd matches, without requiring ClamAV installed.

# Helper: source LMD config stack for unit-level function tests (mirrors
# _source_lmd_stack_clamav in tests/19-clamav.bats).
_source_lmd_stack_resource() {
    set +eu
    trap - ERR  # bash 5.1: BATS ERR trap leaks into sourced files even with set +e
    source "$LMD_INSTALL/internals/internals.conf"
    source "$LMD_INSTALL/conf.maldet"
    source "$LMD_INSTALL/internals/lmd.lib.sh"
}

# Spawns a `sleep` process whose comm name is "clamd" (via symlink + direct
# exec), so pgrep -x clamd finds it like a real daemon. Echoes "mockbin pid".
_spawn_mock_clamd() {
    local mockbin
    mockbin=$(mktemp -d)
    ln -s "$(command -v sleep)" "$mockbin/clamd"
    "$mockbin/clamd" 30 &
    local pid=$!
    sleep 0.2  # let the kernel settle comm name before pgrep -x reads it
    echo "$mockbin $pid"
}

@test "_clamd_apply_throttle renices the live clamd daemon PID, not just the client" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    if pgrep -x clamd >/dev/null 2>&1; then
        skip "a real clamd is already running on this host — would collide with mock"
    fi
    _source_lmd_stack_resource

    read -r mockbin mock_pid < <(_spawn_mock_clamd)
    tmpdir=$(mktemp -d)
    clamd=1
    scan_clamd_remote=""
    scan_cpunice=19
    scan_cpulimit=0

    _clamd_apply_throttle "unit-test-scan-throttle"
    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "19"

    kill "$mock_pid" 2>/dev/null
    rm -rf "$mockbin" "$tmpdir"
}

@test "_clamd_restore_throttle restores clamd's original nice level" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    if pgrep -x clamd >/dev/null 2>&1; then
        skip "a real clamd is already running on this host — would collide with mock"
    fi
    _source_lmd_stack_resource

    read -r mockbin mock_pid < <(_spawn_mock_clamd)
    tmpdir=$(mktemp -d)
    clamd=1
    scan_clamd_remote=""
    scan_cpunice=19
    scan_cpulimit=0

    local orig_nice
    orig_nice=$(ps -o ni= -p "$mock_pid" | tr -d ' ')

    _clamd_apply_throttle "unit-test-scan-restore"
    _clamd_restore_throttle "unit-test-scan-restore"

    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "$orig_nice"

    kill "$mock_pid" 2>/dev/null
    rm -rf "$mockbin" "$tmpdir"
}

@test "scan_clamd_cpulimit defaults to 50 and is independent from scan_cpulimit" {
    source "$LMD_INSTALL/conf.maldet"
    [ "${scan_clamd_cpulimit:-50}" = "50" ]
    # scan_cpulimit (client processes) stays disabled by default — the new
    # daemon-only setting must not change that existing semantic.
    [ "$scan_cpulimit" = "0" ]
}

@test "_clamd_apply_throttle uses renice absolute value, not relative" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    if pgrep -x clamd >/dev/null 2>&1; then
        skip "a real clamd is already running on this host — would collide with mock"
    fi
    _source_lmd_stack_resource

    read -r mockbin mock_pid < <(_spawn_mock_clamd)
    tmpdir=$(mktemp -d)
    clamd=1
    scan_clamd_remote=""
    scan_cpunice=19
    scan_cpulimit=0
    scan_clamd_cpulimit=0

    # renice(1)'s "-n" flag is absolute-or-relative depending on
    # POSIXLY_CORRECT (relative when set) — force that env var to make sure
    # the code path is exercised the same way a strict-POSIX shell would run
    # it, and assert the result still lands exactly on the configured value
    # rather than being added on top of clamd's starting nice level.
    POSIXLY_CORRECT=1 _clamd_apply_throttle "unit-test-scan-renice-absolute"
    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "19"

    _clamd_restore_throttle "unit-test-scan-renice-absolute"
    kill "$mock_pid" 2>/dev/null
    rm -rf "$mockbin" "$tmpdir"
}

@test "_clamd_apply_throttle's cpulimit watcher PID is real and killable (no -b double-fork orphan)" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    command -v cpulimit >/dev/null 2>&1 || skip "cpulimit not available"
    if pgrep -x clamd >/dev/null 2>&1; then
        skip "a real clamd is already running on this host — would collide with mock"
    fi
    _source_lmd_stack_resource

    read -r mockbin mock_pid < <(_spawn_mock_clamd)
    tmpdir=$(mktemp -d)
    clamd=1
    scan_clamd_remote=""
    scan_cpunice=19
    scan_cpulimit=0
    scan_clamd_cpulimit=50
    cpulimit=$(command -v cpulimit)

    _clamd_apply_throttle "unit-test-scan-cpulimit-pid"
    local recorded_pid
    recorded_pid=$(cat "$tmpdir/.clamd_throttle.cpulimit.pid")

    # The recorded PID must be a live cpulimit process actually watching our
    # mock clamd PID — "-b" would daemonize and orphan the real watcher
    # under a different, untracked PID, leaving this check failing.
    run bash -c "ps -o comm= -p $recorded_pid"
    assert_output --partial "cpulimit"
    run bash -c "kill -0 $recorded_pid 2>/dev/null && echo alive"
    assert_output "alive"

    # Killing the recorded PID must actually stop the watcher (proves it's
    # the real process, not a stale/forked-away PID).
    kill "$recorded_pid" 2>/dev/null
    sleep 0.3
    run bash -c "kill -0 $recorded_pid 2>/dev/null && echo alive || echo dead"
    assert_output "dead"

    _clamd_restore_throttle "unit-test-scan-cpulimit-pid"
    kill "$mock_pid" 2>/dev/null
    rm -rf "$mockbin" "$tmpdir"
}

@test "_clamd_apply_throttle's backgrounded cpulimit does not inherit/leak the flock fd" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    command -v cpulimit >/dev/null 2>&1 || skip "cpulimit not available"
    if pgrep -x clamd >/dev/null 2>&1; then
        skip "a real clamd is already running on this host — would collide with mock"
    fi
    _source_lmd_stack_resource

    read -r mockbin mock_pid < <(_spawn_mock_clamd)
    tmpdir=$(mktemp -d)
    clamd=1
    scan_clamd_remote=""
    scan_cpunice=19
    scan_cpulimit=0
    scan_clamd_cpulimit=50
    cpulimit=$(command -v cpulimit)

    _clamd_apply_throttle "unit-test-scan-fd-leak"
    _clamd_restore_throttle "unit-test-scan-fd-leak"

    # If the cpulimit child inherited the flock fd (201), it would hold the
    # exclusive lock open for its whole lifetime even after this restore
    # call's own subshell exited — deadlocking every future apply/restore
    # call. Confirm no process (in particular the just-spawned cpulimit
    # watcher, which restore should have already killed) still holds an
    # open fd on the lockfile.
    run bash -c "fuser \"$tmpdir/.clamd_throttle.lock\" 2>&1"
    refute_output --partial "cpulimit"

    # And a fresh apply/restore cycle must complete promptly (would hang up
    # to the flock timeout if the lock were still leaked/held).
    run timeout 5 bash -c "source '$LMD_INSTALL/internals/lmd.lib.sh'; true"
    _clamd_apply_throttle "unit-test-scan-fd-leak-2"
    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "19"
    _clamd_restore_throttle "unit-test-scan-fd-leak-2"

    kill "$mock_pid" 2>/dev/null
    rm -rf "$mockbin" "$tmpdir"
}

@test "_clamd_prune_dead_holders self-heals a stale marker left by a dead PID" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    if pgrep -x clamd >/dev/null 2>&1; then
        skip "a real clamd is already running on this host — would collide with mock"
    fi
    _source_lmd_stack_resource

    read -r mockbin mock_pid < <(_spawn_mock_clamd)
    tmpdir=$(mktemp -d)
    clamd=1
    scan_clamd_remote=""
    scan_cpunice=19
    scan_cpulimit=0
    scan_clamd_cpulimit=0

    local orig_nice
    orig_nice=$(ps -o ni= -p "$mock_pid" | tr -d ' ')

    # Simulate a stale holder marker left behind by a scan whose own cleanup
    # never ran (e.g. a lock-timeout/crash), embedding a definitely-dead PID
    # in the scanid, matching the real "date-time.PID" format.
    mkdir -p "$tmpdir/.clamd_throttle.holders"
    local dead_pid=999999
    while kill -0 "$dead_pid" 2>/dev/null; do dead_pid=$((dead_pid - 1)); done
    : > "$tmpdir/.clamd_throttle.holders/260925-0000.$dead_pid"

    # A brand-new scan applying the throttle must prune the dead marker as
    # part of becoming (what it thinks is) the first real holder — otherwise
    # the stale marker permanently blocks restore from ever seeing an empty
    # holders dir again.
    _clamd_apply_throttle "unit-test-scan-prune"
    run bash -c "ls '$tmpdir/.clamd_throttle.holders/'"
    refute_output --partial "$dead_pid"
    assert_output --partial "unit-test-scan-prune"

    _clamd_restore_throttle "unit-test-scan-prune"
    run bash -c "ls -A '$tmpdir/.clamd_throttle.holders/' 2>/dev/null"
    assert_output ""
    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "$orig_nice"

    kill "$mock_pid" 2>/dev/null
    rm -rf "$mockbin" "$tmpdir"
}

@test "_clamd_restore_throttle only restores once every concurrent holder has released" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    if pgrep -x clamd >/dev/null 2>&1; then
        skip "a real clamd is already running on this host — would collide with mock"
    fi
    _source_lmd_stack_resource

    read -r mockbin mock_pid < <(_spawn_mock_clamd)
    tmpdir=$(mktemp -d)
    clamd=1
    scan_clamd_remote=""
    scan_cpunice=19
    scan_cpulimit=0

    local orig_nice
    orig_nice=$(ps -o ni= -p "$mock_pid" | tr -d ' ')

    _clamd_apply_throttle "unit-test-scan-a"
    _clamd_apply_throttle "unit-test-scan-b"

    # Releasing one of two concurrent holders must not restore priority yet
    _clamd_restore_throttle "unit-test-scan-a"
    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "19"

    # Releasing the same holder again must be a harmless no-op (idempotent)
    _clamd_restore_throttle "unit-test-scan-a"
    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "19"

    # Releasing the last holder restores clamd's original priority
    _clamd_restore_throttle "unit-test-scan-b"
    run bash -c "ps -o ni= -p $mock_pid | tr -d ' '"
    assert_output "$orig_nice"

    kill "$mock_pid" 2>/dev/null
    rm -rf "$mockbin" "$tmpdir"
}

# _scan_throttle_worker_pid covers the native engine's own parallel batch
# workers (md5/sha256/hex-csig — see lmd_scan.sh), which spawn raw
# md5sum/sha256sum/grep/awk pipelines directly in the background and were
# never wrapped by $nice_command (that variable only works as an exec
# PREFIX for external binaries; it can't wrap an already-backgrounded bash
# function). Left unthrottled, up to 8 parallel workers can peg every core
# regardless of scan_cpunice/scan_cpulimit — this is the native-engine
# equivalent of the clamd-daemon-throttle gap fixed above.

@test "_scan_throttle_worker_pid renices an already-running worker PID" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    _source_lmd_stack_resource
    scan_cpunice=19
    scan_ionice=6
    scan_cpulimit=0

    sleep 30 &
    local worker_pid=$!

    _scan_throttle_worker_pid "$worker_pid"
    run bash -c "ps -o ni= -p $worker_pid | tr -d ' '"
    assert_output "19"

    kill "$worker_pid" 2>/dev/null
}

@test "_scan_throttle_worker_pid is a harmless no-op for an already-exited PID" {
    _source_lmd_stack_resource
    scan_cpunice=19
    scan_ionice=6
    scan_cpulimit=0

    sleep 0.01 &
    local dead_pid=$!
    wait "$dead_pid" 2>/dev/null

    run _scan_throttle_worker_pid "$dead_pid"
    assert_success
}

@test "_scan_throttle_worker_pid applies cpulimit to a worker PID when scan_cpulimit is set" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    command -v cpulimit >/dev/null 2>&1 || skip "cpulimit not available"
    _source_lmd_stack_resource
    scan_cpunice=19
    scan_ionice=6
    scan_cpulimit=50

    : > /tmp/lmd-test-worker-busy.flag
    bash -c 'while [ -f /tmp/lmd-test-worker-busy.flag ]; do :; done' &
    local worker_pid=$!

    _scan_throttle_worker_pid "$worker_pid"
    sleep 0.3
    # -m/--monitor-forks is required here: the worker's actual CPU-heavy
    # work (md5sum/sha256sum/grep/awk) runs in a forked child, not in the
    # worker's own PID — cpulimit -p alone (no -m) would silently watch
    # the wrong process and throttle nothing.
    run pgrep -f "cpulimit -p $worker_pid -l 50 -z -m"
    assert_success

    rm -f /tmp/lmd-test-worker-busy.flag
    wait "$worker_pid" 2>/dev/null
}

@test "lmd_scan.sh throttles md5/sha256/hex worker PIDs immediately after backgrounding" {
    run grep -c '_scan_throttle_worker_pid "\$!"' "$LMD_INSTALL/internals/lmd_scan.sh"
    assert_success
    [ "$output" -ge 3 ]
}

# The scan() orchestrator process itself (not just its md5/sha256/hex
# workers) does real CPU-bound work directly in its own bash interpreter
# (file list handling, worker chunk distribution/collection, hex/csig
# bookkeeping). It was previously left completely unthrottled even though
# the scan log claims "setting nice scheduler priorities for all
# operations" — only the spawned workers actually got that treatment.

@test "lmd_scan.sh throttles its own top-level scan process, not just workers" {
    run grep -c '_scan_throttle_worker_pid "\$_scan_pid" 0' "$LMD_INSTALL/internals/lmd_scan.sh"
    assert_success
    [ "$output" -ge 1 ]
}

@test "_scan_throttle_worker_pid renices the top-level scan PID like a worker PID" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    _source_lmd_stack_resource
    scan_cpunice=19
    scan_ionice=6
    scan_cpulimit=0

    sleep 30 &
    local scan_pid=$!

    _scan_throttle_worker_pid "$scan_pid" 0
    run bash -c "ps -o ni= -p $scan_pid | tr -d ' '"
    assert_output "19"

    kill "$scan_pid" 2>/dev/null
}

@test "_scan_throttle_worker_pid with monitor_forks=0 omits -m from cpulimit (no double-throttling descendants)" {
    command -v renice >/dev/null 2>&1 || skip "renice not available"
    command -v cpulimit >/dev/null 2>&1 || skip "cpulimit not available"
    _source_lmd_stack_resource
    scan_cpunice=19
    scan_ionice=6
    scan_cpulimit=50

    : > /tmp/lmd-test-scanproc-busy.flag
    bash -c 'while [ -f /tmp/lmd-test-scanproc-busy.flag ]; do :; done' &
    local scan_pid=$!

    _scan_throttle_worker_pid "$scan_pid" 0
    sleep 0.3
    # Unlike the worker-PID case (which needs -m since the worker's real
    # CPU-heavy work runs in a forked child), the top-level scan process's
    # own direct CPU usage is what we're targeting here — each of its
    # workers already gets its own independent -m watcher, so watching
    # descendants here too would throttle the same PIDs twice.
    run pgrep -f -- "cpulimit -p $scan_pid -l 50 -z -m"
    assert_failure
    run pgrep -f -- "cpulimit -p $scan_pid -l 50 -z\$"
    assert_success

    rm -f /tmp/lmd-test-scanproc-busy.flag
    wait "$scan_pid" 2>/dev/null
}
