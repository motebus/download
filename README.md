# AGPC Native downloads

Native Linux installer, Windows diagnostics and Mac controller preview **0.1.0-preview.8**.

| Platform | CPU | Permanent download |
| --- | --- | --- |
| macOS | Apple Silicon ARM64 | https://motebus.github.io/download/agpc |
| Linux | x86-64 installer; ARM64 diagnostics | https://motebus.github.io/download/agpc.sh |
| Linux applications | x86-64 | https://motebus.github.io/download/agpc-apps.sh |
| Windows | x86-64 | https://motebus.github.io/download/agpc.exe |
| Windows | ARM64 | https://motebus.github.io/download/agpc-arm64.exe |

## Linux

Installation requires native Ubuntu 24.04/26.04 x86-64, systemd, Bash and Python
3.10+. The standalone script embeds its backend. It verifies and installs pinned
native runtime packages, preserving existing conffiles. ARM64
installation is deferred; explicit diagnostic commands remain available.
Downloads show the artifact name and SHA-256 completion. Codex CLI is managed separately and is not installed or updated.

```bash
curl -fL https://motebus.github.io/download/agpc.sh -o agpc.sh
bash ./agpc.sh install --dry-run
sudo bash ./agpc.sh install
agpc status
```

The core includes uChat (`uchat` and `uchatd`). After it completes, install
optional MDESK, MLINK and SS-WebOS applications:

```bash
curl -fsSL https://motebus.github.io/download/agpc-apps.sh | sudo bash
```

Desktop session setup and device admission remain governed by the native
applications. The application result is recorded separately in
`/usr/local/lib/agpc-native/apps-install.json`.

## Windows

Requires native PowerShell 7.4+ matching the host CPU. On x86-64:

```powershell
curl.exe -fL https://motebus.github.io/download/agpc.exe -o agpc.exe
.\agpc.exe info -Json
```

On ARM64:

```powershell
curl.exe -fL https://motebus.github.io/download/agpc-arm64.exe -o agpc-arm64.exe
.\agpc-arm64.exe info -Json
```

Use the executable for the native CPU. Run without elevation. These preview
EXEs are unsigned; no Windows execution-policy change is needed or requested.

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

## Scope and verification

Linux installation verifies artifact hashes, rejects package removals/downgrades
and unmanaged executable replacement, and records the result under
`/usr/local/lib/agpc-native/install.json`. The installed `agpc` command defaults
to read-only status. The downloaded script defaults to installation.

Windows installation remains unavailable (exit 2): its native runtime bundles
are still required. The Windows EXE bytes are unchanged.

Linux/Windows diagnostics include bounded Codex App-Server health checks and
read-only MCP tool discovery. Installation does not establish AGPC Ready.
S-channel enrollment/policy, application health, peer connectivity and operational
RDP-over-Mote integration remain pending. Codex authentication belongs to the
normal user. macOS is a controller preview; full native runtime acceptance remains pending.

[Checksums](https://motebus.github.io/download/agpc-native-SHA256SUMS) ·
[Checksum signature](https://motebus.github.io/download/agpc-native-SHA256SUMS.asc) ·
[Native provenance](https://motebus.github.io/download/agpc.source.json) ·
[Versioned release](https://github.com/motebus/download/releases/tag/agpc-native-v0.1.0-preview.8)

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

Linux core installation includes Remmina with its RDP plugin and standard xrdp/xorgxrdp host setup. The host uses TLS and a loopback listener, retaining its configured port. A new xrdp installation uses port 3391 when the system GNOME Remote Desktop service is active, otherwise 3389; `--rdp-port PORT` overrides this choice. Existing GNOME access is preserved. A compatible Xorg desktop session must already be installed. Use the client as your desktop user with the authorized Mote ingress address, and verify the target server certificate. Desktop login and Mote transport acceptance remain pending. Windows uses its built-in mstsc client; the Windows AGPC installer is still unavailable.
