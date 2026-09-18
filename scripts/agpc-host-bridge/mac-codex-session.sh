#!/bin/bash
# One host-user App-Server session. Intended for a user LaunchAgent, not root.
set -euo pipefail

bridge_fail() { printf 'AGPC host Codex: %s\n' "$*" >&2; exit 1; }

stop_child() {
    local pid=$1 attempt
    kill -TERM "$pid" 2>/dev/null || true
    for ((attempt=0; attempt<50; attempt++)); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
}

run_session() {
    # Bash 3.2 can unwind function locals before running EXIT traps.
    # Keep cleanup ownership in process-scoped variables, never trap-local state.
    AGPC_BRIDGE_TEMP='' AGPC_BRIDGE_CODEX_PID='' AGPC_BRIDGE_DOCKER_PID=''
    local result=0
    umask 077
    AGPC_BRIDGE_TEMP=$(mktemp -d "${TMPDIR:-/tmp}/agpc-codex.XXXXXXXX")
    cleanup() {
        [[ -z "$AGPC_BRIDGE_DOCKER_PID" ]] || stop_child "$AGPC_BRIDGE_DOCKER_PID"
        [[ -z "$AGPC_BRIDGE_CODEX_PID" ]] || stop_child "$AGPC_BRIDGE_CODEX_PID"
        rm -f "$AGPC_BRIDGE_TEMP/in" "$AGPC_BRIDGE_TEMP/out"
        rmdir "$AGPC_BRIDGE_TEMP"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    mkfifo "$AGPC_BRIDGE_TEMP/in" "$AGPC_BRIDGE_TEMP/out"
    # Redirection order is deliberate: open the same FIFO first at both ends.
    "$CODEX" app-server --listen stdio:// < "$AGPC_BRIDGE_TEMP/in" > "$AGPC_BRIDGE_TEMP/out" &
    AGPC_BRIDGE_CODEX_PID=$!
    "$DOCKER" --context desktop-linux exec -i --user cx-mesh "$CONTAINER" \
        /usr/bin/python3 /usr/local/libexec/agpc/codex-stream.py serve \
        > "$AGPC_BRIDGE_TEMP/in" < "$AGPC_BRIDGE_TEMP/out" &
    AGPC_BRIDGE_DOCKER_PID=$!
    wait "$AGPC_BRIDGE_DOCKER_PID" || result=$?
    cleanup
    trap - EXIT INT TERM
    return "$result"
}

main() {
    PATH=/usr/bin:/bin:/usr/sbin:/sbin
    export PATH
    [[ $# == 3 ]] || bridge_fail 'Expected absolute Codex path, container ID, and host working directory.'
    [[ $(uname -s) == Darwin && $(id -u) != 0 ]] || bridge_fail 'Must run as the ordinary Mac user.'
    CODEX=$1 CONTAINER=$2
    DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
    [[ "$CODEX" == /* && -f "$CODEX" && -x "$CODEX" ]] || bridge_fail 'Host Codex executable is missing.'
    [[ "$CONTAINER" =~ ^[a-f0-9]{64}$ ]] || bridge_fail 'An exact container ID is required.'
    [[ "$3" == /* && -d "$3" ]] || bridge_fail 'Host working directory is missing.'
    [[ -x "$DOCKER" ]] || bridge_fail 'Docker Desktop is missing.'
    local identity
    identity=$("$DOCKER" --context desktop-linux inspect --format \
        '{{index .Config.Labels "org.motebus.agpc.role"}}:{{.State.Running}}' "$CONTAINER")
    [[ "$identity" == mac-runtime:true ]] || bridge_fail 'Container is not a running AGPC Mac runtime.'
    cd "$3"
    run_session
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
