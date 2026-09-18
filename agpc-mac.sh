#!/bin/bash
# macOS AGPC Docker bootstrap preview.4; the AGPC runtime is not yet available.
# Compatible with system Bash 3.2. Docker setup is the only implemented installation.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: agpc-mac.sh [--plan | --check | --install-docker | --help]
Target: macOS 14+ on Apple Silicon (arm64).

  --plan   Display the installation phases without inspecting or changing a host.
  --check  Inspect prerequisites; requires sudo on a supported Mac.
  --install-docker  Install/start official Docker Desktop; no AGPC install.
  --help   Display this help.

The Ubuntu 26.04 AGPC OCI runtime is not admitted yet. Default execution installs/starts
Docker Desktop before stopping at the runtime gate. Installation and --check exit 78
until one is available. It does not install AGPC services or change SSH configuration.
EOF
}

fail() { printf 'AGPC: %s\n' "$*" >&2; exit 1; }
phase() { printf '[%s/9] %s\n' "$1" "$2"; }

plan() {
    cat <<'EOF'
AGPC macOS bootstrap plan — Ubuntu 26.04 OCI release pending
[1/9] Detecting macOS (14+, arm64)
[2/9] Checking prerequisites, installing Docker Desktop, checking Ubuntu 26.04 OCI release
[3/9] Preparing AGPC directories (/opt/agpc; user state ~/.agpc)
[4/9] Configuring local SSH (loopback port 22; owner-managed launchd job)
[5/9] Installing Mote Transport (Ubuntu OCI / DEBs)
[6/9] Installing AgentSphere / AGOS (Ubuntu OCI / DEBs)
[7/9] Joining CX-Mesh (persistent node ID, LocalHostName-derived endpoint)
[8/9] Starting Ubuntu services; connecting Mac-host Codex App-Server
[9/9] Running verification (fresh local and second-AGPC SSH sessions)

BLOCKED: No authenticated Ubuntu 26.04 AGPC OCI runtime is pinned in this candidate.
Phases 3–9 are planned, not implemented. AGPC installation cannot complete yet.
Default execution installs/starts Docker Desktop after preflight.
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
    [[ "$major" -ge 14 ]] || fail 'macOS 14 or newer is required.'
    [[ $(uname -m) == arm64 ]] || fail 'v0.1 requires native arm64; Intel and Rosetta shells are unsupported.'
    printf 'Platform: macOS %s / arm64\n' "$version"
}

# Official Docker Desktop 4.91.0 (Apple Silicon), checked 2026-09-18.
DOCKER_APP=/Applications/Docker.app
DOCKER_BIN=$DOCKER_APP/Contents/Resources/bin/docker
DOCKER_DMG_URL=https://desktop.docker.com/mac/main/arm64/239619/Docker.dmg
DOCKER_DMG_SHA256=31a324e8f72acf178c9f5d46cd71240705541faa69827588813e539d29c7e859

