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

# One classifier is used before downloads and again under APT's lock.
# It reads package metadata and hook bytes, never topology values.
classify_legacy_chatd() {
    local record query_status state version line path digest flag extra
    local protected=0 normal=0 other=0 identity hook expected actual
    local target=/etc/mote/mote-chatd/mote-chatd-mchat.env
    legacy_error() {
        printf '%s\n' "$1" 'Inspect mote-chatd Status, Version, Architecture and Conffiles with dpkg-query; do not print topology values or force package removal.' >&2
        return 1
    }
    if record=$(dpkg-query -W -f='${db:Status-Status}\n${Version}\n${Conffiles}\n' mote-chatd 2>/dev/null); then
        local -a lines
        mapfile -t lines <<< "$record"
        [[ ${#lines[@]} -ge 2 ]] || { legacy_error 'Cannot classify legacy mote-chatd ownership.'; return 1; }
        state=${lines[0]}; version=${lines[1]}
        case "$state" in installed|config-files) ;; *) legacy_error 'Unsupported legacy mote-chatd DPKG state; repair the incomplete transaction first.'; return 1 ;; esac
        [[ -n $version ]] && dpkg --compare-versions "$version" le 2.0.0-6 \
            || { legacy_error 'Unsupported legacy mote-chatd version.'; return 1; }
        for line in "${lines[@]:2}"; do
            [[ -n ${line//[[:space:]]/} ]] || continue
            read -r path digest flag extra <<< "$line"
            [[ $digest =~ ^[0-9a-f]{32}$ && -z $extra && ( -z $flag || $flag == obsolete ) ]] \
                || { legacy_error 'Malformed legacy mote-chatd conffile record.'; return 1; }
            case "$path" in
                "$target") protected=$((protected + 1)) ;;
                /etc/mote/mote-chatd/mote-chatd-deb.env) normal=$((normal + 1)) ;;
                *) other=$((other + 1)) ;;
            esac
        done
        [[ $(stat -c '%F' -- "$target" 2>/dev/null) == 'regular file' ]] \
            || { legacy_error 'Existing legacy topology is missing or not a regular file; owner repair is required.'; return 1; }
        local target_access target_uid target_mode
        target_access=$(stat -c '%u:%a' -- "$target") || { legacy_error 'Cannot inspect topology access metadata.'; return 1; }
        target_uid=${target_access%%:*}; target_mode=${target_access#*:}
        [[ $target_uid == 0 && $target_mode =~ ^[0-7]{3,4}$ ]] && (( (8#$target_mode & 0022) == 0 )) \
            || { legacy_error 'Existing topology must be root-owned and not writable by group or others.'; return 1; }
        if [[ $protected == 1 ]]; then
            printf 'retention:%s\n' "$state"
            return 0
        fi
        [[ $protected == 0 && $normal == 1 && $other == 0 && $version == 2.0.0-4 ]] \
            || { legacy_error 'Legacy ownership does not match a supported retention or ordinary 2.0.0-4 migration.'; return 1; }
        identity=$(dpkg-query -W -f='${Architecture}\n${Status}' mote-chatd 2>/dev/null) \
            || { legacy_error 'Cannot inspect legacy package identity.'; return 1; }
        case "$identity" in
            $'amd64\ninstall ok installed'|$'amd64\ndeinstall ok config-files') ;;
            *) legacy_error 'Ordinary migration requires the reviewed amd64 package in a complete DPKG state.'; return 1 ;;
        esac
        # The ordinary release never owns the locked file. Its removal hooks
        # are pinned so custom or unknown cleanup logic cannot enter this path.
        for hook in postrm prerm; do
            [[ $hook != prerm || $state == installed ]] || continue
            case "$hook" in
                postrm) expected=cad515185035337dd03da926ff380a1cf5a47fd074b6ff7f8525f7d7d1384196 ;;
                prerm) expected=a583a5e196cab7845800d8bade6cca1b1e86db9d077e2749d24ce7ad3b224085 ;;
            esac
            path=/var/lib/dpkg/info/mote-chatd.$hook
            [[ $(stat -c '%u:%g:%a:%F' -- "$path" 2>/dev/null) == '0:0:755:regular file' ]] \
                || { legacy_error "Legacy $hook has unsupported ownership, mode or file type."; return 1; }
            actual=$(sha256sum "$path") || { legacy_error "Cannot inspect legacy $hook."; return 1; }
            [[ ${actual%% *} == "$expected" ]] \
                || { legacy_error "Legacy $hook differs from the reviewed 2.0.0-4 release."; return 1; }
        done
        printf 'ordinary:%s\n' "$state"
    else
        query_status=$?
        [[ $query_status == 1 && -z $record ]] \
            || { legacy_error 'Cannot inspect legacy mote-chatd ownership.'; return 1; }
        printf 'absent\n'
    fi
}
legacy_state=$(classify_legacy_chatd) || fail 'Legacy preflight failed. No download or package change was started.'

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
packages=(agent-sphere=0.1.0-8 agent-apps=0.1.0-2 "$obsidian")
# Preserve DPKG ownership of the locked legacy identity with the reviewed
# documentation-only record. Never remove a protected mote-chatd record.
if [[ $legacy_state == retention:* ]]; then
    packages+=(mote-chatd=2.0.0-6)
elif [[ $legacy_state == ordinary:* ]]; then
    # An installed old name otherwise makes APT prefer its newer retention
    # candidate. Explicitly select the reviewed normal replacement path.
    packages+=(mote-chatd-)
fi

# APT protocol v3 is checked again under APT's lock before any DPKG action.
{
printf '%s\n' '#!/bin/bash' 'set -euo pipefail'
declare -f classify_legacy_chatd
printf 'expected_legacy_state=%q\n' "$legacy_state"
cat <<'GUARD'
fail() { printf 'Agent Computer transaction refused: %s\n' "$*" >&2; exit 1; }
legacy_state=$(classify_legacy_chatd) || fail 'legacy ownership is unsupported at transaction time'
[[ $legacy_state == "$expected_legacy_state" ]] || fail 'legacy ownership changed after preflight'
[[ ${APT_HOOK_INFO_FD:-} == 0 ]] || fail 'APT action protocol is unavailable'
IFS= read -r header || fail 'empty action protocol'
[[ $header == 'VERSION 3' ]] || fail 'APT action protocol version 3 is required'
config_end=false
while IFS= read -r line; do
    if [[ -z $line ]]; then config_end=true; break; fi
    [[ $line == *=* ]] || fail 'malformed APT configuration record'
done
$config_end || fail 'incomplete APT action protocol'
declare -A removed=() installed=() configured=() artifacts=()
public_cx_migration=false
declare -A replacement=([mote-sync]=mote-vault-sync [mote-syncd]=mote-vault-syncd [cx-node]=cx-agent [model-node]=model-llm)
declare -A reviewed_old=([mote-sync]=1.1.0-2 [mote-syncd]=1.1.0-2 [cx-node]=0.3.4-1~local20260909 [model-node]=0.1.0-2)
if [[ $legacy_state == ordinary:installed ]]; then
    replacement[mote-chatd]=mote-transportd
    reviewed_old[mote-chatd]=2.0.0-4
fi
declare -A floor=([agent-sphere]=0.1.0-8 [agent-apps]=0.1.0-2 [moted]=3.6.0-2 [medge]=3.0.0-3 [mlink]=2.1.0-1 [mote-transportd]=2.0.0-6 [mote-chatd]=2.0.0-6 [agos]=2.0.0-2 [cx-agent]=0.3.4-2 [model-router]=0.1.0-1 [model-llm]=0.1.0-3 [mote-vault-sync]=1.1.0-3 [mote-vault-syncd]=1.1.0-3)
while IFS= read -r line; do
    read -r -a fields <<< "$line"
    [[ ${#fields[@]} == 9 ]] || fail 'malformed package action'
    name=${fields[0]}; old=${fields[1]}; direction=${fields[4]}
    new=${fields[5]}; action=${fields[8]}
    [[ $name =~ ^[a-z0-9][a-z0-9+.-]*$ ]] || fail 'invalid package name'
    [[ $direction == '<' || $direction == '=' || $direction == '>' ]] || fail 'invalid version action'
    if [[ $action == '**REMOVE**' ]]; then
        if [[ $name == cx-node && $old == 0.3.3-6 ]]; then
            cx_record=$(dpkg-query -W -f='${Version}|${Architecture}|${Status}|${Conffiles}' cx-node 2>/dev/null) || fail 'cannot inspect legacy CX package'
            [[ $cx_record == '0.3.3-6|amd64|install ok installed|' ]] || fail 'unreviewed legacy CX package state'
            for hook in prerm postrm; do
                case "$hook" in
                    prerm) expected=5a07af360b9e229fad483ba3ada220d81636f0a145ad38550542f9324432dfc3 ;;
                    postrm) expected=fc2ae1c462331eeb4c7a93eee8b27012120ca620baf6d91dd4b2e714b39c2f99 ;;
                esac
                path=/var/lib/dpkg/info/cx-node.$hook
                [[ $(stat -c '%u:%g:%a:%F' -- "$path" 2>/dev/null) == '0:0:755:regular file' ]] || fail "unsafe legacy CX $hook"
                actual=$(sha256sum "$path") || fail "cannot inspect legacy CX $hook"
                [[ ${actual%% *} == "$expected" ]] || fail "unreviewed legacy CX $hook"
            done
            if [[ -e /etc/cx-node/cx-node.toml || -L /etc/cx-node/cx-node.toml ]]; then
                [[ -f /etc/cx-node/cx-node-mchat.env && ! -L /etc/cx-node/cx-node-mchat.env ]] || fail 'existing CX configuration requires intact MCHAT identity'
            fi
            reviewed_old[cx-node]=0.3.3-6
            public_cx_migration=true
        fi
        [[ -n ${replacement[$name]:-} && $old == "${reviewed_old[$name]}" && $new == - && -z ${removed[$name]:-} ]] || fail "removal of $name"
        removed[$name]=true
    elif [[ $action == '**CONFIGURE**' || $action == /*.deb ]]; then
        [[ $name != mote-chatd || $legacy_state == retention:* ]] || fail 'retention is not admitted for this ownership state'
        case "$name" in mote-sync|mote-syncd|cx-node|model-node|model-grid|mcp-run|ultra-mcp-ssh) fail "retired package $name" ;; esac
        [[ $new != - ]] || fail 'missing target version'
        [[ $old == - ]] || dpkg --compare-versions "$new" ge "$old" || fail "downgrade of $name"
        if [[ -n ${floor[$name]:-} ]]; then
            dpkg --compare-versions "$new" ge "${floor[$name]}" || fail "obsolete package $name"
        fi
        if [[ $name == agent-sphere || $name == agent-apps ]]; then
            [[ $new == "${floor[$name]}" ]] || fail "unexpected composition version $name"
        fi
        if [[ $name == mote-transportd && $legacy_state == ordinary:* ]]; then
            [[ $new == 2.0.0-6 && ${fields[6]} == amd64 ]] || fail 'ordinary migration requires exact transport 2.0.0-6 amd64'
            if [[ $action == /*.deb ]]; then
                [[ ! -L $action && -f $action ]] || fail 'unsafe transport artifact'
                printf '%s  %s\n' 9c56cade3f014f75876cce126d2ef8c9d5c27a60709ff592ac0e9af9788dd23f "$action" | sha256sum --check --status || fail 'transport artifact changed'
            fi
        fi
        if [[ $action == /*.deb ]]; then
            [[ -z ${installed[$name]:-} ]] || fail "duplicate installation $name"
            installed[$name]=$new
            artifacts[$name]=$action
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
if $public_cx_migration; then
    [[ ${installed[cx-agent]:-} == 0.3.4-2 ]] || fail 'public CX migration requires exact cx-agent 0.3.4-2'
    path=${artifacts[cx-agent]}
    [[ ! -L $path && -f $path ]] || fail 'unsafe CX artifact'
    [[ $(dpkg-deb -f "$path" Architecture) == amd64 ]] || fail 'unexpected CX artifact architecture'
    printf '%s  %s\n' b9189a3b15321679fe2bcd19ad37ec2efb1b2fa6c9ceb10185d8e3d6c57333b9 "$path" | sha256sum --check --status || fail 'CX artifact changed'
fi
GUARD
} > "$temporary/guard"
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
                'mote-chatd:[2.0.0-4]'*)
                    [[ $legacy_state == ordinary:installed ]] || fail 'Refusing removal of protected or unreviewed mote-chatd ownership.'
                    removed[mote-chatd]=mote-transportd ;;
                'mote-sync:[1.1.0-2]'*) removed[mote-sync]=mote-vault-sync ;;
                'mote-syncd:[1.1.0-2]'*) removed[mote-syncd]=mote-vault-syncd ;;
                'cx-node:[0.3.3-6]'*|'cx-node:[0.3.4-1~local20260909]'*) removed[cx-node]=cx-agent ;;
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
# A piped script has no interactive stdin. Obtain the controlling terminal
# explicitly; without one, the caller must choose --yes for unattended use.
if [[ ${#confirmation[@]} == 0 && ! -t 0 ]]; then
    if ! { exec {confirmation_fd}<>/dev/tty; } 2>/dev/null; then
        fail 'APT confirmation needs a terminal. Run with --yes only to explicitly approve unattended installation.'
    fi
else
    exec {confirmation_fd}<&0
fi
apt-get -o "DPkg::Pre-Install-Pkgs::=$guard" \
    -o "DPkg::Tools::Options::$guard::Version=3" \
    -o "DPkg::Tools::Options::$guard::InfoFD=0" \
    -o 'Dpkg::Options::=--force-confold' \
    "${confirmation[@]}" install "${packages[@]}" <&"$confirmation_fd"
printf '%s\n' 'Agent Sphere and Agent Apps packages installed. Runtime configuration and health are separate checks.'
