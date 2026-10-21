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
installed. Local MCP execution uses the independent S Channel authority in
`mote-secd`; requests require administrator approval and the caller must have
explicit membership in `mote-sec-consumer`. Remote M-channel admission and
cross-machine agent delegation are not enabled by this package update. Package
installation does not establish full runtime or cross-machine handoff readiness.
The historical `agent-sphere-apps.sh` compatibility entry follows Full.

Both profiles install `agpc-cdp`, which provides the terminal `cdp` client and
the `cdpd` provider daemon. The client resolves the `moted`-owned `type=mote`
record and uses the native P channel directly to `cdpd`; CDP traffic does not
traverse SSH, `mote-proxy`, `moted`, or WSS. Target OS username/password is
verified by `cdpd` through PAM. S-channel admission is a mutually exclusive
alternative. A selected desktop user service, an available native Chrome/Edge
runtime, and live target acceptance remain runtime setup checks.

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

Preview 17 keeps Windows doctor and explicit WSL status output inside AGPC Manager, including exit codes. Results remain selectable and scrollable after completion. Diagnostics have bounded output, a timeout and owned-process cancellation when the window closes. PowerShell 5.1/7.6.5 regressions and packaged diagnostic checks passed. Native uchatd, durable Redis and live chat delivery remain pending.

Preview 16 fixes native PowerShell startup when a foreign-edition module path is inherited. Packaged MCP discovery and manager status pass with that invalid parent path. Native clipboard round-trips pass in a private test window station without accessing the user's interactive clipboard; terminal-host interaction and live chat delivery remain unverified.


Preview 15 adds the native AGPC Manager window: run `agpc-manager` or `agpc.exe manager`; use `agpc-manager status -Json` for observations. It preserves independent Windows and explicit WSL identities. uChat adds Ctrl+V paste into the draft, Ctrl+Y copy draft, Ctrl+Shift+C copy latest message, and /copy or /copy last. Paste does not send automatically; scroll controls retain the draft. Native uchatd and live clipboard round-trip remain unverified.


Preview 14 fixes MCP discovery by preserving the Windows SystemDrive variable. Native protocol initialization passes against the installed stdio provider; the default catalog remains empty, and tool authorization/execution remain unverified. MCP remains an on-demand stdio provider; no mote-mcpd SCM service is added.


Preview 18 validates the protected uChat endpoint through pinned Windows file and ancestor handles, including ownership, ACL and size checks. Untrusted configuration is rejected. It does not install native Redis or uchatd, provision accounts, or complete the UAC identity handoff; live chat remains unavailable.

