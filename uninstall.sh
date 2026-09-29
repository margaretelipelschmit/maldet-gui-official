#!/usr/bin/env bash
##
# Linux Malware Detect v2.0.1
#             (C) 2002-2026, R-fx Networks <proj@rfxn.com>
#             (C) 2026, Ryan MacDonald <ryan@rfxn.com>
# This program may be freely redistributed under the terms of the GNU GPL v2
##
# uninstall.sh — interactive LMD removal (installed-path entry point)

export PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:$PATH
inspath=/usr/local/maldetect

# Source shared packaging library from install path
# shellcheck disable=SC1090,SC1091
source "$inspath/internals/pkg_lib.sh"

_preserve_quarantine() {
	local _source="$1" _root="$2" _backup _hist _copied=0 _has_history=0
	for _hist in "$_source"/sess/quarantine.hist*; do
		[ -f "$_hist" ] && _has_history=1
	done
	if [ ! -d "$_source/quarantine" ] && [ "$_has_history" -eq 0 ]; then
		return 0
	fi
	if [ -L "$_root" ]; then
		pkg_error "quarantine backup directory is a symlink: $_root"
		return 1
	fi
	if ! (umask 077; mkdir -p -- "$_root" && chmod 700 -- "$_root"); then
		pkg_error "could not create protected quarantine backup directory: $_root"
		return 1
	fi
	_backup=$(umask 077; mktemp -d "$_root/quarantine.XXXXXXXX") || {
		pkg_error "could not allocate quarantine backup in $_root"
		return 1
	}
	if [ -d "$_source/quarantine" ]; then
		if ! cp -a -- "$_source/quarantine" "$_backup/quarantine" ||
			! diff -qr -- "$_source/quarantine" "$_backup/quarantine" >/dev/null; then
			pkg_error "quarantine backup failed or did not match: $_backup"
			return 1
		fi
		_copied=1
	fi
	for _hist in "$_source"/sess/quarantine.hist*; do
		[ -f "$_hist" ] || continue
		if ! mkdir -p -- "$_backup/sess" ||
			! cp -a -- "$_hist" "$_backup/sess/" ||
			! cmp -s -- "$_hist" "$_backup/sess/${_hist##*/}"; then
			pkg_error "quarantine history backup failed or did not match: $_backup"
			return 1
		fi
		_copied=1
	done
	if [ "$_copied" -eq 1 ]; then
		pkg_item "Quarantine backup" "$_backup"
	fi
}

echo "This will remove Linux Malware Detect. Quarantined files will NOT be restored to their original locations."
if ! pkg_uninstall_confirm "Linux Malware Detect"; then
	echo "You selected No or provided an invalid confirmation, nothing has been done!"
	exit 0
fi

# Keep quarantined payloads isolated. Abort before stopping services or
# removing files if a verified backup cannot be made.
_preserve_quarantine "$inspath" /var/backups/maldetect || exit 1

# Stop any running monitor before cleanup
if [ "$(ps -A --user root -o "command" 2>/dev/null | grep maldetect | grep inotifywait)" ]; then
	/usr/local/sbin/maldet -k >>/dev/null 2>&1
fi

# Remove service (handles systemd, SysV, chkconfig, update-rc.d, etc.)
pkg_service_uninstall maldet
pkg_service_uninstall maldet-gui

pkg_uninstall_cron /etc/cron.d/maldet_pub /etc/cron.daily/maldet /etc/cron.weekly/maldet-watchdog

# Remove man page and symlink
pkg_uninstall_man 1 maldet
command rm -f /usr/local/share/man/man1/maldet.1.gz 2>/dev/null  # safe: symlink may not exist

pkg_symlink_cleanup /usr/local/sbin/maldet /usr/local/sbin/lmd /usr/local/sbin/maldet-gui /usr/local/sbin/maldet-webgui /usr/local/sbin/maldet-systray
command rm -f /usr/share/applications/maldet-systray.desktop /usr/share/applications/maldet-gui.desktop
if [ -n "${SUDO_USER:-}" ] && command -v getent >/dev/null 2>&1; then
	_uninstall_gui_home=$(getent passwd "$SUDO_USER" | cut -d: -f6)
	command rm -f "$_uninstall_gui_home/Desktop/Maldet WebGUI.desktop" \
		"$_uninstall_gui_home/Área de Trabalho/Maldet WebGUI.desktop"
fi

pkg_uninstall_sysconfig maldet

# Remove ClamAV signature symlinks (LMD-specific)
clamav_paths="/usr/local/cpanel/3rdparty/share/clamav/ /var/lib/clamav/ /var/clamav/ /usr/share/clamav/ /usr/local/share/clamav"
for cpath in $clamav_paths; do
	command rm -f "$cpath"/rfxn.* "$cpath"/lmd.user.* 2>/dev/null  # safe: files may not exist
done

# Remove the current installation only. Older installation backups may still
# contain quarantine data and must not be removed by a broad glob.
pkg_uninstall_files "$inspath"
if [ -e "$inspath" ]; then
	pkg_error "installation directory could not be removed: $inspath"
	exit 1
fi

pkg_success "Linux Malware Detect has been uninstalled."
