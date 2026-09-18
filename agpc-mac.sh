#!/bin/bash
# macOS AGPC bootstrap candidate. Native release is not yet available.
# Compatible with the system Bash 3.2. No system mutation before release admission.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: agpc-mac.sh [--plan | --check | --help]
Target: macOS 15+ on Apple Silicon (arm64).

  --plan   Display the installation phases without inspecting or changing a host.
  --check  Inspect prerequisites; requires sudo on a supported Mac.
  --help   Display this help.

This candidate has no admitted native release. Installation and --check exit 78
until one is available. It does not install services or change SSH configuration.
EOF
}

fail() { printf 'AGPC: %s\n' "$*" >&2; exit 1; }
phase() { printf '[%s/9] %s\n' "$1" "$2"; }

plan() {
    cat <<'EOF'
AGPC macOS bootstrap plan — native release pending
[1/9] Detecting macOS (15+, arm64)
[2/9] Checking prerequisites and authenticated native release
[3/9] Preparing AGPC directories (/opt/agpc; user state ~/.agpc)
[4/9] Configuring local SSH (loopback port 22; owner-managed launchd job)
[5/9] Installing Mote Transport (native artifacts)
[6/9] Installing AgentSphere / AGOS (native artifacts)
[7/9] Joining CX-Mesh (persistent node ID, LocalHostName-derived endpoint)
[8/9] Starting AGPC services (launchd; Codex runtime discovery)
[9/9] Running verification (fresh local and second-AGPC SSH sessions)

BLOCKED: No authenticated macOS arm64 AGPC release is pinned in this candidate.
Phases 3–9 are planned, not implemented. No installation can complete yet.
EOF
}

normalize_hostname() {
    # LocalHostName is a routing name, never shell input or a DNS dependency.
    local normalized
    normalized=$(printf '%s' "$1" | LC_ALL=C tr '[:upper:]' '[:lower:]' |
        LC_ALL=C sed -E 's/[^a-z0-9-]+/-/g; s/-+/-/g; s/^-//; s/-$//')
    [[ -n "$normalized" && ${#normalized} -le 63 ]] || return 1
    [[ "$normalized" != local ]] || return 1
    printf '%s\n' "$normalized"
}

platform_check() {
    [[ $(uname -s) == Darwin ]] || fail 'macOS is required; no changes made.'
    local version major
    version=$(sw_vers -productVersion) || fail 'Cannot determine macOS version.'
    major=${version%%.*}
    case "$major" in ''|*[!0-9]*) fail 'Invalid macOS version.' ;; esac
    [[ "$major" -ge 15 ]] || fail 'macOS 15 or newer is required.'
    [[ $(uname -m) == arm64 ]] || fail 'v0.1 requires native arm64; Intel and Rosetta shells are unsupported.'
    printf 'Platform: macOS %s / arm64\n' "$version"
}

preflight() {
    phase 1 'Detecting macOS'
    platform_check
    [[ $(id -u) == 0 ]] || fail 'Run with sudo on the target Mac for prerequisite inspection.'
    phase 2 'Checking prerequisites'
    local tool raw hostname free_kb remote_login listeners
    for tool in curl ssh sshd launchctl hostname scutil df awk sed tr lsof systemsetup; do
        command -v "$tool" >/dev/null 2>&1 || fail "Missing macOS prerequisite: $tool"
    done
    ssh -V 2>&1
    raw=$(scutil --get LocalHostName) || fail 'LocalHostName is unavailable.'
    hostname=$(normalize_hostname "$raw") || fail 'LocalHostName cannot form an unambiguous 1–63 character endpoint (local is reserved).'
    printf 'Proposed endpoint: %s.mote\n' "$hostname"

    # Preserve unknown installations. Upgrades require a release migration contract.
    if [[ -e /opt/agpc || -L /opt/agpc ]]; then
        fail 'Existing /opt/agpc detected; migration contract is required. Installation preserved.'
    fi
    free_kb=$(df -Pk / | awk 'NR == 2 {print $4}')
    case "$free_kb" in ''|*[!0-9]*) fail 'Cannot determine available disk space.' ;; esac
    [[ "$free_kb" -ge 2097152 ]] || fail 'At least 2 GiB of free space is required for bootstrap staging.'
    printf 'Disk space: %s KiB available (final requirement depends on release size).\n' "$free_kb"

    if remote_login=$(systemsetup -getremotelogin 2>&1); then
        printf 'Remote Login inspection: %s\n' "$remote_login"
    else
        printf 'Remote Login inspection unavailable: %s\n' "$remote_login" >&2
    fi
    # Remote Login being enabled does not prove loopback-only SSH.
    if listeners=$(lsof -nP -iTCP:22 -sTCP:LISTEN 2>&1); then
        printf 'Existing SSH listeners (not changed):\n%s\n' "$listeners"
    else
        printf 'No SSH listener confirmed; SSH readiness remains unverified.\n'
    fi
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 10 --max-time 30 --output /dev/null \
        https://motebus.github.io/download/agpc.sh || fail 'Official download endpoint is unreachable.'
    printf 'Network: official HTTPS download endpoint reachable.\n'
}

release_gate() {
    cat >&2 <<'EOF'
AGPC bootstrap BLOCKED (native-release-unavailable).
Required before installation:
  - Authenticated, immutable macOS arm64 artifacts and provenance.
  - Native runtime launch, configuration, enrollment and health contracts.
  - Mote host authorization and SSH ProxyCommand integration.
  - Codex App-Server discovery and per-user execution contract.
No system files, SSH settings, identities or launchd services were changed.
AGPC installation is NOT complete. Exit status: 78.
EOF
    return 78
}

main() {
    # Never execute tools from the invoking user's PATH under sudo.
    PATH=/usr/bin:/bin:/usr/sbin:/sbin
    export PATH LC_ALL=C
    [[ $# -le 1 ]] || { usage >&2; return 2; }
    case "${1:-}" in
        --help|-h) usage; return 0 ;;
        --plan) plan; return 0 ;;
        --check|'') preflight; release_gate ;;
        *) usage >&2; return 2 ;;
    esac
}

if [[ -z ${BASH_SOURCE[0]:-} || ${BASH_SOURCE[0]:-} == "$0" ]]; then
    main "$@"
fi
