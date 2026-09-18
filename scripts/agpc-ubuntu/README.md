# Mac → Docker → Ubuntu 26.04 → AGPC DEBs

This is the package-build foundation for the requested Mac architecture. It
installs the signed, version-pinned headless AGPC core and manager into Ubuntu
26.04 amd64. Apple Silicon will require amd64 execution support in Docker.
No source is compiled on the user's Mac. Core startup remains systemd-managed.

The user's `.mote` SSH target is **the Mac**, not this Ubuntu container. Never
start a container SSH endpoint and report it as successful Mac access. MoteD's
current packaged relay targets container-local 127.0.0.1:22 and requires an
owner-reviewed secure Mac bridge before use. CX-Mesh's default Codex command is
Linux-local and also needs a Mac execution adapter. Do not mount the Mac home or
Docker socket, or use privileged containers as a shortcut.

The image CMD preserves /sbin/init, but no Mac-compatible cgroup or runtime
configuration is admitted yet. `installed.json` explicitly records
`runtime_ready: false`. Do not advertise this image as a running AGPC or wire it
into the public installer before runtime and Mac endpoint acceptance.

Build from repository root in CI:

```sh
docker build --platform linux/amd64 -f scripts/agpc-ubuntu/Dockerfile -t agpc-ubuntu26:candidate .
```

The image contains no agent-apps, agent-ultra or non-redistributable Obsidian
payload. Mac host software remains outside the Linux container.

## Host Codex execution contract

CX-Mesh runs here, but its App-Server must run on the Mac under the selected
ordinary host user. Host credentials and workspaces stay on the host. A Linux
App-Server inside this image must not satisfy the Mac Codex readiness check.

The inspected CX-Mesh managed backend accepts a configurable absolute command
and transports JSONL over stdin/stdout. Its external mode is unimplemented.
The candidate image configures the managed stdio adapter in
`scripts/agpc-host-bridge/`. The host user initiates a Docker exec stream, and
only the container CX-Mesh UID can connect to its private Unix socket. The
public installer does not enable this candidate yet; runtime readiness remains
false pending real Mac acceptance. Host execution must preserve
approval requests as well as responses and notifications, and disconnects must
fail visibly. No public App-Server listener, host credential mount or Docker
socket mount is part of this contract.

Acceptance must verify the protocol initialize exchange, Mac OS/user/workspace
identity, approval round-trip, disconnect handling and process cleanup. A local
`cx-exec --check` only checks executable availability and is insufficient.

## Container confinement candidate

`runtime-options.json` requires Engine 28+, private cgroup v2, writable container
cgroups, no-new-privileges and CAP_SYS_ADMIN for systemd namespace setup. It uses
no privileged mode, host mounts, host cgroup namespace or published ports. The
capability requirement is broader than an ordinary application container and
must be included in runtime admission review.

Linux CI loads `agpc-systemd.apparmor` on its disposable runner. The profile
retains Docker-derived proc/sys restrictions and denies unspecified mount
operations. Its additions cover systemd's private staging mounts, generator
read-only remounts and private runtime credentials. The template's license is
preserved in `LICENSE.apparmor`. CI also requires a mount outside these paths to
fail, and executes a hardened non-root transient service.

This CI profile is not installed into a user's Docker Desktop VM. Mac admission
must inspect the actual Engine/cgroup/security configuration and verify service
startup there; it must not silently turn off AppArmor or enable privileged mode.
The separate `--diagnose-without-apparmor` check is only a CI failure-isolation
experiment and cannot qualify an image for release.
