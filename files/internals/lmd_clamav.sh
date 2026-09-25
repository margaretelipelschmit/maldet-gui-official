#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC1090,SC1091
##
# Linux Malware Detect v2.0.1
#             (C) 2002-2026, R-fx Networks <proj@rfxn.com>
#             (C) 2026, Ryan MacDonald <ryan@rfxn.com>
# This program may be freely redistributed under the terms of the GNU GPL v2
##
# ClamAV integration — engine selection, validation, and sig deployment

# Source guard
[[ -n "${_LMD_CLAMAV_LOADED:-}" ]] && return 0 2>/dev/null
_LMD_CLAMAV_LOADED=1

# _clamav_validate_sigs staging_dir — validate ClamAV can load staged sig files; returns 0 on pass/absent
# shellcheck disable=SC2034
_clamav_validate_sigs() {
	local _staging="$1"
	local _clamscan_bin=""
	_clamav_validate_err=""
	_clamav_validate_rc=""
	# Self-contained binary discovery — does not depend on clamselector()
	if [ -f "/usr/local/cpanel/3rdparty/bin/clamscan" ]; then
		_clamscan_bin="/usr/local/cpanel/3rdparty/bin/clamscan"
	else
		_clamscan_bin=$(command -v clamscan 2>/dev/null) # may be empty if clamscan not installed
	fi
	if [ -z "$_clamscan_bin" ]; then
		# No clamscan available — skip validation, degrade to current behavior
		return 0
	fi
	# Use a real temp file as scan target — /dev/null causes exit 2 on some
	# ClamAV versions that reject device files ("Not supported file type")
	local _scan_target
	_scan_target=$(mktemp "$tmpdir/.clamval_target.XXXXXX")
	# Test database loading: -d loads only from staging dir
	# No --quiet: we need the error output for diagnostics
	_clamav_validate_err=$("$_clamscan_bin" -d "$_staging" --no-summary "$_scan_target" 2>&1)
	_clamav_validate_rc=$?
	command rm -f "$_scan_target"
	if [ "$_clamav_validate_rc" -ne 0 ]; then
		return 1
	fi
	return 0
}

clamav_unlinksigs() {
	# Remove LMD signature files from all ClamAV data directories.
	# Called when ClamAV scanning is disabled to clean stale artifacts.
	# Also removes local sigdir symlinks to runtime files.
	local _cpath
	for _cpath in $clamav_paths; do
		if [ -d "$_cpath" ]; then
			command rm -f "$_cpath"/rfxn.{hdb,ndb,yara,hsb} 2>/dev/null
			command rm -f "$_cpath"/lmd.user.* 2>/dev/null
		fi
	done
	command rm -f "$sigdir/lmd.user.ndb" "$sigdir/lmd.user.hdb" "$sigdir/lmd.user.hsb" 2>/dev/null
}

