# AGPC native downloads

AGPC is a native system. Linux installation uses signed DEB packages on
Ubuntu 24.04 or 26.04 amd64, with systemd, Bash and Python 3.10+.

| Profile | Download | Includes |
| --- | --- | --- |
| Standard | [agpc.sh](https://motebus.github.io/download/agpc.sh) | Agent Sphere, local Agent Ultra, AGPC Manager, contextd and Redis-backed uchatd |
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
transition to `agpc-apps`. Existing SQLite-based uChat installations require the
separate offline migration before this installer can proceed.

`contextd` owns local task context isolation; cloud CoD Server (`codd`) is not
installed. New S Channel and Agent identity integration remain deferred. Package
installation does not establish full runtime or cross-machine handoff readiness.
The historical `agent-sphere-apps.sh` compatibility entry follows Full.

Installer signatures (`.asc`), source records (`agpc.source.json` and
`agpc-all.source.json`), and `agpc-native-SHA256SUMS` are published beside them.
The dedicated `publish-agpc-profiles.yml` workflow verifies fresh Standard,
fresh Full and the legacy Apps transition on disposable native Ubuntu CI hosts
before activating Pages. It preserves existing pool files and unrelated site
content. No Docker or OCI is used for AGPC validation or publication.

## Earlier platform previews

The following notes describe separately published previews. They do not change
the current native Linux standard/full profiles. Windows native integration is
a separate future target; historical macOS Docker experiments are not supported
AGPC installation paths.

## Windows

Uses PowerShell 7.4+ when available and falls back to the matching Windows
PowerShell 5.1 host shipped with Windows 10/11. On x86-64:

```powershell
curl.exe -fL https://motebus.github.io/download/agpc.exe -o agpc.exe
.\agpc.exe
```

On ARM64:

```powershell
curl.exe -fL https://motebus.github.io/download/agpc-arm64.exe -o agpc-arm64.exe
.\agpc-arm64.exe
```

Running the executable with no command invokes the overall installer. Use the
explicit form below when the manifest path is known; `info`, `status` and
`doctor` remain read-only diagnostics:

```powershell
.\agpc.exe install -RuntimeManifest C:\ProgramData\AGPC\runtime-manifest.json
.\agpc.exe status -Json
```

The overall installer verifies the approved manifest, downloads the six native
Mote components, registers Windows SCM services and enables OpenSSH. It fails
closed without approved runtime bundles; no WSL or Debian fallback is used.
These preview EXEs are unsigned; no execution-policy change is needed.

## Mac (M-series only)

```sh
curl -fL https://motebus.github.io/download/agpc -o agpc
chmod +x agpc
./agpc version
./agpc init
./agpc sphere start
./agpc sphere status
```

Use Docker Desktop with Apple Virtualization framework and Rosetta enabled.
Only the pinned MoteBus + DC containers run in its Linux VM; host services use
native ARM64 executables. Run as your normal user, without sudo.

This release contains the controller. Configure owner-issued native components
in `~/Library/Application Support/AGPC/agpc.json` before `./agpc start`.
Missing owners fail startup; `doctor` stays nonzero until required readiness
checks pass. Apple Developer ID signing and notarization remain pending; the
Pages GPG signatures authenticate distribution, not Apple code signing.
Mac mesh, security, audit, MCP, exec and update commands remain unavailable
until their owner integrations are implemented.

The `macos-native-controller` CI job executes the hash-pinned released binary on
Darwin ARM64 and checks version, private init, and failure on missing owners.
Docker Desktop VM, launchd lifecycle and full stack acceptance require a real
M-series host and are not inferred from this CLI check.

The Linux applications installer selects **ss-webos 2.0.0-15**. Its primary
screen uses `<machine>.ss`; additional displays use `<machine>-02.ss`,
`<machine>-03.ss`, and so on. `<machine>.mote` identifies the host.

## Scope and verification

Linux installation verifies artifact hashes, rejects package removals/downgrades
and unmanaged executable replacement, and records the result under
`/usr/local/lib/agpc-native/install.json`. The installed `agpc` command defaults
to read-only status. The downloaded script defaults to installation.

Windows installation requires the approved native runtime manifest and bundles;
without them `install` exits 2 with `native_runtime_manifest_required`. The
Windows EXEs embed the overall PowerShell installer.

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

Linux core installation includes the `rdp TARGET.mote` command and two menu entries: **FreeRDP(xrdp)** and **FreeRDP(physical)**, both using FreeRDP at 1920×1080. Native Remmina remains installed with RDP, Secret Service and built-in SSH/SFTP support. Open Remmina from the app menu to manage saved profiles. There are no Open with Remmina launcher actions. Existing profiles and credentials are preserved. Target profile registration is required; no live targets or credentials are bundled. Existing single-mode profiles and listeners require the migration described in the versioned release. RDP uses its independent Mote relay, without SSH forwarding. RDP relay v2 selects Physical on remote loopback 3389 or XRDP on loopback 3390; both can operate concurrently through distinct local listeners. The installer also provides standard xrdp/xorgxrdp host setup. The host uses TLS and a loopback listener, retaining its configured port. A new xrdp installation uses port 3390; Physical RDP reserves 3389; `--rdp-port PORT` overrides this choice. Existing GNOME access is preserved. A compatible Xorg desktop session must already be installed. Use the client as your desktop user with the authorized Mote ingress address, and verify the target server certificate. Desktop login and Mote transport acceptance remain pending. Windows uses its built-in mstsc client; native RDP host and transport acceptance remain pending.
