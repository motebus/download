AGPC Windows x86-64 host recovery preview.1 — **unsigned prerelease**.

Download `agpc.exe` from this release, run it and approve Windows UAC. This is a partial host-access preview with the limitations below.

This unsigned native executable handles Windows UAC, OpenSSH provisioning/startup, localhost SSH verification and embedded Mote host-service installation. Docker, WSL and a Linux VM are not required. Sphered 4.1.0-windows.2 now tolerates two consecutive typed transient health-probe failures after startup; a third failure stops it, while ownership, permission and identity errors still fail immediately.

Validation on one existing Windows 11 x86-64 PC:

- Local elevated installation completed with verification-pending exit code 3. Seven AGPC services and sshd were running with automatic startup.
- Authenticated SSH survived a 45-second idle check. A 65,536-byte SFTP upload/download matched SHA-256 and the temporary remote files were removed.
- Independent RDP negotiation succeeded for two registered desktop selectors; desktop authentication/input was not retested in this increment.
- Local isolated CDP navigation, input, click and result verification passed without SSH. Remote CDP remains pending.
- 58 previously built native MCP tests passed. Both PowerShell 5.1 and 7 passed 28 catalog contract cases and the MCP installer source suite. These are regression tests: MCP is not installed in this host profile and real MCP tool execution/admission remains unverified.

Limitations:

- **Unsigned and incomplete host-access preview.** Complete native uChat, Redis, contextd, CoD client and AGOS integration remain pending. codd is an external server-side component.
- Recent Rust channel-isolation source changes were not rebuilt into the bundled components. No new Rust build, reverse-direction SSH repair, clean-machine or ARM64 acceptance is claimed.
- This is a locally built artifact, not a remote CI release. Existing Rust binaries retain compiler diagnostic paths. Necessary interpreted runtime programs are embedded; no development source tree, Git history, private keys, credentials, local logs or locked topology files are uploaded as release assets.
- Authenticode signing and full-runtime acceptance remain pending. This prerelease is not a stable/full-runtime release.

Version: `0.1.0-host-recovery-preview.1`

`agpc.exe`: 49,554,944 bytes.

SHA-256: `8f28f85391b0940dd0f0bd7dc0d573a013c16a1596d6ac1ef4ad93c61680fe60`

Assets: `agpc.exe`, `MANIFEST.json`, `SHA256SUMS`.

The version tag contains release metadata only. GitHub-generated source archives contain no AGPC implementation source or development history.
