# Install Sphere Debian Distribution

This public repository is the reviewed GitHub release and signed APT boundary
for the Sphere/Mote Transport Debian aggregate. Private implementation source,
GitLab addresses, credentials, topology, source packages, and loose env files
are forbidden here.

## Mote Transport Dual Channel v0.1

The standalone GitHub release `mote-transport-v2026.09.02-1` carries the
first component-qualified Dual Channel binary bundle:

```text
mote-proxy 1.5.0-1   B/SSH + D/MSG local ingress
moted      3.2.0-35  B -> sshd, D -> chatd dispatch
chat       0.1.0-1   D/MSG client
chatd      0.1.0-1   independent MSG service and local app inbox
```

MSG uses native xMSG between one Mote Proxy and the target MoteD. MOTESSH,
MOTERDP, and RDP remain retired. This standalone release does not replace or
modify the current signed MEdge APT aggregate or its GitHub Pages installer.

## Current v10 package set

The latest approved bundle is `medge-v5.1.0-13`.

An approved `medge-public-release/v10` bundle contains these independent Debian
packages in dependency-safe audit order:

```text
sphere
moted
medge
mlink
mdesk
ss-webos
mote-proxy
motemcp
ultra-mcp-ssh
mcp-run
cx-pivot
mote-sync
mote-syncd
```

The bundle includes the active Sphere runtime catalog. `ultra-mcp-ssh` and
`mcp-run` are the strict MCP-over-SSH client and target data-plane packages;
they do not restore the retired MCP mode proxy. CX Pivot keeps its independent
CX ownership. `mote-sync` and `mote-syncd` are the client and
endpoint packages used by the Sync-service acceptance row. WebOS Server, SS
Server, Redixs, and every other OCI-only service are excluded; `ss-webos` is
the independent Debian client runtime and remains included.

The five Mote Transport service rows are SSH, SFTP, Git, MCP over SSH, and
Sync for an Obsidian Vault. Install Sphere provides their approved Debian
package prerequisites, but it never discovers, creates, selects, modifies, or
copies a Vault. Vault pairing and runtime Sync acceptance remain separate
post-install operations owned by `mote-sync` and `mote-syncd`.

`medge` and `cx-pivot` are independent package boundaries. Their publication
and installation do not depend on or query UltraMap. Historical `cx-node`
release evidence does not create an UltraMap relationship.

There is no aggregate `sphere`, `medge-core`, or `medge-all` meta-package.
`vdevice` remains optional and separate.

## Clean break

The current signed release surface contains exactly four scripts:
`sphere.sh` for all thirteen packages, `webdesk.sh` for
`sphere + mlink + mdesk + ss-webos`, and `sshkit.sh` for
`sphere + moted + mote-proxy + motemcp + ultra-mcp-ssh + mcp-run + mote-sync + mote-syncd`.
`uninstall.sh` performs a bounded purge of the approved thirteen-package set
and the exact installer-managed APT source/key. All former
`install*.sh` and `*-install.sh` entries are retired without aliases.
Existing tags and release assets remain immutable historical evidence; they
are not copied into the new Pages site.

## Trust chain

The protected private owner creates a v10 bundle from exact GitLab `main` or an
explicitly approved immutable rollback tag. This repository then:

1. validates the exact thirteen-package manifest, assets, SHA-256 checksums, env
   provenance, and the four executable release scripts;
2. installs the bundle in pinned Ubuntu 24.04 and 26.04 amd64 containers;
3. constructs the APT index from only that approved bundle;
4. signs `Release`, `InRelease`, and `release-manifest.json.asc` with the
   protected archive key; and
5. publishes the resulting site through GitHub Pages.

The installer pins archive fingerprint
`AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0`, verifies the manifest detached
signature, accepts only the exact Pages `.sources` definition, proves every
manifest version is present in the signed APT source, performs one APT
transaction, and verifies installed versions. Before `sphere.sh` or
`sshkit.sh` reports success, it also proves the package-owned system OpenSSH
profile and helper have their exact root ownership and modes and that `ssh -G`
selects the helper for a typed `.mote` target. The installers do not write user
SSH configuration or duplicate the package-owned proxy rule. They reject any
GitLab URL in the resolved package plan.

Those two profiles then run the manifest-pinned `sphere post-install` command.
It emits deterministic PASS/WARN/FAIL results and returns non-zero for an
essential unit, TCP/6262, relay socket, configuration, or `mote-proxy doctor`
failure. Its bounded noninteractive `ssh local.mote` smoke uses strict
host-key checking and is only a warning because registration and trust
admission can be external to package correctness.

`uninstall.sh` verifies the same signed manifest and fingerprint before any
destructive action, requires an exact unmodified installer-managed source/key,
and simulates APT purge first. It refuses a plan that would remove anything
outside the thirteen signed package identities. It does not run `autoremove`,
recursively delete paths, or remove user data, SSH identities, Obsidian vaults,
unrelated packages, or non-Sphere services. After the package purge it removes
the exact package-owned `/etc/ssh/ssh_config.d/50-mote-proxy.conf` profile; a
modified or symlinked profile is preserved and causes a visible failure.

After an approved v10 release has completed the Pages workflow, install with:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://motebus.github.io/download/sphere.sh | sudo bash
```

Each release script fetches the manifest and detached signature from that same
Pages origin before making any APT change unless an operator explicitly
supplies a local signed pair through `MEDGE_RELEASE_MANIFEST` and
`MEDGE_RELEASE_MANIFEST_SIGNATURE`. A stale manifest beside a downloaded
script is never reused. The raw `main` script on GitHub is source-review
material, not an approved installation source.

To remove only that bounded Sphere package surface from an admitted host:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://motebus.github.io/download/uninstall.sh | sudo bash
```

## L5/L6 post-install support path

A new L5 or L6 runs the signed `sphere.sh` locally, optionally launched by its
local Codex CLI. Codex is not a runtime dependency of `mote-proxy`; only the
independent `cx-pivot` integration may consume a Codex client when available.
After MoteD has registered the new host and the operator has separately admitted
L1 host-key and public-key authentication, a support session may use:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes medge-home.mote
```

The installer never starts that session automatically, accepts a first-use
host key, provisions credentials, sends logs, or selects a support target. A
future App Suite Supporting Center is a separate post-install consumer and
requires its own owner contract, fixed operation, admission, report schema,
retention policy, and tests; it is not a Sphere package or release asset.

Do not install from a local checkout, a loose artifact copy, or a private
GitLab URL.

## Publication gates

Normal branches validate only. Publication requires an immutable approved
`medge-v<version>` GitHub release, protected `release` environment access, both
archive-signing secrets, successful compatibility validation, and a successful
GitHub Pages deployment. Existing tags and assets are never replaced.

L1 and L9 installation is a separate gate: both endpoints must appear in the
authoritative target inventory with explicit host identity, owner admission,
an approved signed release reference, and an authorized installation window.
UltraMap is not part of this gate.
