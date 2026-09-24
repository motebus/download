# AGPC native downloads

AGPC is a native system. Linux installation uses signed DEB packages on
Ubuntu 24.04 or 26.04 amd64, with systemd, Bash and Python 3.10+.

| Profile | Download | Includes |
| --- | --- | --- |
| Standard | [agpc.sh](https://motebus.github.io/download/agpc.sh) | Agent Sphere, local Agent Ultra, AGPC Manager, CDP client/provider, contextd and Redis-backed uchatd |
| Full | [agpc-all.sh](https://motebus.github.io/download/agpc-all.sh) | Standard plus agpc-apps |

Standard:

```bash
curl -fL https://motebus.github.io/download/agpc.sh -o agpc.sh
sudo bash ./agpc.sh
```

Full:

```bash
curl -fL https://motebus.github.io/download/agpc-all.sh -o agpc-all.sh
sudo bash ./agpc-all.sh
```

Use `--help` to inspect options. Both entries verify native package selection
and preserve existing application data. Standard leaves installed apps in place;
Full upgrades an installed legacy `agent-apps` through its documentation-only
transition to `agpc-apps`. SQLite is retired from the runtime; an existing
SQLite-based uChat installation must complete the separate offline migration
before this installer can proceed.

`@machine-name` is the default user-to-user Inbox route; it requires no setting or check. `contextd` owns local task context isolation; cloud CoD Server (`codd`) is not
installed. New S Channel and Agent identity integration remain deferred. Package
installation does not establish full runtime or cross-machine handoff readiness.
The historical `agent-sphere-apps.sh` compatibility entry follows Full.

Both profiles install `agpc-cdp`, which provides the terminal `cdp` client and
the `cdpd` provider daemon. The daemon is fail-closed and remains disabled until
the host has a reviewed `/etc/agpc-cdp/cdpd-binding.cjs` Mote P/S deployment
binding. Package installation does not establish remote CDP readiness.

## Work and context contract

uChat carries work and CoD carries the working context. Box addresses a message;
Inbox records the durable work state:

```text
User Box   -> User Inbox   = U2U work
Agent Box  -> Agent Inbox  = U2A / A2U work
Mesh Box   -> Mesh Inbox   = A2A work
```

Redis is the shared internal durable layer for delivery, pending work, ACK and
recovery. Agents do not access Redis directly. CoD opens the task-scoped
context sandbox, attaches authorized sources on demand and persists useful
results; `contextd` is inside native AGPC and CoD Server (`codd`) is cloud-side.
Messages carry `task + context_ref`, not an entire context. The D Channel carries
message and control traffic, the O Channel is reserved for logs and billing, and
the S Channel is reserved for identity, capability, authorization and policy.
S-channel and Agent identity integration is deferred. SQLite is retired and is
not a message, queue, approval or recovery store.

The component boundary is `uChat -> uchatd` for communication semantics and
Box/Inbox routing, Redis for durable delivery, CoD/codd for context lifecycle and
assembly, `contextd` for native isolation, Nbook for durable organizational
knowledge, and AGPC for native execution. A handoff moves the task and context
reference through a Mesh Box; the receiving agent claims Inbox work and asks CoD
for the authorized context.

Installer signatures (`.asc`), source records (`agpc.source.json` and
`agpc-all.source.json`), and `agpc-native-SHA256SUMS` are published beside them.
The dedicated `publish-agpc-profiles.yml` workflow verifies fresh Standard,
fresh Full and the legacy Apps transition on disposable native Ubuntu CI hosts
before activating Pages. It preserves existing pool files and unrelated site
content. No Docker or OCI is used for AGPC validation or publication.

## Earlier platform previews

The following notes describe separately published previews. They do not change
the current native Linux standard/full profiles. Full Windows native integration remains incomplete; historical macOS Docker experiments are not supported
AGPC installation paths.

## Windows

[Download agpc.exe (x86-64)](https://motebus.github.io/download/agpc.exe):
**0.1.0-host-access-preview.2**, an unsigned outbound-access preview with
FreeRDP 3.31.1 and native MCP. Download and run `agpc.exe`, then approve Windows
UAC when prompted. No Docker or WSL is required. FreeRDP is provisioned when
missing and needs Internet access for its initial download.

RDP uses an independent Mote channel. Windows Home supports the FreeRDP client;
FreeRDP does not add an RDP host to Windows Home. MCP binaries are packaged with
deny-by-default policy. Local CDP remains a preview.

This executable uses the `agpc.windows-access/v1` outbound profile: it does not
include moted or provision a complete inbound host installation. Full
uChat/contextd/Redis/CoD integration and remote CDP admission remain incomplete.
Remote SSH/RDP and MCP authorization/tool execution are not accepted for this
exact build. Native build tests and PowerShell 5.1/7 suites passed; fixtures do
not establish remote readiness or clean-machine acceptance.

[Release notes, manifests and checksums](https://github.com/motebus/download/releases/tag/agpc-windows-v0.1.0-host-access-preview.2).
ARM64 remains the earlier manifest-dependent preview at
[agpc-arm64.exe](https://motebus.github.io/download/agpc-arm64.exe).

## Native-only boundary

AGPC is 100% native. The supported Linux path installs signed Debian packages
with `agpc.sh` or `agpc-all.sh`; Full Windows native integration remains incomplete; the outbound-access preview is available above.
There is no Docker, Podman, `ag-net`, WSL fallback or container runtime in the
AGPC product. OCI images are reserved for cloud or server deployments outside
AGPC. The former macOS Docker bootstrap is retired and is not an installation
path.

## Scope and verification

Linux installation verifies artifact hashes, rejects package removals/downgrades
and unmanaged executable replacement, and records the result under
`/usr/local/lib/agpc-native/install.json`. The installed `agpc` command defaults
to read-only status. The downloaded script defaults to installation.

The current x86-64 Windows preview embeds its outbound-access bundles. Full-host
installation still requires the approved native host runtime and is not included
in this release. The earlier ARM64 preview remains manifest-dependent.

Linux/Windows diagnostics include bounded Codex App-Server health checks and
read-only MCP tool discovery. Installation does not establish AGPC Ready.
S-channel enrollment/policy, application health, peer connectivity and operational
RDP-over-Mote integration remain pending. Codex authentication belongs to the
normal user. macOS is a controller preview; full native runtime acceptance remains pending.

[Checksums](https://motebus.github.io/download/agpc-native-SHA256SUMS) ·
[Checksum signature](https://motebus.github.io/download/agpc-native-SHA256SUMS.asc) ·
[Native provenance](https://motebus.github.io/download/agpc.source.json) ·
[Versioned release](https://github.com/motebus/download/releases/tag/agpc-native-v0.1.0-preview.20)

## Publication maintenance

`scripts/native-pages.json` pins the published native release and all asset and
runtime hashes. `scripts/publish_native.py` makes a standalone Linux launcher
with unchanged Python backend bytes and extracts the two unchanged Windows
EXEs and the original Mac ARM64 Mach-O controller. GitHub Pages serves these generated files at the permanent URLs.

The native Pages workflow restores the current successful Pages CI artifact,
checks its SHA-256, replaces only the native entrypoints, their signed provenance
and the landing page, and verifies every other file is byte-identical. Both
Pages workflows share one deployment concurrency group. The APT publisher also
applies the native files last so later APT publication cannot reclaim these URLs.

The root `agpc.sh` and `agpc.source.json` in this Git tree remain immutable Debian
build inputs used by the existing APT verifier; they are replaced in the Pages
artifact by the native publisher. Native source is taken from the reviewed
release, not from these historical build inputs. Debian package bytes, indexes,
release assets and `agent-sphere-apps.sh` remain unchanged by native publication.
See [historical Debian documentation](AGPC-DEBIAN.md) for the separate edition.
The requested native entrypoints never invoke the Debian or WSL installers.

Codex CLI is not downloaded, installed or updated by `agpc.sh`. Existing Codex
files and links are preserved, including installations from earlier previews.
The optional Codex diagnostic requires a separately provided binary.

Downloads show an artifact start line and SHA-256 completion without repeated transfer-rate or elapsed-time output. Core packages include the independent mote-mcp-ultra server, CX-Mesh execution runtime, uchat and uchatd. The legacy mote-mcpd gateway and its six tools are retired; inbox remains with uchatd. Existing medge and agpc-manager versions and configuration are preserved.

Linux core installation includes the `rdp TARGET.mote` command and two menu entries: **FreeRDP(xrdp)** and **FreeRDP(physical)**, both using FreeRDP at 1920×1080. Native Remmina remains installed with RDP, Secret Service and built-in SSH/SFTP support. Open Remmina from the app menu to manage saved profiles. There are no Open with Remmina launcher actions. Existing profiles and credentials are preserved. Target profile registration is required; no live targets or credentials are bundled. Existing single-mode profiles and listeners require the migration described in the versioned release. RDP uses its independent Mote relay, without SSH forwarding. RDP relay v2 selects Physical on remote loopback 3389 or XRDP on loopback 3390; both can operate concurrently through distinct local listeners. The installer also provides standard xrdp/xorgxrdp host setup. The host uses TLS and a loopback listener, retaining its configured port. A new xrdp installation uses port 3390; Physical RDP reserves 3389; `--rdp-port PORT` overrides this choice. Existing GNOME access is preserved. A compatible Xorg desktop session must already be installed. Use the client as your desktop user with the authorized Mote ingress address, and verify the target server certificate. Desktop login and Mote transport acceptance remain pending. The current Windows x86-64 preview uses the SDL FreeRDP 3.31.1 client; native RDP host and end-to-end transport acceptance remain pending.
