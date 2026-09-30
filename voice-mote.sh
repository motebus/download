#!/usr/bin/env bash
# YPCloud Voice-Mote bootstrap; package lifecycle belongs to APT.
set -Eeuo pipefail

usage() {
    cat <<'HELP'
YPCloud Voice-Mote bootstrap 0.1.0-bootstrap.1
Usage: sudo bash voice-mote.sh [--yes] [--check] [--agpc-verify /absolute/path]
       bash voice-mote.sh --help | --version

Installs the voice-mote APT package on an existing Ubuntu AGPC.
--check        Run prerequisites and cached APT simulation without installation.
--yes          Accept the APT transaction noninteractively.
--agpc-verify  Use an operator-provided, root-owned AGPC Ready checker.
               It takes no arguments; exit 0 must mean full live readiness.
Default: agpc-manager ready --json, requiring state=ready and live_verified=true.
A local-precheck or ready-with-gates result is insufficient.

Requires existing trusted APT sources and a published voice-mote package.
This bootstrap release does not include the voice-moted runtime or provision
SIP, model credentials, policy, a new identity, or AGPC itself.
Package installation alone is not Voice-Mote Ready.
HELP
}

die() { printf 'voice-mote bootstrap: %s\n' "$*" >&2; exit 1; }

trusted_checker() {
    python3 - "$1" <<'PY'
import os, pathlib, stat, sys
p = pathlib.Path(sys.argv[1])
if not p.is_absolute():
    raise SystemExit('AGPC checker requires an absolute path')
for item in (p, *p.parents):
    s = item.lstat()
    if stat.S_ISLNK(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
        raise SystemExit('AGPC checker and parent directories must be root-owned, non-writable by others, and not symlinks')
if not p.is_file() or not os.access(p, os.X_OK):
    raise SystemExit('AGPC checker is not executable')
PY
}

validate_ready_report() {
    python3 -c '
import json, sys
try:
    r = json.load(sys.stdin)
    ok = (isinstance(r, dict) and r.get("state") == "ready" and
          r.get("live_verified") is True and r.get("scope") != "local-precheck")
except (ValueError, TypeError):
    ok = False
if not ok:
    raise SystemExit("Full live AGPC readiness is required; local-precheck is insufficient. Use --agpc-verify with the approved acceptance checker.")
'
}

verify_agpc() {
    if [[ -n $agpc_verify ]]; then
        trusted_checker "$agpc_verify" || die 'untrusted AGPC checker'
        timeout --kill-after=5s 120s "$agpc_verify" || die 'AGPC Ready verification failed or timed out'
    else
        [[ -x /usr/bin/agpc-manager ]] || die 'AGPC manager missing; install and verify AGPC first'
        local report
        if ! report=$(timeout --kill-after=5s 60s /usr/bin/agpc-manager ready --json); then
            die 'AGPC readiness command failed; complete AGPC acceptance first'
        fi
        printf '%s' "$report" | validate_ready_report || die 'AGPC Ready not established'
    fi
}

platform_check() {
    ((EUID == 0)) || die 'run with sudo'
    [[ -r /etc/os-release ]] || die 'cannot identify operating system'
    # shellcheck source=/dev/null
    . /etc/os-release
    [[ ${ID:-} == ubuntu ]] || die 'Ubuntu Linux is required'
    [[ -d /run/systemd/system ]] || die 'a running systemd host is required'
    for command in apt-get apt-cache dpkg python3 timeout; do
        command -v "$command" >/dev/null || die "missing command: $command"
    done
}

install_voice() {
    local audit candidate
    audit=$(dpkg --audit) || die 'dpkg audit failed'
    [[ -z $audit ]] || die 'incomplete dpkg state; resolve it before installation'
    apt-get check
    local apt_options=(
        -o APT::Get::AllowUnauthenticated=false
        -o Acquire::AllowInsecureRepositories=false
        -o Acquire::AllowDowngradeToInsecureRepositories=false
        -o Acquire::AllowWeakRepositories=false
        -o APT::Get::allow-Downgrades=false
    )
    if ! $check_only; then
        apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update
    fi
    candidate=$(LC_ALL=C apt-cache policy voice-mote)
    if ! printf '%s\n' "$candidate" | python3 -c '
import re, sys
m = re.search(r"^\s*Candidate:\s*(\S+)\s*$", sys.stdin.read(), re.M)
sys.exit(0 if m and m[1] != "(none)" else 1)
'; then
        die 'voice-mote package unavailable; configure its trusted repository or wait for the runtime package release'
    fi
    apt-get "${apt_options[@]}" --simulate --no-remove install voice-mote
    if $check_only; then
        printf 'Prerequisites and cached package plan checked; installation and Voice-Mote capability remain unverified.\n'
        return
    fi
    if $assume_yes; then apt_options+=(-y); fi
    apt-get "${apt_options[@]}" --no-remove install voice-mote
    [[ -x /usr/bin/voice-mote ]] || die 'package installation completed but /usr/bin/voice-mote is missing'
    if ! /usr/bin/voice-mote verify; then
        die 'package installation completed; Voice-Mote capability verification did not pass'
    fi
    printf 'Voice-Mote installation and capability verification completed.\n'
}

main() {
    local agpc_verify='' assume_yes=false check_only=false
    export PATH=/usr/sbin:/usr/bin:/sbin:/bin
    while (($#)); do
        case "$1" in
            --help|-h) usage; return ;;
            --version) printf '0.1.0-bootstrap.1\n'; return ;;
            --agpc-verify)
                (($# >= 2)) && [[ $2 == /* ]] || die '--agpc-verify requires an absolute executable path'
                agpc_verify=$2; shift 2 ;;
            --yes) assume_yes=true; shift ;;
            --check) check_only=true; shift ;;
            *) die "unknown argument: $1" ;;
        esac
    done
    platform_check
    verify_agpc
    install_voice
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
