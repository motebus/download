# Mac host Codex bridge candidate

This candidate keeps CX-Mesh in Ubuntu and starts Codex App-Server on the Mac as
an ordinary host user. It is not enabled by the public installer yet. SSH bridging,
container lifecycle and clean-Mac acceptance remain separate unfinished work.

## Transport

The host opens `docker --context desktop-linux exec -i --user cx-mesh` into an
exact, role-labeled container ID. A container helper listens once on a private
Unix socket. CX-Mesh's managed `cx-exec` backend launches the same helper in
client mode. The helper passes bytes through stdio to the Mac App-Server. It
never parses shell commands or JSON, including approval decisions.

Only the container's `cx-mesh` UID may connect; directory and socket permissions
are 0700/0600, and both endpoints check Linux peer credentials. Container root
remains trusted. No network port, Docker socket mount, host home mount or Codex
credential copy is required. The host's Docker credentials stay on the host.

The supervisor uses native Bash 3.2 and FIFOs; no extra host Python installation
is needed. It accepts an absolute host Codex binary, exact container ID and Mac
working directory. It rejects root and non-macOS hosts. Docker and Codex stderr
remain diagnostic output; stdout carries only protocol bytes. Each connection
owns a new App-Server process. Closing the session or stopping the supervisor
cleans up both local processes and FIFOs. Container helpers use bounded buffers,
a connection timeout, peer-UID checks and an EOF grace period.

## Admission still required

- Install trusted helpers and discover the actual host Codex binary.
- Create a per-user LaunchAgent with restart/throttling and logs; start the
  container before exposing the host bridge, and stop the bridge on logout.
- Verify the real App-Server initialize response reports macOS, then verify host
  user/workspace execution, approval round-trip and restart/disconnect behavior.
- Validate the Ubuntu systemd runtime on Docker Desktop and the separate Mac
  SSH endpoint. The image inventory deliberately remains `runtime_ready: false`.

Tests use fake protocol endpoints. Their macOS identity strings are fixtures,
not proof of real Mac execution. CI additionally builds the candidate OCI image
from signed DEBs; it does not publish or admit it as a running AGPC image.

Official protocol: https://learn.chatgpt.com/docs/app-server
