#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf '%s\n' \
        'Usage: agent-sphere-apps.sh [--yes] [--help]' \
        'Install agent-sphere and agent-apps using the configured signed MoteBus APT repository.' \
        'Downloads the pinned official Obsidian DEB for the same APT transaction.' \
        'Run as root. APT asks for confirmation unless --yes is supplied.'
}
fail() { printf '%s\n' "$*" >&2; exit 1; }
confirmation=()
for arg in "$@"; do
    case "$arg" in
        --yes) confirmation=(--yes) ;;
        --help) usage; exit 0 ;;
        *) printf 'Unsupported argument: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done
[[ $(id -u) == 0 ]] || fail 'Run this installer as root (for example, with sudo).'
for command in apt-get curl sha256sum dpkg dpkg-deb dpkg-query mktemp chmod realpath stat; do
    command -v "$command" >/dev/null 2>&1 || fail "$command is required. Package installation was not started."
done
[[ $(dpkg --print-architecture) == amd64 ]] || fail 'This reviewed release requires amd64.'
export LC_ALL=C

# Retention is only valid for an existing locked conffile ownership record.
# Classify before downloads or APT; a package-name match alone is insufficient.
legacy_retention=false
legacy_record=''
if legacy_record=$(dpkg-query -W -f='${db:Status-Status}\n${Version}\n${Conffiles}\n' mote-chatd 2>/dev/null); then
    mapfile -t legacy_lines <<< "$legacy_record"
    [[ ${#legacy_lines[@]} -ge 2 ]] || fail 'Cannot classify legacy mote-chatd ownership. No download or package change was started.'
    case "${legacy_lines[0]}" in
        installed|config-files) ;;
        *) fail 'Unsupported legacy mote-chatd DPKG state. Repair it before using this installer; no download or package change was started.' ;;
    esac
    [[ -n ${legacy_lines[1]} ]] && dpkg --compare-versions "${legacy_lines[1]}" le 2.0.0-6 \
        || fail 'Unsupported legacy mote-chatd version. No download or package change was started.'
    ownership_count=0
    for legacy_line in "${legacy_lines[@]:2}"; do
        read -r record_path record_digest record_flag record_extra <<< "$legacy_line"
        if [[ $record_path == /etc/mote/mote-chatd/mote-chatd-mchat.env ]]; then
            [[ $record_digest =~ ^[0-9a-f]{32}$ && -z $record_extra && \
               ( -z $record_flag || $record_flag == obsolete ) ]] \
                || fail 'Malformed protected mote-chatd ownership record. No download or package change was started.'
            ownership_count=$((ownership_count + 1))
        fi
    done
    [[ $ownership_count == 1 ]] \
        || fail 'Existing mote-chatd does not have the exact protected ownership required for retention. This state needs a separately reviewed migration; no download or package change was started.'
    [[ $(stat -c '%F' -- /etc/mote/mote-chatd/mote-chatd-mchat.env 2>/dev/null) == 'regular file' ]] \
        || fail 'The protected legacy topology is missing or not a regular file. Owner repair is required; no download or package change was started.'
    legacy_retention=true
else
    query_status=$?
    [[ $query_status == 1 && -z $legacy_record ]] \
        || fail 'Cannot inspect legacy mote-chatd ownership. No download or package change was started.'
fi

umask 077
temporary=$(mktemp -d /var/tmp/agent-sphere-apps.XXXXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
obsidian="$temporary/obsidian_1.13.7_amd64.deb"
curl --fail --location --proto '=https' --proto-redir '=https' --retry 2 \
    --output "$obsidian" \
    https://github.com/obsidianmd/obsidian-releases/releases/download/v1.13.7/obsidian_1.13.7_amd64.deb
printf '%s  %s\n' 17dc33b49cb3e785ecc27edd2ea0c79e40207798b554fd2886e36ebee7af9ae0 "$obsidian" | sha256sum --check --status \
    || fail 'Official Obsidian checksum mismatch. Package installation was not started.'
[[ $(dpkg-deb -f "$obsidian" Package) == obsidian && \
   $(dpkg-deb -f "$obsidian" Version) == 1.13.7 && \
   $(dpkg-deb -f "$obsidian" Architecture) == amd64 ]] \
    || fail 'Official Obsidian package metadata mismatch. Package installation was not started.'
chmod 0755 "$temporary"
chmod 0644 "$obsidian"
packages=(agent-sphere=0.1.0-6 agent-apps=0.1.0-2 "$obsidian")
# Preserve DPKG ownership of the locked legacy identity with the reviewed
# documentation-only record. Never remove the mote-chatd record.
if $legacy_retention; then
    packages+=(mote-chatd=2.0.0-6)
fi

# APT protocol v3 is checked again under APT's lock before any DPKG action.
cat > "$temporary/guard" <<'GUARD'
#!/bin/bash
set -euo pipefail
fail() { printf 'Agent Computer transaction refused: %s\n' "$*" >&2; exit 1; }
[[ ${APT_HOOK_INFO_FD:-} == 0 ]] || fail 'APT action protocol is unavailable'
IFS= read -r header || fail 'empty action protocol'
[[ $header == 'VERSION 3' ]] || fail 'APT action protocol version 3 is required'
config_end=false
while IFS= read -r line; do
    if [[ -z $line ]]; then config_end=true; break; fi
    [[ $line == *=* ]] || fail 'malformed APT configuration record'
done
$config_end || fail 'incomplete APT action protocol'
declare -A removed=() installed=() configured=()
declare -A replacement=([mote-sync]=mote-vault-sync [mote-syncd]=mote-vault-syncd [cx-node]=cx-agent [model-node]=model-llm)
declare -A reviewed_old=([mote-sync]=1.1.0-2 [mote-syncd]=1.1.0-2 [cx-node]=0.3.4-1~local20260909 [model-node]=0.1.0-2)
declare -A floor=([agent-sphere]=0.1.0-6 [agent-apps]=0.1.0-2 [moted]=3.6.0-2 [medge]=3.0.0-2 [mlink]=2.1.0-1 [mote-transportd]=2.0.0-6 [mote-chatd]=2.0.0-6 [agos]=2.0.0-2 [cx-agent]=0.3.4-2 [model-router]=0.1.0-1 [model-llm]=0.1.0-3 [mote-vault-sync]=1.1.0-3 [mote-vault-syncd]=1.1.0-3)
while IFS= read -r line; do
    read -r -a fields <<< "$line"
    [[ ${#fields[@]} == 9 ]] || fail 'malformed package action'
    name=${fields[0]}; old=${fields[1]}; direction=${fields[4]}
    new=${fields[5]}; action=${fields[8]}
    [[ $name =~ ^[a-z0-9][a-z0-9+.-]*$ ]] || fail 'invalid package name'
    [[ $direction == '<' || $direction == '=' || $direction == '>' ]] || fail 'invalid version action'
    if [[ $action == '**REMOVE**' ]]; then
        [[ -n ${replacement[$name]:-} && $old == "${reviewed_old[$name]}" && $new == - && -z ${removed[$name]:-} ]] || fail "removal of $name"
        removed[$name]=true
    elif [[ $action == '**CONFIGURE**' || $action == /*.deb ]]; then
        case "$name" in mote-sync|mote-syncd|cx-node|model-node|model-grid|mcp-run|ultra-mcp-ssh) fail "retired package $name" ;; esac
        [[ $new != - ]] || fail 'missing target version'
        [[ $old == - ]] || dpkg --compare-versions "$new" ge "$old" || fail "downgrade of $name"
        if [[ -n ${floor[$name]:-} ]]; then
            dpkg --compare-versions "$new" ge "${floor[$name]}" || fail "obsolete package $name"
        fi
        if [[ $name == agent-sphere || $name == agent-apps ]]; then
            [[ $new == "${floor[$name]}" ]] || fail "unexpected composition version $name"
        fi
        if [[ $action == /*.deb ]]; then
            [[ -z ${installed[$name]:-} ]] || fail "duplicate installation $name"
            installed[$name]=$new
            if [[ $name == obsidian ]]; then
                [[ $new == 1.13.7 && ! -L $action && -f $action ]] || fail 'unexpected Obsidian artifact'
                printf '%s  %s\n' 17dc33b49cb3e785ecc27edd2ea0c79e40207798b554fd2886e36ebee7af9ae0 "$action" | sha256sum --check --status || fail 'Obsidian artifact changed'
            fi
        else
            [[ -z ${configured[$name]:-} ]] || fail "duplicate configuration $name"
            configured[$name]=$new
        fi
    else
        fail 'unknown package action'
    fi
done
for name in "${!removed[@]}"; do
    [[ -n ${installed[${replacement[$name]}]:-} ]] || fail "$name removal lacks its reviewed replacement"
done
GUARD
chmod 0700 "$temporary/guard"
guard=$(realpath "$temporary/guard")
[[ $guard =~ ^/[a-zA-Z0-9_./-]+$ ]] || fail 'Invalid temporary hook path.'
apt-get update || fail 'APT update failed. Package installation was not started.'
if ! apt-get --simulate install "${packages[@]}" > "$temporary/plan"; then
    cat "$temporary/plan"
    fail 'Both packages and their dependencies must be available in the signed MoteBus APT repository. Package installation was not started.'
fi
cat "$temporary/plan"
declare -A removed=() planned=()
while read -r action package rest; do
    name=${package%%:*}
    case "$action" in
        Remv)
            case "$name:$rest" in
                'mote-sync:[1.1.0-2]'*) removed[mote-sync]=mote-vault-sync ;;
                'mote-syncd:[1.1.0-2]'*) removed[mote-syncd]=mote-vault-syncd ;;
                'cx-node:[0.3.4-1~local20260909]'*) removed[cx-node]=cx-agent ;;
                'model-node:[0.1.0-2]'*) removed[model-node]=model-llm ;;
                *) fail "Refusing package removal: $name. Package installation was not started." ;;
            esac ;;
        Purg|E:) fail 'APT error or purge refused. Package installation was not started.' ;;
        Inst) planned[$name]=true ;;
    esac
done < "$temporary/plan"
for name in "${!removed[@]}"; do
    [[ -n ${planned[${removed[$name]}]:-} ]] || fail "$name removal lacks its replacement. Package installation was not started."
done
apt-get -o "DPkg::Pre-Install-Pkgs::=$guard" \
    -o "DPkg::Tools::Options::$guard::Version=3" \
    -o "DPkg::Tools::Options::$guard::InfoFD=0" \
    -o 'Dpkg::Options::=--force-confold' \
    "${confirmation[@]}" install "${packages[@]}"
printf '%s\n' 'Agent Sphere and Agent Apps packages installed. Runtime configuration and health are separate checks.'
