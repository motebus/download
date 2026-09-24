AGPC Windows x86-64 access preview 3 — native Windows RDP client and local CDP. **Unsigned prerelease; incomplete outbound-access profile.**

Changes:
- Removed FreeRDP/MSYS2 installation, discovery and dependency. RDP uses Windows mstsc.exe.
- Added a navigation deadline guard to the local CDP engine.
- Help commands no longer trigger UAC.

Validation on one Windows PC: real Chrome headless and headed browser tests passed for forms, upload/download, screenshot, denied origins, replay rejection and policy revocation. The Windows symlink-escape fixture was skipped because the current account lacks symlink privilege. Native Go tests/vet and PowerShell 5.1/7 probe, MCP contract, OpenSSH, channel, bundle and installer transaction suites passed. Some checks use fixtures; this is not clean-machine or remote acceptance.

Limitations:
- Windows 11 x86-64 only; this asset is not ARM64 accepted.
- This agpc.windows-access/v1 bundle contains sphered, mote-proxy and the deny-by-default local MCP adapter. It does not contain moted or the full inbound host runtime. Do not treat it as a complete host installer.
- Remote CDP admission/provider/broker is NOT implemented. Local browser execution requires native Node.js 22+, Chrome, browser setup and an operator-approved policy/request. browser doctor reports engine inventory only, not session readiness.
- Windows Home supports outbound mstsc connections but cannot host native Microsoft RDP. The changed mstsc connection path has not passed an interactive remote acceptance test in this build.
- Remote SSH/RDP acceptance, MCP authorization/tool execution and full uChat/Redis/contextd/CoD/AGOS readiness are pending. Embedded transport binaries do not include the newer managed SSH host-key runtime.
- No Authenticode signature. SHA-256 is an integrity checksum, not Windows publisher signing.

Download agpc.exe and approve UAC for installation. No Docker or WSL is required. Exit 3 means installation completed with readiness verification pending.

Distribution version: 0.1.0-host-access-preview.3. Internal build identifier remains 0.1.0-access-mcp-preview.2. Built from private working-tree changes based on 4d4d58fd8709608546aca809d6a461ea5e035677; this is not a clean committed-source build. Private source and history are not included in GitHub assets. Required embedded PowerShell/JavaScript runtime programs are part of the executable. This tag's automatic source archives contain only distribution metadata.

SHA-256 (agpc.exe): 1fba392d0119ffc5e0743cea0bdc102732aa3cd9cdf8e0002b4a6d1df3dccda9
