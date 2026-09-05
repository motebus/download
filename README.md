# Install Sphere Debian Distribution

This public repository is the reviewed GitHub release and signed APT boundary
for the Sphere/Mote Transport Debian aggregate. Private implementation source,
GitLab addresses, credentials, topology, source packages, and loose env files
are forbidden here.

## Mote Transport target selectors

The standalone GitHub release `mote-transport-v2026.09.03-2` publishes the
component-qualified target-selector bundle:

```text
mote-proxy 1.6.0-1   B/SSH + D/MSG selector enforcement and resolution
moted      3.2.0-44  B -> sshd; D connect/send -> target schatd app inbox
schat      0.6.0-1   accept .mote/.mma and reject .local D/MSG targets
schatd     0.4.0-1   enforce the same D/MSG target policy
```

`host.local` remains ordinary OpenSSH LAN/mDNS addressing for B/SSH only and
is never intercepted by Mote Proxy. `host.mote` provides B/SSH and D/MSG
through Mote Proxy and is the only selector that queries MoteC with
`rc.query type=moted`. A lower-case `xxx.xxx.mma` provides B/SSH and D/MSG by
stripping only the final `.mma` and using exact `xxx.xxx` as the MMA, without
querying MoteC. There is no suffix conversion or fallback, and callers cannot
supply raw MMA transport fields.

The canonical application path is `schat -> local schatd -> local mote-proxy ->
D/MSG -> target moted -> remote schatd -> remote schat`. Interactive commands
`/help`, `/status`, `/inbox`, and `/quit` remain local and are never sent as
MSG payloads. Before its first prompt, interactive Schat performs a payload-free
connect through that complete path and prints `ready to chat` only after the
remote SchatD confirms the session. MOTESSH, MOTERDP, and RDP remain retired.

Verify the exact four-package application chain without installing or changing
the host runtime:

```bash
node scripts/verify-dual-channel-bundle.js \
  --assets-dir /path/to/downloaded/release-assets \
  --output dual-channel-e2e.json
```

The verifier extracts the published Debian packages and executes the actual
packaged `schat`, `schatd`, Mote Proxy MSG, and MoteD MSG-dispatch modules across
temporary Unix sockets. Its D/MSG bridge is intentionally in-process, so a pass
qualifies the package chain but does not claim live MoteBus or two-endpoint
runtime acceptance. It also proves that a `local.mote` self-delivery terminates
as one idempotent inbox record and never re-enters the outbound path. Mote
Transport releases run this gate in their own GitHub Actions workflow. The
older releases remain immutable historical evidence.

## Current v17 package set

The immutable v16 baseline adds the component-qualified S/SEC status owner and
Mote Bridge MCP 2.2. The `medge-public-release/v17` contract replaces the
retired Schat package names with `mote-chatd` and `uchat`, and advances Codex
Mesh to its `mote-chatd` app inbox boundary. The install-only `sphere.sh`
profile selects sixteen
rows and leaves `ultra-mcp-ssh` to the dedicated `sshkit.sh` profile.
Publication remains an owner-approved, signed `medge-v<version>` operation.

Mote Bridge MCP 2.3.1 sends Screen and Telegram requests directly through
Sphere-native MoteBus contracts (`screen://spec` + `screen://mms` and
`tg://spec` + `tg://mms`). It is a peer of UltraMCP SS and UltraMCP Comm:
Codex selects one provider directly, Mote Bridge never calls those providers,
and no MCP provider may call another MCP provider. It does not mirror outbound
Codex Mesh sends. After `mote-chatd` durably commits a new, non-duplicate
`app=codex` inbox record, its internal `inbox-mirror` publishes an
`event/codex-inbox` event through logical `rc/broker`. Ehandle subscribes to
that event and sends the summary and packet identity through Comm's registered
`*codex-mesh` Telegram target. Operational logs remain local; mirror failure is
non-authoritative and never retries or rolls back inbox acceptance.

The new S component versions admitted by that contract are:

