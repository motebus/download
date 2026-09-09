#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf '%s\n' \
        'Usage: agent-sphere-apps.sh [--yes] [--help]' \
        'Install agent-sphere and agent-apps using the configured signed MoteBus APT repository.' \
        'Run as root. APT asks for confirmation unless --yes is supplied.'
}

confirmation=()
show_help=false
for arg in "$@"; do
    case "$arg" in
        --yes) confirmation=(--yes) ;;
        --help) show_help=true ;;
        *) printf 'Unsupported argument: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done
if "$show_help"; then
    usage
    exit 0
fi

if [[ "$(id -u)" != 0 ]]; then
    printf '%s\n' 'Run this installer as root (for example, with sudo).' >&2
    exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' 'apt-get is required. Use a supported Debian or Ubuntu host.' >&2
    exit 1
fi

if ! apt-get update; then
    printf '%s\n' 'APT update failed. Package installation was not started.' >&2
    exit 1
fi
if ! apt-get --simulate --no-remove install agent-sphere agent-apps; then
    printf '%s\n' \
        'Both packages must be available and compatible without package removals.' \
        'Check the configured signed MoteBus APT repository. Package installation was not started.' >&2
    exit 1
fi

apt-get --no-remove "${confirmation[@]}" install agent-sphere agent-apps
