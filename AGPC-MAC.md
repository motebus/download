# macOS AGPC v0.1 implementation and acceptance contract

This records the requested target, not an existing native service API. No
component CLI flags or registration protocols are fabricated here.

## Platform and filesystem

- macOS 14+, native arm64. Intel and Rosetta shells are rejected in v0.1.
- System runtime: `/opt/agpc/{bin,etc,var,logs,agents,apps,runtime}`.
- Per-user state: `~/.agpc`, owned by the selected ordinary login user.
- launchd definitions: `/Library/LaunchDaemons`; these are OS integration files.
- Provide `agpc` on the normal shell PATH through a managed link or system path
  integration; its actual executable remains in `/opt/agpc/bin`.
- No apt, dpkg, .deb, systemd, runtime compilation, or source deployment on Mac.

## Native release admission (currently unavailable)

Require immutable, authenticated release artifacts with version, platform,
size, SHA-256, source revision and CI provenance. Digest integrity alone is not
publisher authentication. The release must define trusted publisher identity,
signature verification and macOS signing/notarization requirements. Retain
Gatekeeper; never remove quarantine to bypass verification.

The owner's release must include the runtime and all native dependencies for:

- AgentSphere and host service (`sphered`, `moted` in the inspected Linux stack).
- Mote client/proxy integration and Mote Transport.
- CX-Mesh and AGOS.
- The MCP component as its declared execution type. The inspected Linux
  `mote-mcpd` is on-demand stdio; do not invent a persistent daemon for it.
- Codex App-Server discovery, supported installation or an actionable missing
  runtime result, plus a protocol-level health check and per-user execution.

For each service require actual argv, configuration schema, least-privilege
account, readiness probe, dependency ordering, signal/shutdown behavior and
upgrade/rollback semantics. Never assume `--config`, `status` or `register`
exists. Do not launch a user's Codex session as root or copy its credentials.

The user explicitly requests native Mac artifacts. The broader workspace OCI
release policy still applies to hosted CI/services; an OCI container does not
substitute for an executable native macOS runtime. Native artifact promotion
and provenance must be resolved in the release pipeline.

## Host identity and transport

Derive the endpoint from `scutil --get LocalHostName`: lowercase, normalize
separators, enforce a nonempty label of at most 63 characters and reserve
`local`. Do not silently truncate names or append random suffixes on collision.
Persist one node ID on first admitted installation and reuse it on reruns.
Mesh enrollment must check naming collisions and authorization with its owner.

The requested identity record contains `id`, `hostname`, `endpoint`, `os`,
`arch`, `role`; this does not create new Mote environment aliases. Mote startup
uses only the owner's `MCHAT_*` identity/gateway configuration. No invented
`AGPC_MMA` or peer IP tables. Do not alter existing locked MCHAT files.

Keep `.mote` as a host endpoint routed by Mote, without `/etc/hosts`, DNS,
public IP, VPN or router dependencies. Install reviewed, narrowly scoped SSH
client integration automatically. Preserve OpenSSH host-key verification and
authentication. `local.mote` and the machine endpoint need fresh authenticated
sessions; a listening socket alone is not readiness.

The supplied channel model (including M/MCP and C/Content) differs from the
older locally available canonical policy (M/MEDIA and B/D/O/S). This installer
does not redefine channels. v0.1 needs an owner-admitted B/SSH contract; other
channels remain subject to their current owner's actual contracts.

## SSH and launchd

Use macOS OpenSSH; do not install a second client. The SSH target is
`127.0.0.1:22`. Enabling Remote Login alone does not establish loopback-only
listening. A release must supply an isolated, validated SSH server configuration
and launchd/socket-activation strategy that actually binds only loopback.

Inspect existing Remote Login, socket activation, listeners and SSH settings
before applying changes. An existing port-22 listener requires an explicit
migration strategy; never start a competing listener, silently take over a
remote session, weaken global sshd_config, or claim no exposure based on config
text alone. Preserve existing unrelated SSH access until an authorized new
session succeeds. Do not automatically enable stock Remote Login if that
exposes port 22 on external interfaces.

No root login, fallback password, permanent private-key distribution, firewall
disablement, SIP change or Gatekeeper bypass. Initial credentials/enrollment
must follow the owner-admitted trust bootstrap; zero configuration does not
mean anonymous access. Never log secrets.

Each actual daemon's launchd job needs absolute ProgramArguments, an explicit
working directory and account, start-at-boot, restart-on-failure with throttling,
stdout/stderr logs, graceful shutdown, and a runtime readiness check. launchctl
submission success alone is insufficient. Admission failures must stay visible.

## CLI target

The eventual native runtime must implement the same UX:

```text
agpc status
agpc info
agpc doctor
agpc start
agpc stop
agpc restart
agpc mesh status
agpc mesh peers
agpc mote status
agpc codex status
```

Do not implement stub commands returning success while their services are absent.

## Acceptance gates

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Clean Mac bootstrap | One command on clean Apple Silicon macOS 14+, no manual network/SSH configuration | Not tested |
| Release trust | Authenticated immutable native artifacts, actual executable architecture and dependency checks | Missing |
| Loopback SSH | Effective configuration and socket binding; no external-interface port 22 listener introduced | Not tested |
| Local endpoint | Fresh authorized `ssh local.mote` login as ordinary user | Not tested |
| Mesh endpoint | Fresh authorized `ssh <machine-name>.mote` from a second AGPC | Not tested |
| Runtime | All five stack components healthy via actual service/protocol probes | Not tested |
| CLI | Every listed command works and reports nonzero on failures | Not implemented |
| Persistence | Reboot recovery, stop/restart, clean shutdown, stable node ID | Not tested |
| Rerun/failure | No duplicate identity; interruption, collisions and invalid artifacts fail visibly | Not tested |

Only after these gates pass may the installer print `AGPC installation complete`
and the five green service lines. Missing remote evidence must be reported as
unverified, never silently converted to success. Store machine-readable evidence
with timestamp, platform, release digest, node ID, component checks and local/
remote session results, excluding credentials.