```text
mote-proxy 1.7.0-1   B/SSH + S/SEC selector enforcement and resolution
moted      3.3.0-1   B -> sshd; S -> mote-secd fixed dispatch
mote-secd  0.1.0-1   S/SEC status owner; authority mutations fail closed
mote-chatd 1.1.0-1   durable app inbox plus post-commit event/codex-inbox publication
uchat      1.0.0-4   app=uchat default; home/general aliases; /app view
```

An approved `medge-public-release/v17` bundle contains these independent Debian
packages in dependency-safe audit order:

```text
sphere
moted
medge
mlink
mdesk
ss-webos
mote-proxy
mote-secd
mote-bridge-mcp
ultra-mcp-ssh
mcp-run
cx-node
mote-sync
mote-syncd
mote-chatd
uchat
codex-mesh
```

The bundle includes the active Sphere runtime catalog. `ultra-mcp-ssh` and
`mcp-run` are the strict MCP-over-SSH client and target data-plane packages;
they do not restore the retired MCP mode proxy. `ultra-mcp-ssh` remains in the
bundle for `sshkit.sh`, but is not selected by `sphere.sh`. CX Node keeps its
independent CX ownership. `mote-sync` and `mote-syncd` are the client and
endpoint packages used by the Sync-service acceptance row. WebOS Server, SS
Server, Redixs, and every other OCI-only service are excluded; `ss-webos` is
the independent Debian client runtime and remains included.

The five B/SSH service rows are SSH, SFTP, Git, MCP over SSH, and Sync for an
Obsidian Vault. D/MSG adds UChat through `mote-chatd` and `uchat`, independent
of MoteD and Mote Proxy. Install Sphere provides their approved Debian
package prerequisites, but it never discovers, creates, selects, modifies, or
copies a Vault. Vault pairing and runtime Sync acceptance remain separate
post-install operations owned by `mote-sync` and `mote-syncd`.

`medge` and `cx-node` are independent package boundaries. Their publication
and installation do not depend on or query UltraMap. Historical `cx-pivot`
release evidence does not create an UltraMap relationship or compatibility
alias.

There is no aggregate `sphere`, `medge-core`, or `medge-all` meta-package.
`vdevice` remains optional and separate.

## Clean break

The current signed release surface contains exactly four scripts:
`sphere.sh` for sixteen packages (all catalog rows except `ultra-mcp-ssh`),
`webdesk.sh` for
`sphere + mlink + mdesk + ss-webos`, and `sshkit.sh` for
`sphere + moted + mote-proxy + mote-secd + mote-bridge-mcp + ultra-mcp-ssh + mcp-run + mote-sync + mote-syncd + mote-chatd + uchat`.
`uninstall.sh` performs a bounded purge of the approved seventeen-package set
and the exact installer-managed APT source/key. All former
`install*.sh` and `*-install.sh` entries are retired without aliases.
Existing tags and release assets remain immutable historical evidence; they
are not copied into the new Pages site.

## Trust chain

The protected private owner creates a v17 bundle from exact private-source `main` or an
explicitly approved immutable rollback tag. This repository then:

1. validates the exact seventeen-package manifest, assets, SHA-256 checksums, env
   provenance, and the four executable release scripts;
2. installs the bundle in pinned Ubuntu 24.04 and 26.04 amd64 containers;
3. constructs the APT index from only that approved bundle;
4. signs `Release`, `InRelease`, and `release-manifest.json.asc` with the
   protected archive key; and
5. publishes the resulting site through GitHub Pages.

