# AGPC Mac Docker bootstrap preview.4

Requires macOS 14+ and native Apple Silicon arm64. This preview installs or
starts Docker Desktop as the invoking Mac user, then exits **78** because the
AGPC Ubuntu runtime and host bridge are not ready. It is not a full AGPC install.
Docker's first-launch license and authorization dialogs may require interaction.
An existing Docker installation is preserved. The pinned download is Docker
Desktop 4.91.0, verified by SHA-256 and macOS signature/Gatekeeper checks; its
minimum OS requirement is checked before installation.

```sh
curl -fsSL https://motebus.github.io/download/agpc-mac.sh | sudo bash
```

Use `--plan` for a read-only plan, `--check` for prerequisite inspection, or
`--install-docker` to perform Docker setup only. A successful Docker-only command
does not mean AGPC is ready.

## Target architecture

```text
Mac host: SSH + Codex App-Server (ordinary Mac user)
  Docker Desktop
    Ubuntu 26.04 / existing AGPC DEBs
      AgentSphere + Mote Transport + CX-Mesh + AGOS
      CX-Mesh -> authenticated adapter -> Mac Codex App-Server
```

The Ubuntu 26.04 candidate image builds successfully in remote CI from signed,
version-pinned DEBs. It is not an admitted or published runtime image. Existing packages currently require linux/amd64 execution on
Apple Silicon. No native arm64 mbStack support is claimed.

Codex authentication, workspaces and execution remain on the Mac. CX-Mesh's
managed stdio host adapter is implemented in `scripts/agpc-host-bridge/` and
verified through the image's installed `cx-exec` over Docker exec streams. It
is not enabled by this installer. CX-Mesh external mode is not implemented.
A container-local Codex executable cannot satisfy host readiness. No host home
or Docker socket mounts, privileged container shortcut, unauthenticated
App-Server listener, or credential copying is part of this plan.

Both `ssh local.mote` and `ssh <machine-name>.mote` must reach the Mac. The
current Linux relay targets its own localhost, so it cannot satisfy that target
without the pending host bridge. This preview does not change SSH configuration,
firewall, SIP or Gatekeeper, enroll peers, or install AGPC services.

## Verified candidate behavior

- macOS system Bash tests cover host supervisor termination and FIFO cleanup.
- Official pinned Codex 0.155.0 completes a native macOS App-Server initialize
  handshake and clean shutdown under an ordinary user with isolated state and
  zero model calls.
- Docker/CX-Mesh transport tests preserve requests, notifications and approval
  replies using a simulated host. These are separate from the native Mac test;
  they do not establish same-Mac end-to-end operation.
- The candidate image clears build-time OS and SSH identities before export.

The default-privilege Docker systemd diagnostic exits 255: it cannot create
`/init.scope` on the read-only cgroup filesystem. That diagnostic explicitly
reports `runtime_ready: false`; its CI completion is not runtime admission.
No privileged-container or host-cgroup-mount workaround is shipped.

## Remaining acceptance gates

- Authenticated immutable Ubuntu OCI release and container service lifecycle.
- Mac host bridge with authenticated SSH and no external port 22 exposure.
- Integrated same-Mac host App-Server execution, correct user/workspace,
  approval round-trip, disconnect handling, launchd and reboot recovery.
- Fresh local and second-AGPC `.mote` SSH sessions reaching the Mac.
- Working AGPC CLI, reboot recovery and all component health checks.
- Clean macOS 14+ Apple Silicon installation evidence.

Source CI checks syntax, mocked bootstrap behavior and publication integrity.
It does not prove Docker installation or end-to-end Mac runtime operation.
Only after all runtime gates pass may installation report success.
