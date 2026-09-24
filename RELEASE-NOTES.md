AGPC Windows x86-64 outbound-access preview with FreeRDP 3.31.1 and native MCP packaging. **Unsigned prerelease; not the full AGPC host installer.**

Download `agpc.exe`, run it, and approve Windows UAC when prompted. No Docker or WSL is required. FreeRDP is downloaded when missing, so its initial provisioning requires Internet access.

Included:
- Embedded native Sphere/Mote access transport and `mote-proxy`.
- Automatic SDL FreeRDP client detection/provisioning, pinned to FreeRDP **3.31.1-1** (MSYS2 UCRT64 x86-64). `agpc.exe rdp connect machine-name.mote` uses the independent Mote RDP channel; it does not tunnel through SSH.
- Native `mote-mcp-ultra` 0.3.0 binaries with deny-by-default policy, plus bounded MCP discovery and diagnostics.
- Local CDP browser preview and independent channel status reporting.

Limits:
- Windows Home supports the outbound RDP client. FreeRDP does not enable a Windows Home RDP server.
- This artifact has the `agpc.windows-access/v1` outbound profile. It does not include `moted` or provision a complete inbound host installation. Use it for outbound access; do not treat it as a full-host replacement.
- Full uChat, contextd, Redis and CoD integration is not included as an accepted working stack. Remote CDP admission/broker lifecycle is not implemented.
- Remote SSH/RDP, MCP authorization/tool execution and a clean-machine install have not been accepted for this exact build. Existing services alone do not establish readiness.
- The new managed SSH host-key runtime is not included in the embedded transport components. SSH authentication and host-key verification remain required.
- The EXE has no Authenticode signature. Checksums verify integrity and do not constitute Windows publisher signing.

Validation: native x64 Go tests and vet passed; the complete native probe, MCP contract, OpenSSH/FreeRDP provisioning, channel isolation, bundle validation and installer transaction suites passed in Windows PowerShell 5.1 and PowerShell 7. These include fixtures/mock services; they are not remote end-to-end acceptance.

Distribution version: `0.1.0-host-access-preview.2`. Internal build version: `0.1.0-access-mcp-preview.2`. Source commit: `4d4d58fd8709608546aca809d6a461ea5e035677`, maintained only in private GitLab. GitHub receives runtime artifacts and distribution metadata, not the private source tree/history. The automatically generated source archives for this tag contain only release metadata.

SHA-256 (`agpc.exe`): `fe057e80ffb0f31788f354b21d3d7cea158138090b766b228bc95c04cfa040da`.
