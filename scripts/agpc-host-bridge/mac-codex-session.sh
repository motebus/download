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
    local temporary codex_pid='' docker_pid='' result=0
    umask 077
    temporary=$(mktemp -d "${TMPDIR:-/tmp}/agpc-codex.XXXXXXXX")
    cleanup() {
        [[ -z "$docker_pid" ]] || stop_child "$docker_pid"
        [[ -z "$codex_pid" ]] || stop_child "$codex_pid"
        rm -f "$temporary/in" "$temporary/out"
        rmdir "$temporary"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    mkfifo "$temporary/in" "$temporary/out"
    # Redirection order is deliberate: open the same FIFO first at both ends.
    "$CODEX" app-server --listen stdio:// < "$temporary/in" > "$temporary/out" &
    codex_pid=$!
    "$DOCKER" --context desktop-linux exec -i --user cx-mesh "$CONTAINER" \
        /usr/bin/python3 /usr/local/libexec/agpc/codex-stream.py serve \
        > "$temporary/in" < "$temporary/out" &
    docker_pid=$!
    wait "$docker_pid" || result=$?
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
