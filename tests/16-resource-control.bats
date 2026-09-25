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
