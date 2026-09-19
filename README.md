# AGPC Native downloads

Native Linux and Windows CLI preview **0.1.0-preview.1**.

| Platform | CPU | Permanent download |
| --- | --- | --- |
| Linux | ARM64 and x86-64 | https://motebus.github.io/download/agpc.sh |
| Windows | x86-64 | https://motebus.github.io/download/agpc.exe |
| Windows | ARM64 | https://motebus.github.io/download/agpc-arm64.exe |

## Linux

Requires native Linux, Bash and Python 3.10+. The standalone script contains
its Python backend; a separate source folder is not needed. Run without sudo.

```bash
curl -fL https://motebus.github.io/download/agpc.sh -o agpc.sh
bash ./agpc.sh info --json
```

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

## Scope and verification

The CLI provides diagnostics, bounded Codex App-Server health checks and
read-only MCP tool discovery. It does not install the complete AGPC stack or
configure services. Native Windows execution acceptance and operational
RDP-over-Mote integration remain pending. macOS is specification-only.

[Checksums](https://motebus.github.io/download/agpc-native-SHA256SUMS) ·
[Checksum signature](https://motebus.github.io/download/agpc-native-SHA256SUMS.asc) ·
[Native provenance](https://motebus.github.io/download/agpc.source.json) ·
[Versioned release](https://github.com/motebus/download/releases/tag/agpc-native-v0.1.0-preview.1)

## Publication maintenance

`scripts/native-pages.json` pins the published native release and all asset and
runtime hashes. `scripts/publish_native.py` makes a standalone Linux launcher
with unchanged Python backend bytes and extracts the two unchanged Windows
EXEs. GitHub Pages serves these generated files at the permanent URLs.

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