clamav_linksigs() {
	local cpath="$1"
	local _log_ctx="${2:-sigup}"  # caller passes "scan" or "sigup"
	if [ -d "$cpath" ]; then
		local _staging
		_staging=$(mktemp -d "$tmpdir/.clamval.XXXXXX")
		if [ -z "$_staging" ] || [ ! -d "$_staging" ]; then
			eout "{$_log_ctx} ERROR: mktemp staging dir failed for ClamAV path $cpath — skipping" 1
			return 1
		fi
		# Stage sig files into temp dir (same conditional logic as before)
		# HEX (.ndb) and YARA always seeded regardless of hash mode
		command cp -f "$sigdir"/rfxn.ndb "$_staging"/ 2>/dev/null
		command cp -f "$sigdir"/rfxn.yara "$_staging"/ 2>/dev/null
		# MD5 hash sigs (.hdb) — only when effective hashtype includes md5
		if [ "$_effective_hashtype" != "sha256" ]; then
			command cp -f "$sigdir/rfxn.hdb" "$_staging"/ 2>/dev/null
		fi
		# SHA-256 hash sigs (.hsb) — only when effective hashtype includes sha256
		# and ClamAV >= 0.97 (avoids "Malformed database" on CentOS 6)
		if [ "$_effective_hashtype" != "md5" ] && [ -n "$_clamav_supports_hsb" ] \
		   && [ -f "$sigdir/rfxn.hsb" ] && [ -s "$sigdir/rfxn.hsb" ]; then
			command cp -f "$sigdir/rfxn.hsb" "$_staging"/ 2>/dev/null
		fi
		# User-supplied sigs (only if non-empty)
		[ -s "$sigdir/lmd.user.ndb" ] && command cp -f "$sigdir/lmd.user.ndb" "$_staging"/ 2>/dev/null
		if [ "$_effective_hashtype" != "sha256" ] && [ -s "$sigdir/lmd.user.hdb" ]; then
			command cp -f "$sigdir/lmd.user.hdb" "$_staging"/ 2>/dev/null
		fi
		if [ "$_effective_hashtype" != "md5" ] && [ -n "$_clamav_supports_hsb" ] \
		   && [ -s "$sigdir/lmd.user.hsb" ]; then
			command cp -f "$sigdir/lmd.user.hsb" "$_staging"/ 2>/dev/null
		fi
		# Validate staged sigs before deploying to ClamAV path
		if _clamav_validate_sigs "$_staging"; then
			# Validation passed — deploy to ClamAV path
			command rm -f "$cpath"/rfxn.{hdb,ndb,yara,hsb} 2>/dev/null
			command rm -f "$cpath"/lmd.user.* 2>/dev/null
			command cp -f "$_staging"/* "$cpath"/ 2>/dev/null
			# Signatures deployed to partner scanner paths must be 644 —
			# scanner daemons run as non-root and need read access
			for _sf in "$cpath"/rfxn.* "$cpath"/lmd.user.*; do
				[ -f "$_sf" ] || continue
				command chmod 644 "$_sf" 2>/dev/null  # enforce world-readable for scanner daemon
			done
			# Match ownership to ClamAV data dir when it runs as non-root
			local _cpath_owner _cpath_group
			if [ "$os_freebsd" == "1" ]; then
				_cpath_owner=$(stat -f '%Su' "$cpath" 2>/dev/null)
				_cpath_group=$(stat -f '%Sg' "$cpath" 2>/dev/null)
			else
				_cpath_owner=$(stat -c '%U' "$cpath" 2>/dev/null)
				_cpath_group=$(stat -c '%G' "$cpath" 2>/dev/null)
			fi
			if [ -n "$_cpath_owner" ] && [ "$_cpath_owner" != "root" ]; then
				for _sf in "$cpath"/rfxn.* "$cpath"/lmd.user.*; do
					[ -f "$_sf" ] || continue
					command chown "${_cpath_owner}:${_cpath_group}" "$_sf" 2>/dev/null
				done
			fi
			command rm -rf "$_staging"
			return 0
		else
			# Validation failed — protect ClamAV by removing LMD sigs
			command rm -f "$cpath"/rfxn.{hdb,ndb,yara,hsb} 2>/dev/null
			command rm -f "$cpath"/lmd.user.* 2>/dev/null
			local _err_detail=""
			if [ -n "$_clamav_validate_err" ]; then
				# First non-empty line of clamscan output
				_err_detail=$(echo "$_clamav_validate_err" | grep -m1 '.')
			fi
			if [ -n "$_err_detail" ]; then
				eout "{$_log_ctx} clamav signature validation failed for $cpath (rc=$_clamav_validate_rc): $_err_detail" 1
			else
				eout "{$_log_ctx} clamav signature validation failed for $cpath (rc=$_clamav_validate_rc)" 1
			fi
			command rm -rf "$_staging"
			return 1
		fi
	fi
}

_clamscan_fallback() {
	clambin="clamscan"
	local _hash_db_opts=""
	[ -n "$runtime_hdb" ] && _hash_db_opts="-d $runtime_hdb"
	[ -n "$runtime_hsb" ] && [ -s "$runtime_hsb" ] && _hash_db_opts="$_hash_db_opts -d $runtime_hsb"
	clamopts="$clamscan_extraopts --max-filesize=$clamscan_max_filesize --max-scansize=$((clamscan_max_filesize * 2)) $_hash_db_opts -d $runtime_ndb $clamav_db -r"
	if [ -f "/usr/local/cpanel/3rdparty/bin/$clambin" ]; then
		clamscan="/usr/local/cpanel/3rdparty/bin/$clambin"
	elif [ -f "$(command -v $clambin 2> /dev/null)" ]; then
		clamscan=$(command -v $clambin 2> /dev/null)
	else
		scan_clamscan="0"
	fi
}

clamselector() {
	sig_max_filesize=$(cut -d':' -f2 "$sig_md5_file" | sort -n | tail -n1)
	if [ -f "$sig_sha256_file" ] && [ -s "$sig_sha256_file" ]; then
		local _sha256_max
		_sha256_max=$(cut -d':' -f2 "$sig_sha256_file" | sort -n | tail -n1)
		if [ "$_sha256_max" -gt "$sig_max_filesize" ] 2>/dev/null; then
			sig_max_filesize="$_sha256_max"
		fi
	fi
	if [ "$sig_max_filesize" -gt "1" ] 2>/dev/null; then
		clamscan_max_filesize=$((sig_max_filesize+1))
	else
		clamscan_max_filesize="2592000"
	fi

	# Detect ClamAV version for .hsb support (SHA-256 hash DB, ClamAV >= 0.97)
	_clamav_supports_hsb=""

	if [ "$scan_clamscan" == "1" ]; then
		trim_log $clamscan_log 10000 1
		for dpath in $clamav_paths; do
			if [ -f "${dpath}/main.cld" ] || [ -f "${dpath}/main.cvd" ]; then
				clamav_db="-d $dpath"
			fi
		done

		isclamd=$(pgrep -x clamd 2> /dev/null)
		isclamd_root=$(pgrep -x -u root clamd 2> /dev/null)
		if [ "$scan_clamd_remote" == "1" ] && [ -f "$remote_clamd_config" ]; then
			clamd=1
			clambin="clamdscan"
			clamopts="-c $remote_clamd_config"
		elif [ "$isclamd" ] && [ "$isclamd_root" ]; then
			clamd=1
			clambin="clamdscan"
			clamopts="$clamdscan_extraopts"
		elif [ "$isclamd" ] && [ ! "$isclamd_root" ]; then
			clamd=1
			clambin="clamdscan"
			clamopts="--fdpass $clamdscan_extraopts"
		else
			_clamscan_fallback
			if [ "$monitor_mode" ]; then
				inotify_sleep="120"
				eout "{mon} warning clamd service not running; force-set monitor mode file scanning to every 120s"
			fi

		fi

		if [ "$clamd" ]; then
			if [ -f "/usr/local/cpanel/3rdparty/bin/$clambin" ]; then
				clamscan="/usr/local/cpanel/3rdparty/bin/$clambin"
			elif [ -f "$(command -v $clambin 2> /dev/null)" ]; then
				clamscan=$(command -v $clambin 2> /dev/null)
			else
				scan_clamscan="0"
			fi
		fi
		if [ "$clamd" ] && [ "$scan_clamscan" == "1" ]; then
			## test clamdscan for errors as not all 'running' instances of clamd are indicative of working setup
			if [ "$scan_clamd_remote" == "1" ] && [ -f "$remote_clamd_config" ]; then
				try=0
				while [ $try -le $remote_clamd_max_retry ]; do
					clamd_test=$($clamscan $clamopts --quiet --no-summary /etc/passwd 2> /dev/null || echo $?)
					if [ "$clamd_test" = "2" ]; then
						((try++))
						sleep $remote_clamd_retry_sleep
					else
						break
					fi
				done
			else
				clamd_test=$($clamscan --fdpass --quiet --no-summary /etc/passwd 2> /dev/null || echo $?)
			fi
			if [ -n "$clamd_test" ]; then
				if [ "$scan_clamd_remote" == "1" ]; then
					eout "{scan} warning: remote clamd test failed (rc=$clamd_test), falling back to local clamscan" 1
				else
					eout "{scan} warning: local clamd test failed (rc=$clamd_test), falling back to clamscan" 1
				fi
				clamd=0
				_clamscan_fallback
			fi
		fi
	fi

	# Detect ClamAV version for .hsb support gate
	if [ "$scan_clamscan" == "1" ]; then
		local _clam_ver_bin
		_clam_ver_bin="${clamscan:-$(command -v clamscan 2>/dev/null)}"
		if [ -n "$_clam_ver_bin" ]; then
			local _clam_ver
			_clam_ver=$("$_clam_ver_bin" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
			if [ -n "$_clam_ver" ]; then
				local _clam_major _clam_minor
				_clam_major="${_clam_ver%%.*}"
				_clam_minor="${_clam_ver#*.}"
				if [ "$_clam_major" -gt 0 ] 2>/dev/null || { [ "$_clam_major" -eq 0 ] && [ "$_clam_minor" -ge 97 ]; } 2>/dev/null; then
					_clamav_supports_hsb=1
				fi
			fi
		fi
	fi
}

# _clamd_prune_dead_holders holdersdir — remove any holder marker whose
# scanid-embedded PID (the numeric suffix after the last '.') is no longer
# alive. Self-heals cases where a scan's own cleanup never ran (e.g. a race
# between two scans finishing within the same flock window, a SIGKILL that
# bypassed the trap, or a crash) — without this, a single stale marker would
# permanently hold clamd throttled since the refcount would never reach zero
# again on its own.
_clamd_prune_dead_holders() {
	local _holdersdir="$1" _marker _pid
	[ -d "$_holdersdir" ] || return 0
	for _marker in "$_holdersdir"/*; do
		[ -e "$_marker" ] || continue
		_pid="${_marker##*.}"
		if [ -z "$_pid" ] || ! [ "$_pid" -gt 0 ] 2>/dev/null || ! kill -0 "$_pid" 2>/dev/null; then
			command rm -f "$_marker" 2>/dev/null
		fi
	done
}

# _clamd_apply_throttle scanid — deprioritize the shared clamd DAEMON for the
# duration of maldet-triggered scans. scan_cpunice/scan_ionice/scan_cpulimit
# only wrap the clamdscan CLIENT process maldet spawns (via $nice_command);
# the actual file-scanning CPU work happens inside the pre-existing clamd
# daemon over its socket, which is otherwise completely unthrottled and can
# peg CPU cores regardless of those settings.
#
# renice alone only affects scheduling PRIORITY: on a host with idle cores it
# does nothing to cap clamd's absolute usage, so it can still show 100% of a
# core in top/htop during a scan even while correctly niced. scan_clamd_cpulimit
# (percentage of one core, independent from scan_cpulimit which governs the
# clamdscan/clamscan/find/yara CLIENT processes) is what actually caps clamd's
# real usage, via periodic SIGSTOP/SIGCONT cycling done by the cpulimit binary
# — defaults to 50 so this is capped out of the box even if unset in an older
# conf.maldet, but an explicit scan_clamd_cpulimit="0" disables the cap.
#
# Tracked via one marker file per holding scanid (not a bare counter) so that
# releasing the same scanid's hold twice — e.g. once from a killed scan's own
# _scan_cleanup trap and once from _lifecycle_kill's own restore call, since a
# background scan's process-group TERM/KILL race means the trap is not
# guaranteed to run to completion — is a no-op instead of corrupting the
# refcount for other, still-running, concurrent scans.
_clamd_apply_throttle() {
	local _scanid="$1"
	[ -n "$_scanid" ] || return 0
	[ "$clamd" ] || return 0
	[ "$scan_clamd_remote" == "1" ] && return 0  # remote clamd — nothing local to throttle
	command -v flock >/dev/null 2>&1 || return 0  # best-effort only
	command -v renice >/dev/null 2>&1 || return 0

	local _lockfile="$tmpdir/.clamd_throttle.lock"
	local _holdersdir="$tmpdir/.clamd_throttle.holders"
	local _nicefile="$tmpdir/.clamd_throttle.orig_nice"
	local _cpulimitpidfile="$tmpdir/.clamd_throttle.cpulimit.pid"
	local _clamd_pid
	_clamd_pid=$(pgrep -x clamd 2>/dev/null | head -n1)
	[ -n "$_clamd_pid" ] || return 0
	local _clamd_cpulimit="${scan_clamd_cpulimit:-50}"

	(
		flock -x -w 15 201 || exit 0
		command mkdir -p "$_holdersdir" 2>/dev/null
		_clamd_prune_dead_holders "$_holdersdir"
		if [ -z "$(command ls -A "$_holdersdir" 2>/dev/null)" ]; then
			# First holder — capture original priority and apply the throttle.
			# Defensively reap any cpulimit watcher orphaned by a prior crashed
			# or ungracefully-killed scan before starting a fresh one; running
			# two concurrent watchers against the same PID is what caused
			# clamd to be left permanently stuck in a stopped (T) state during
			# testing (each watcher independently SIGSTOP/SIGCONT's clamd with
			# no coordination between them).
			pkill -f "cpulimit .*-p $_clamd_pid( |$)" >/dev/null 2>&1
			kill -CONT "$_clamd_pid" >/dev/null 2>&1  # in case an orphan left it stopped
			local _orig_nice
			_orig_nice=$(ps -o ni= -p "$_clamd_pid" 2>/dev/null | tr -d ' ')
			[ -n "$_orig_nice" ] || _orig_nice=0
			echo "$_orig_nice" > "$_nicefile"
			if [ "$scan_cpunice" ] && [ "$scan_cpunice" -gt "$_orig_nice" ] 2>/dev/null; then
				# Absolute priority: renice's "-n" flag is relative under
				# POSIXLY_CORRECT, so pass the value bare (unambiguously
				# absolute per renice(1)) instead of "-n $scan_cpunice".
				renice "$scan_cpunice" -p "$_clamd_pid" >/dev/null 2>&1
			fi
			if [ -n "$cpulimit" ] && [ -f "$cpulimit" ] && [ "$_clamd_cpulimit" -gt 0 ] 2>/dev/null; then
				# No "-b": that flag makes cpulimit double-fork/daemonize,
				# so "$!" below would capture the short-lived forking
				# parent's PID, not the real long-running watcher — leaving
				# an untracked, unkillable orphan once the scan ends. Instead
				# we background it ourselves via "&", which keeps "$!"
				# pointing at the actual watcher process.
				#
				# "201>&-" closes the inherited flock fd in this long-lived
				# child before it execs: without it, cpulimit keeps fd 201
				# (the exclusive lock on $_lockfile) open for its entire
				# lifetime — a lock is held per open file description, not
				# per process, so every future apply/restore call would
				# block on flock until this watcher exits, deadlocking
				# cleanup indefinitely (observed in testing: markers and
				# orphaned cpulimit processes piled up forever because
				# _clamd_restore_throttle could never re-acquire the lock).
				"$cpulimit" -p "$_clamd_pid" -l "$_clamd_cpulimit" -z >/dev/null 2>&1 201>&- &
				disown 2>/dev/null
				echo "$!" > "$_cpulimitpidfile"
			fi
		fi
		: > "$_holdersdir/$_scanid"
	) 201>"$_lockfile"
}

# _clamd_restore_throttle scanid — release this scan's hold on the shared
# clamd throttle. Only when no holder markers remain does clamd's original
# nice level get restored and the cpulimit watcher stopped. Safe to call more
# than once for the same scanid (idempotent) and safe to call for a scanid
# that never held the throttle (no-op).
_clamd_restore_throttle() {
	local _scanid="$1"
	[ -n "$_scanid" ] || return 0
	command -v flock >/dev/null 2>&1 || return 0
	local _lockfile="$tmpdir/.clamd_throttle.lock"
	local _holdersdir="$tmpdir/.clamd_throttle.holders"
	local _nicefile="$tmpdir/.clamd_throttle.orig_nice"
	local _cpulimitpidfile="$tmpdir/.clamd_throttle.cpulimit.pid"
	[ -d "$_holdersdir" ] || return 0

	(
		flock -x -w 15 201 || exit 0
		command rm -f "$_holdersdir/$_scanid" 2>/dev/null
		_clamd_prune_dead_holders "$_holdersdir"
		if [ -z "$(command ls -A "$_holdersdir" 2>/dev/null)" ]; then
			local _orig_nice _clamd_pid
			_clamd_pid=$(pgrep -x clamd 2>/dev/null | head -n1)
			if [ -f "$_cpulimitpidfile" ]; then
				local _cpid
				_cpid=$(cat "$_cpulimitpidfile" 2>/dev/null)
				[ -n "$_cpid" ] && kill "$_cpid" 2>/dev/null
				command rm -f "$_cpulimitpidfile"
			fi
			# Belt-and-suspenders: also reap by command-line match, in case
			# the tracked PID was stale, and unconditionally SIGCONT clamd —
			# harmless if it's already running, but guarantees it can never
			# be left permanently stopped by a watcher that exited mid-cycle.
			[ -n "$_clamd_pid" ] && pkill -f "cpulimit .*-p $_clamd_pid( |$)" >/dev/null 2>&1
			[ -n "$_clamd_pid" ] && kill -CONT "$_clamd_pid" >/dev/null 2>&1
			_orig_nice=$(cat "$_nicefile" 2>/dev/null)
			if [ -n "$_clamd_pid" ] && [ -n "$_orig_nice" ] && command -v renice >/dev/null 2>&1; then
				# Absolute priority: see the matching note in
				# _clamd_apply_throttle for why "-n" is intentionally omitted.
				renice "$_orig_nice" -p "$_clamd_pid" >/dev/null 2>&1
			fi
			command rm -f "$_nicefile" 2>/dev/null
			command rmdir "$_holdersdir" 2>/dev/null  # safe: no-op if concurrently repopulated
		fi
	) 201>"$_lockfile"
}

_clamd_retry_scan() {
	local _filelist="$1" _results="${2:-$clamscan_results}" _pid_file="${3:-}"
	if [ "$scan_clamd_remote" == "1" ] && [ -f "$remote_clamd_config" ]; then
		local try=0
		while [ $try -le $remote_clamd_max_retry ]; do
			if [ -n "$_pid_file" ]; then
				# Launch with PID capture for lifecycle management
				$nice_command $clamscan $clamopts --infected --no-summary -f "$_filelist" > "$_results" 2>> "$clamscan_log" &
				echo "$!" > "$_pid_file"
				wait "$!"
				clamscan_return=$?
			else
				$nice_command $clamscan $clamopts --infected --no-summary -f "$_filelist" > "$_results" 2>> "$clamscan_log"
				clamscan_return=$?
			fi
			if [ "$clamscan_return" == "2" ]; then
				((try++))
				echo "$(date +"%b %d %H:%M:%S") $(hostname -s) remote clamd error - retrying in $remote_clamd_retry_sleep seconds ($try)" >> "$clamscan_log"
				command sleep "$remote_clamd_retry_sleep"
			else
				break
			fi
		done
	else
		if [ -n "$_pid_file" ]; then
			# Launch with PID capture for lifecycle management
			$nice_command $clamscan $clamopts --infected --no-summary -f "$_filelist" > "$_results" 2>> "$clamscan_log" &
			echo "$!" > "$_pid_file"
			wait "$!"
			clamscan_return=$?
		else
			$nice_command $clamscan $clamopts --infected --no-summary -f "$_filelist" > "$_results" 2>> "$clamscan_log"
			clamscan_return=$?
		fi
	fi
}

# shellcheck disable=SC2154
_process_clamav_hits() {
	local _results="$1" _progress="$2"
	local _clam_manifest _signame _file
	local _yara_prefix="{YARA}"
	_clam_manifest=$(mktemp "$tmpdir/.clam_manifest.$$.XXXXXX")

	# Parse clamscan output → filepath\tsigname manifest
	while IFS=: read -r _signame _file; do
		if [[ "$_signame" == *YARA* ]]; then
			_signame="${_signame/YARA./$_yara_prefix}"
		elif [[ "$_signame" != *HEX* ]] && [[ "$_signame" != *MD5* ]]; then
			_signame="{CAV}$_signame"
		fi
		[ -f "$_file" ] && printf '%s\t%s\n' "$_file" "$_signame"
	done < <(grep -E -v 'ERROR$|lstat\(\)|no reply from clamd' "$_results" \
		| sed -e 's/.UNOFFICIAL//' -e 's/ FOUND$//' \
		| sed -n 's/^\(.*\): \(.*\)$/\2:\1/p') > "$_clam_manifest"

	# Bulk ignore_sigs filter
	_batch_filter_ignore_sigs "$_clam_manifest"

	_scan_progress "clamav" "processing hits"
	_flush_hit_batch "$_clam_manifest" "clamav"
	command rm -f "$_clam_manifest"
}