mac_owner() {
    OWNER=${SUDO_USER:-$(id -un)}
    [[ "$OWNER" != root && "$OWNER" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] ||
        fail 'Run from an ordinary Mac login account using sudo.'
    OWNER_UID=$(id -u "$OWNER")
    [[ "$OWNER_UID" -ge 501 ]] || fail 'An ordinary Mac login account is required.'
    OWNER_HOME=$(dscl . -read "/Users/$OWNER" NFSHomeDirectory | sed 's/^NFSHomeDirectory: //')
    [[ "$OWNER_HOME" == /Users/* && -d "$OWNER_HOME" ]] || fail 'Cannot resolve the Mac login home.'
}

as_mac_owner() {
    if [[ $(id -u) == 0 ]]; then
        sudo -H -u "$OWNER" /usr/bin/env -i HOME="$OWNER_HOME" USER="$OWNER" \
            PATH=/usr/bin:/bin:/usr/sbin:/sbin "$@"
    else
        "$@"
    fi
}

docker_info() {
    as_mac_owner "$DOCKER_BIN" --context desktop-linux info >/dev/null 2>&1
}

verify_docker_digest() {
    local actual
    actual=$(shasum -a 256 "$1") || return 1
    [[ ${actual%% *} == "$DOCKER_DMG_SHA256" ]] || {
        printf '%s\n' 'Docker Desktop checksum mismatch; installer will not run.' >&2
        return 1
    }
}

version_at_least() {
    local actual=$1 required=$2 a b c x y z
    [[ "$actual" =~ ^[0-9]+(\.[0-9]+){0,2}$ && "$required" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] || return 1
    IFS=. read -r a b c <<< "$actual"
    IFS=. read -r x y z <<< "$required"
    a=$((10#$a)); b=$((10#${b:-0})); c=$((10#${c:-0}))
    x=$((10#$x)); y=$((10#${y:-0})); z=$((10#${z:-0}))
    (( a > x || (a == x && b > y) || (a == x && b == y && c >= z) ))
}

install_docker_desktop() (
    [[ $(id -u) == 0 ]] || fail 'Docker installation requires sudo.'
    [[ ! -e "$DOCKER_APP" && ! -L "$DOCKER_APP" ]] || fail 'Existing Docker.app is incomplete or differs; preserved for repair.'
    local temporary mounted=0 minimum
    temporary=$(mktemp -d /private/tmp/agpc-docker.XXXXXXXX)
    cleanup_docker() {
        local result=$?
        if [[ "$mounted" == 1 ]]; then
            if ! hdiutil detach "$temporary/mount" -quiet; then
                printf 'Docker volume could not be detached: %s\n' "$temporary/mount" >&2
                exit 1
            fi
        fi
        rm -f "$temporary/Docker.dmg"
        rmdir "$temporary/mount" "$temporary" 2>/dev/null || true
        exit "$result"
    }
    trap cleanup_docker EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    mkdir "$temporary/mount"
    printf '%s\n' 'Downloading verified Docker Desktop 4.91.0 for Apple Silicon.'
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 20 --max-time 1800 --retry 3 \
        --output "$temporary/Docker.dmg" "$DOCKER_DMG_URL"
    verify_docker_digest "$temporary/Docker.dmg"
    hdiutil attach "$temporary/Docker.dmg" -readonly -nobrowse -mountpoint "$temporary/mount" -quiet
    mounted=1
    codesign --verify --deep --strict "$temporary/mount/Docker.app"
    spctl --assess --type execute "$temporary/mount/Docker.app"
    minimum=$(plutil -extract LSMinimumSystemVersion raw "$temporary/mount/Docker.app/Contents/Info.plist")
    version_at_least "$(sw_vers -productVersion)" "$minimum" || fail "This Docker build requires macOS $minimum. No unsupported install was attempted."
    # Preserve Docker's interactive license and authorization flow on first launch.
    "$temporary/mount/Docker.app/Contents/MacOS/install" --user="$OWNER"
    [[ -x "$DOCKER_BIN" ]] || fail 'Docker installer returned without a usable Docker CLI.'
)

wait_for_docker() {
    local attempt
    for ((attempt=0; attempt<60; attempt++)); do
        if docker_info; then return 0; fi
        if (( attempt % 6 == 0 )); then
            printf '%s\n' 'Waiting for Docker Desktop. Complete any setup, license or authorization dialog on the Mac.'
        fi
        sleep 5
    done
    printf '%s\n' 'Docker Desktop is not ready. Complete its Mac setup and rerun; installation is preserved.' >&2
    return 1
}

ensure_docker_desktop() {
    if [[ ! -x "$DOCKER_BIN" ]]; then install_docker_desktop; fi
    if docker_info; then
        printf '%s\n' 'Existing Docker Desktop is ready; preserved.'
        return 0
    fi
    # Launch in the owner's existing GUI session, not in the root session.
    launchctl print "gui/$OWNER_UID" >/dev/null 2>&1 || fail 'Log in to the Mac desktop as the installation owner, then rerun.'
    launchctl asuser "$OWNER_UID" sudo -H -u "$OWNER" /usr/bin/open -a "$DOCKER_APP"
    wait_for_docker
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
AGPC bootstrap BLOCKED (ubuntu-oci-release-unavailable).
Required before installation:
  - Authenticated, immutable Ubuntu 26.04 AGPC OCI image and provenance.
  - Container lifecycle: default Docker systemd cannot write /init.scope cgroup.
  - Runtime configuration, enrollment and health checks.
  - Authorized container-to-Mac SSH transport and ProxyCommand integration.
  - Integration of the tested CX-Mesh host adapter with Mac launchd and runtime.
No AGPC services or SSH changes were applied. Docker Desktop may have been installed or started.
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
        --check) preflight; release_gate ;;
        --install-docker) platform_check; mac_owner; ensure_docker_desktop ;;
        '') preflight; mac_owner; ensure_docker_desktop; release_gate ;;
        *) usage >&2; return 2 ;;
    esac
}

if [[ -z ${BASH_SOURCE[0]:-} || ${BASH_SOURCE[0]:-} == "$0" ]]; then
    main "$@"
fi
