#!/usr/bin/env bash
# YPCloud Voice-Mote bootstrap; package lifecycle belongs to APT.
set -Eeuo pipefail

usage() {
    cat <<'HELP'
YPCloud Voice-Mote bootstrap 0.1.0-bootstrap.3
Usage: sudo bash voice-mote.sh [--preview] [--yes] [--check] [--agpc-verify /absolute/path]
       bash voice-mote.sh --help | --version

Installs the voice-mote APT package on an existing Ubuntu AGPC.
--preview      Install the pinned preview.3 control runtime on Ubuntu 24.04 amd64.
               Requires installed AGPC; full live acceptance remains pending.
--check        Run prerequisites and cached APT simulation without installation.
--yes          Accept the APT transaction noninteractively.
--agpc-verify  Use an operator-provided, root-owned AGPC Ready checker.
               It takes no arguments; exit 0 must mean full live readiness.
Default: agpc-manager ready --json, requiring state=ready and live_verified=true.
A local-precheck or ready-with-gates result is insufficient.

Default mode requires existing trusted APT sources and a published voice-mote package.
Preview downloads a fixed SHA-256 release asset, then installs it through APT.
Authenticate this bootstrap before running it. Preview does not enable SIP/AI.
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

verify_preview_host() {
    [[ ${VERSION_ID:-} == 24.04 && $(dpkg --print-architecture) == amd64 ]] || die 'preview supports Ubuntu 24.04 amd64 only'
    [[ -s /etc/machine-id && -x /usr/bin/agpc-manager ]] || die 'existing AGPC identity and manager required'
    [[ $(dpkg-query -W -f='${Status}' agpc-manager 2>/dev/null) == 'install ok installed' ]] || die 'AGPC manager package is not installed'
    printf 'AGPC installed; full live readiness has not been established by this preview installer.\n'
}

prepare_preview() {
    command -v curl >/dev/null || die 'preview requires curl'
    local installed
    installed=$(dpkg-query -W -f='${Version}' voice-mote 2>/dev/null || true)
    if [[ -n $installed ]] && dpkg --compare-versions "$installed" gt '0.1.0~preview.3'; then
        die 'installed voice-mote is newer than this preview; refusing downgrade'
    fi
    preview_stage=$(mktemp -d /var/tmp/voice-mote.XXXXXXXX)
    trap 'rm -rf -- "$preview_stage"' EXIT
    package_target="$preview_stage/voice-mote.deb"
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 180 \
        'https://github.com/motebus/download/releases/download/voice-mote-v0.1.0-preview.3/voice-mote_0.1.0.preview.3_all.deb' -o "$package_target"
    printf '%s  %s\n' '3c8c5514637c6fdc23dff5173556796190546f47afe49948502e784bf36fac93' "$package_target" | sha256sum --check --status || die 'preview package checksum mismatch'
    [[ $(dpkg-deb -f "$package_target" Package) == voice-mote &&
       $(dpkg-deb -f "$package_target" Version) == '0.1.0~preview.3' &&
       $(dpkg-deb -f "$package_target" Architecture) == all ]] || die 'unexpected preview package metadata'
    chmod 0755 "$preview_stage"
    chmod 0644 "$package_target"
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
    if ${preview:-false}; then
        prepare_preview
    else
    candidate=$(LC_ALL=C apt-cache policy voice-mote)
    if ! printf '%s\n' "$candidate" | python3 -c '
import re, sys
m = re.search(r"^\s*Candidate:\s*(\S+)\s*$", sys.stdin.read(), re.M)
sys.exit(0 if m and m[1] != "(none)" else 1)
'; then
        die 'voice-mote package unavailable; configure its trusted repository or wait for the runtime package release'
    fi
    fi
    apt-get "${apt_options[@]}" --simulate --no-remove install "${package_target:-voice-mote}"
    if $check_only; then
        printf 'Prerequisites and cached package plan checked; installation and Voice-Mote capability remain unverified.\n'
        return
    fi
    if $assume_yes; then apt_options+=(-y); fi
    apt-get "${apt_options[@]}" --no-remove install "${package_target:-voice-mote}"
    [[ -x /usr/bin/voice-mote ]] || die 'package installation completed but /usr/bin/voice-mote is missing'
    if ${preview:-false}; then
        [[ $(dpkg-query -W -f='${Status} ${Version}' voice-mote) == 'install ok installed 0.1.0~preview.3' ]] || die 'installed preview version mismatch'
        systemctl is-active --quiet voice-moted || die 'preview installed but voice-moted is not active'
        printf 'Voice-Mote preview.3 installed; voice-moted running. SIP/AI setup and full capability verification remain pending.\n'
        return
    fi
    if ! /usr/bin/voice-mote verify; then
        die 'package installation completed; Voice-Mote capability verification did not pass'
    fi
    printf 'Voice-Mote installation and capability verification completed.\n'
}

main() {
    local agpc_verify='' assume_yes=false check_only=false preview=false package_target=voice-mote
    preview_stage=''
    export PATH=/usr/sbin:/usr/bin:/sbin:/bin
    while (($#)); do
        case "$1" in
            --help|-h) usage; return ;;
            --version) printf '0.1.0-bootstrap.3\n'; return ;;
            --agpc-verify)
                (($# >= 2)) && [[ $2 == /* ]] || die '--agpc-verify requires an absolute executable path'
                agpc_verify=$2; shift 2 ;;
            --preview) preview=true; shift ;;
            --yes) assume_yes=true; shift ;;
            --check) check_only=true; shift ;;
            *) die "unknown argument: $1" ;;
        esac
    done
    platform_check
    if $preview; then
        [[ -z $agpc_verify ]] || die '--preview and --agpc-verify are separate installation contracts'
        verify_preview_host
    else
        verify_agpc
    fi
    install_voice
}

# Bash reading from stdin has no BASH_SOURCE entry. Sourcing still defines functions only.
if [[ ${BASH_SOURCE[0]:-$0} == "$0" ]]; then main "$@"; fi
