# Mac host adapters (candidate)

The Ubuntu image retains the signed AGPC DEB installation. CX-Mesh runs as
`cx-mesh` inside that image; its configured App-Server command exchanges opaque
stdio bytes with a native Mac Codex process. The Mac process runs as the ordinary
Mac user. Neither host credentials nor host workspaces are mounted in Docker.

The SSH adapter preserves the packaged Mote B relay's destination, container
`127.0.0.1:22`. A container-only `ssh.service` forwards bytes to a private Unix
socket owned by `moted`. Four host worker slots carry streams through `docker
exec`; each accepted stream connects to Mac `127.0.0.1:22`. The client authenticates
with the Mac sshd. The Ubuntu ssh.socket is masked; container OpenSSH is not the
login destination. No container ports are published.

Host scripts require an exact container ID, the AGPC role label, Docker Desktop's
explicit context and an ordinary Mac user. Socket directories are mode 0700;
listeners and clients verify peer UIDs. A worker slot remains locked for the
connection lifetime. Four simultaneous sessions are supported; excess connections
are closed. A supervisor must restart workers after a session or the bounded idle
timeout. The public installer does not yet install such a supervisor.

## Codex lifecycle and admission

The native Bash 3.2 supervisor uses FIFOs and accepts an absolute Codex binary,
container ID and host working directory. Every connection owns a new App-Server
process. Protocol bytes, including approval decisions, are never interpreted by
the adapter. Container root remains trusted. Buffers and connection waits are
bounded. Peer EOF ends the exec session because Docker CLI does not expose an
independent stdout half-close while its exec process remains alive. Cleanup stops
both local processes and removes FIFOs.

Installer integration still needs trusted helper installation, host Codex discovery
and per-user LaunchAgents with restart throttling and logs. Acceptance must verify
host user/workspace execution, approval round trips and restart/disconnect on a
real Mac. Official protocol: https://learn.chatgpt.com/docs/app-server

## Verification boundaries

- `test_host_codex_bridge.py`: protocol preservation, backpressure and cleanup.
- `test_host_ssh_bridge.py`: loopback bytes, slot exclusion/reuse, missing worker,
  host connection only after a valid ready marker, and inert script sourcing.
- `verify-container-bridge.py`: installed cx-exec through actual Docker exec,
  using a simulated host protocol.
- `verify-container-ssh.py`: actual image loopback port 22 and Docker exec,
  simulated host SSH banner and bidirectional binary bytes. No SSH authentication.
- `verify-native-mac.py`: pinned native Codex initialization without model calls.

Full Mac Docker startup, launchd worker installation, host sshd provisioning,
`.mote` client configuration, authenticated Mac SSH and second-machine access
remain acceptance gates. These adapters are source candidates, not a claim that
the published bootstrap installs a complete AGPC runtime.
