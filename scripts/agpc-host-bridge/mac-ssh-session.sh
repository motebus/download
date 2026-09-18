#!/bin/bash
# One Mac-owned SSH transport worker. Only loopback sshd is reachable.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mac-codex-session.sh"

run_ssh_session() {
    AGPC_SSH_TEMP='' AGPC_SSH_DOCKER_PID='' AGPC_SSH_NC_PID=''
    local ready result=0
    umask 077
    AGPC_SSH_TEMP=$(mktemp -d "${TMPDIR:-/tmp}/agpc-ssh.XXXXXXXX")
    cleanup_ssh() {
        exec 3<&- 4>&-
        [[ -z "$AGPC_SSH_DOCKER_PID" ]] || stop_child "$AGPC_SSH_DOCKER_PID"
        [[ -z "$AGPC_SSH_NC_PID" ]] || stop_child "$AGPC_SSH_NC_PID"
        rm -f "$AGPC_SSH_TEMP/in" "$AGPC_SSH_TEMP/out"
        rmdir "$AGPC_SSH_TEMP"
    }
    trap cleanup_ssh EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    mkfifo "$AGPC_SSH_TEMP/in" "$AGPC_SSH_TEMP/out"
    "$DOCKER" --context desktop-linux exec -i --user moted "$CONTAINER" \
        /usr/bin/python3 /usr/local/libexec/agpc/codex-stream.py serve \
        --socket "/run/mote/host-ssh/$SLOT.sock" --announce-ssh \
        > "$AGPC_SSH_TEMP/in" < "$AGPC_SSH_TEMP/out" &
    AGPC_SSH_DOCKER_PID=$!
    exec 3< "$AGPC_SSH_TEMP/in"
    exec 4> "$AGPC_SSH_TEMP/out"
    # Do not open speculative SSH connections while waiting for a Mote client.
    IFS= read -r -t 35 ready <&3 || bridge_fail 'SSH worker did not receive a connection.'
    [[ "$ready" == AGPC-SSH-READY ]] || bridge_fail 'Invalid SSH worker preamble.'
    "$NETCAT" 127.0.0.1 22 <&3 >&4 &
    AGPC_SSH_NC_PID=$!
    exec 3<&- 4>&-
    wait "$AGPC_SSH_DOCKER_PID" || result=$?
    cleanup_ssh
    trap - EXIT INT TERM
    return "$result"
}

ssh_main() {
    PATH=/usr/bin:/bin:/usr/sbin:/sbin
    export PATH
    [[ $# == 2 ]] || bridge_fail 'Expected exact container ID and SSH slot 0–3.'
    [[ $(uname -s) == Darwin && $(id -u) != 0 ]] || bridge_fail 'Must run as the ordinary Mac user.'
    CONTAINER=$1 SLOT=$2
    [[ "$CONTAINER" =~ ^[a-f0-9]{64}$ && "$SLOT" =~ ^[0-3]$ ]] || bridge_fail 'Invalid container or SSH slot.'
    DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
    NETCAT=/usr/bin/nc
    [[ -x "$DOCKER" && -x "$NETCAT" ]] || bridge_fail 'Docker Desktop or native nc is missing.'
    local identity
    identity=$("$DOCKER" --context desktop-linux inspect --format \
        '{{index .Config.Labels "org.motebus.agpc.role"}}:{{.State.Running}}' "$CONTAINER")
    [[ "$identity" == mac-runtime:true ]] || bridge_fail 'Container is not a running AGPC Mac runtime.'
    run_ssh_session
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then ssh_main "$@"; fi