[Download agpc.exe (x86-64)](https://motebus.github.io/download/agpc.exe):
**0.1.0-host-access-preview.18**, an unsigned outbound-access preview with
local CDP/cdpd, the Windows `mstsc.exe` RDP client, and native MCP. One elevated
installation registers the stable `C:\Program Files\AGPC\bin` machine PATH and creates `cdp.exe`,
`rdp.exe`, `run.exe`, `mesh.exe`, `uchat.exe`, and `agpc-manager.exe` as hard links to that one
payload. The protected native bootstrap forwards each command to the HKLM-registered current release. Existing preview 9/10 terminals need one initial refresh; later upgrades keep the same command path.
No Docker or WSL is required for native Windows.
One `agpc.exe` also manages the explicit `agpc-wsl` sibling runtime. Bare
invocation selects `agpc-win` (native Windows/PowerShell). WSL commands select
`agpc-wsl` (WSL Linux/Bash); the runtimes have independent node identities and
Mesh admission. Native Windows does not require WSL or switch into it silently.

```powershell
.\agpc.exe wsl status -Json
.\agpc.exe wsl plan -NodeName mypc-wsl -Distro Ubuntu-24.04 -UserName jujue
.\agpc.exe wsl install -NodeName mypc-wsl -Distro Ubuntu-24.04 -UserName jujue
```

The WSL installer uses SHA-256 pinned Linux release `v0.3.0-46`, requests UAC
and retains protected per-account restart state. Local Linux password entry
stays in the console. Live WSL install/reboot/resume and Mesh admission are
not verified in this preview. Go tests/vet and native PowerShell 5.1/7 suites
passed; publication uses the user-authorized local Windows build.

RDP uses an independent Mote channel. Windows Home supports the `mstsc.exe` client
but has no built-in RDP host. MCP binaries are packaged with
deny-by-default policy. Windows CDP is local-only; remote CDP is retired.

In PowerShell, `local.mote` resolves to this PC. `cdp doctor` inventories local
prerequisites; `plan` and `run` require an expiring operator policy and request:

```powershell
.\agpc.exe cdp doctor local.mote
.\agpc.exe cdp setup
.\agpc.exe cdp plan 'C:\path\policy.json' 'C:\path\request.json'
.\agpc.exe cdp run 'C:\path\policy.json' 'C:\path\request.json'
```

Start `agpc.exe cdpd serve POLICY` with a private, expiring operator policy,
then use `agpc.exe cdp --head local.mote [command]`. The CLI and bundled MCP
`browser_cdp` adapter use the authenticated local P pipe to `cdpd`. Headed
Google Maps and the Rust MCP adapter were verified on `medge-oa.mote`.

This executable uses the `agpc.windows-access/v1` outbound profile: it does not
include moted or provision a complete inbound host installation. Full
uChat/contextd/Redis/CoD integration remains incomplete.
Remote SSH/RDP and MCP authorization/tool execution are not accepted for this
exact build. RUN and Mesh commands report owner-not-installed until
their production services and S admission exist. Local CDP prerequisites were
observed on MEDGE-OA; this does not establish browser execution on this exact
build, remote readiness, or clean-machine acceptance.

[Release notes, manifests and checksums](https://github.com/motebus/download/releases/tag/agpc-windows-v0.1.0-host-access-preview.18).

Preview 10 adds native human uChat client commands: `uchat uput @machine MESSAGE`,
`uchat ubox [AFTER_CURSOR]`, `uchat uget INBOX_ID`, and `uchat info`.
The client authenticates the installed daemon's Windows service identity and
requires owner-protected endpoint configuration. The Windows uchatd, durable
Redis, account binding and Mesh routing are not packaged; client operations
report `uchat_endpoint_not_installed` until those owners are installed.
Bare `uchat` now opens the native Windows terminal UI. CDP now explains
its missing remote P/S provider; no remote provider or transport fallback is added.

Preview 11 fixes command lookup across upgrades and rejects mistyped CDP
selectors such as `medge-home.mpte` before checking remote admission.
It preserves the existing local CDP and native human uChat client boundaries;
missing daemon/storage or remote P/S providers remain unavailable.
Preview 12 adds the native terminal UI: bare `uchat` opens it, `/connect @machine` selects a recipient, and `/help` shows its commands. It opens disconnected when the protected native daemon endpoint is absent; offline sends retain the draft and say **Not sent**. No message is queued or replayed. Native Go tests, PowerShell 5.1/7.6.5 suites and an owned Windows console launch/input/exit test passed. Native uchatd, Redis, account binding and live chat delivery remain unavailable in this preview.

Preview 13 matches the current DEB uChat design: one compact status/From/To header, separator, conversation at the top and only the draft at the bottom. `@machine` selects a chat, `@machine TEXT` sends literal text, and `/inbox`, `/help`, `/next`, `/back`, `/status`, `/clean` and Ctrl+U provide native navigation. It also stages CLI aliases in the immutable release inventory so repeat setup retains exact file verification without rejecting installer-created aliases. Native console/layout tests and PowerShell regression suites passed; local live install/reinstall acceptance is recorded separately from source validation.

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

Downloads show an artifact start line and SHA-256 completion without repeated transfer-rate or elapsed-time output. Core packages include the local `mote-mcpd` gateway, its independent `mote-secd` rights authority, CX-Mesh execution runtime, uchat and uchatd. `mote-mcp-ultra` is retired: its native adapters are embedded in `mote-mcpd`, with existing administrator configuration preserved during the reviewed package transition. `ultra-mcp` and `ultra-mcp-xx` are cloud components and are not installed on AGPC. Inbox remains with uchatd. Existing medge and agpc-manager versions and configuration are preserved.

Linux core installation includes the `rdp TARGET.mote` command and two menu entries: **FreeRDP(xrdp)** and **FreeRDP(physical)**, both using FreeRDP at 1920×1080. Native Remmina remains installed with RDP, Secret Service and built-in SSH/SFTP support. Open Remmina from the app menu to manage saved profiles. There are no Open with Remmina launcher actions. Existing profiles and credentials are preserved. Target profile registration is required; no live targets or credentials are bundled. Existing single-mode profiles and listeners require the migration described in the versioned release. RDP uses its independent Mote relay, without SSH forwarding. RDP relay v2 selects Physical on remote loopback 3389 or XRDP on loopback 3390; both can operate concurrently through distinct local listeners. The installer also provides standard xrdp/xorgxrdp host setup. The host uses TLS and a loopback listener, retaining its configured port. A new xrdp installation uses port 3390; Physical RDP reserves 3389; `--rdp-port PORT` overrides this choice. Existing GNOME access is preserved. A compatible Xorg desktop session must already be installed. Use the client as your desktop user with the authorized Mote ingress address, and verify the target server certificate. Desktop login and Mote transport acceptance remain pending. The current Windows x86-64 preview uses the SDL FreeRDP 3.31.1 client; native RDP host and end-to-end transport acceptance remain pending.

## Voice-Mote bootstrap

[voice-mote.sh](https://motebus.github.io/download/voice-mote.sh) publishes the
`0.1.0-bootstrap.1` installer for the AGPC Voice execution capability. This
release contains the bootstrap only; the `voice-mote` runtime package and full
AGPC/Voice live acceptance remain prerequisites. Missing gates stop installation.
See [installation and signature verification](VOICE-MOTE-INSTALL.md) and the
[canonical specification](VOICE-MOTE-SPEC-v0.1.md).