The installer pins archive fingerprint
`AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0`, verifies the manifest detached
signature on a protected private snapshot before parsing it, and accepts only
the exact Pages `.sources` definition. Each run uses isolated APT indexes and
archives, requires the exact Pages pool origin and signed asset identity for
every acquired catalog package, and checks its SHA-256 and Debian metadata
before installation. A same-version installation is reacquired and verified.
The final APT transaction uses only the verified downloads, exact
`name=version` pins, `--allow-downgrades`, and `--no-remove`, then checks
installed states and versions. Planning and downloading also refuse removals.
It does not admit unpinned downgrades,
essential-package removal, or held-package changes. `sphere.sh` ends after the
signed package transaction and installed-version checks; it does not perform
SSH, runtime, transport, or target-connectivity tests. Package maintainer
scripts own service activation and configuration handling.

Before `sshkit.sh` reports success, it proves the package-owned system OpenSSH
profile and helper have their exact root ownership and modes, verifies that
`ssh -G` selects the helper for a typed `.mote` target, and runs the
manifest-pinned `sphere post-install` command. The installers do not write user
SSH configuration or duplicate the package-owned proxy rule. They reject any
GitLab URL in the resolved package plan.

`uninstall.sh` verifies the same signed manifest and fingerprint before any
destructive action, requires an exact unmodified installer-managed source/key,
and simulates APT purge first. It refuses a plan that would remove anything
outside the seventeen signed package identities. It does not run `autoremove`,
delete persistent data directories, or remove user data, SSH identities,
Obsidian vaults,
unrelated packages, or non-Sphere services. After the package purge it removes
the exact package-owned `/etc/ssh/ssh_config.d/50-mote-proxy.conf` profile; a
modified or symlinked profile is preserved and causes a visible failure.

After an approved v17 release has completed the Pages workflow, an ordinary
interactive operator may install with:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://motebus.github.io/download/sphere.sh | sudo bash
```

Each release script fetches the manifest and detached signature from that same
Pages origin before making any APT change unless an operator explicitly
supplies a local signed pair through `MEDGE_RELEASE_MANIFEST` and
`MEDGE_RELEASE_MANIFEST_SIGNATURE`. A partial override fails. Verification
and planning use only the invocation's protected copies, even if the original
files change. Temporary files and APT caches are removed on exit. A stale
manifest beside a downloaded script is never reused. The raw `main` script on GitHub is source-review
material, not an approved installation source.

That pipe is not the managed L1/L9 path. The managed endpoints use the
separately signed `sphere-runner-v5.2.0-3-1` routine surface, immutable failed
`sphere-runner-v5.2.0-3-2`, `sphere-runner-v5.2.0-3-3`,
`sphere-runner-v5.2.0-3-4`, `sphere-runner-v5.2.0-3-5`, and
`sphere-runner-v5.2.0-3-6` corrective evidence, and the current
`sphere-runner-v5.2.0-3-7` corrective bootstrap publication.
The corrected native
bootstrap verifies the bootstrap signature, signed runner manifest, every
artifact digest/signature, target identity, validity, public keys, and exact
digest-form sudoers rules before installation. It selects the first valid SSH
algorithm/blob record, ignores trailing blank records, compares Ed25519 public
DER rather than comment or PEM serialization bytes, and activates an exact
public-key-only SSH Match policy before making the service principal
non-locked. Runner `-7` accepts only the exact consumed `-6` L1 marker,
preserves the principal-readable public key, and installs the exact
digest-form sudoers policy under dotless includedir name
`sphere-install-l1-5203` before writing a new consumed marker.
Routine operations then require
both a target-specific restricted SSH key and a short-lived single-use
capability token delivered on stdin. L1 is the canary; L9 starts only after L1
acceptance and requires its own local native administrator bootstrap. No
password is relayed through SSH, chat, argv, environment, stdin, a file, or a
log.

To remove only that bounded Sphere package surface from an admitted host:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://motebus.github.io/download/uninstall.sh | sudo bash
```

## L5/L6 post-install support path

A new L5 or L6 runs the signed `sphere.sh` locally, optionally launched by its
local Codex CLI. Codex is not a runtime dependency of `mote-proxy`; only the
independent `cx-node` integration may consume a Codex client when available.
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

Installer source changes require a new approved release bundle and signatures;
historical release assets and their recorded digests must not be rewritten.
