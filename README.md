# Agent Computer Debian Distribution

```text
Agent Computer = agent-sphere.deb + agent-apps.deb

agent-sphere                       agent-apps
  sphered                            agos
  moted                              model-router
  mote-proxy                         model-llm
  mote-transportd                     cx-agent
  medge                              ss-webos
  mlink                              mdesk
                                     obsidian
                                     uchat
                                     mote-bridge-mcp
                                     mote-vault-sync
                                     mote-vault-syncd
                                     mote-secd
                                     codex-mesh

MEdge = MBox + MDrive + MCP
```

Agent Sphere supplies the system substrate. Agent Apps composes thirteen
applications. APT/DPKG resolves the two entry packages and systemd manages each
component's lifecycle. AGOS runs agent modules and requests model resources
through the combined Model Router; Model LLM performs inference through its
configured backend. CX Agent supplies admitted Codex execution.

MEdge owns MBox admission/dispatch, bounded local MDrive objects and fixed MCP
tools. Its MCP extension uses the Apps-owned Mote Bridge MCP server. Local
I/O follows MoteD admission to MEdge and MLINK.

## Installation

The permanent installer URL is
**https://motebus.github.io/download/agent-sphere-apps.sh**.
Every installer release must update this exact GitHub Pages path after the
required package, signature and dependency checks. Keep the URL and plural
`agent-sphere-apps.sh` filename stable across versions. Publish its matching
`.asc`, `agent-sphere-apps.source.json` and source-record signature together.
A release is complete only after download readback from this URL matches the
reviewed installer digest and its archive signature verifies. GitHub Release
assets retain versioned history; user-facing installation links use this
permanent URL.

Use [`agent-sphere-apps.sh`](https://motebus.github.io/download/agent-sphere-apps.sh)
from this site after configuring the trusted signed MoteBus APT repository.
The [detached signature](https://motebus.github.io/download/agent-sphere-apps.sh.asc)
and [source release record](https://motebus.github.io/download/agent-sphere-apps.source.json)
bind the script to the reviewed Agent Sphere release. Verify the signature
with the trusted archive key before running the downloaded script using sudo.

The installer downloads and verifies the official upstream Obsidian DEB, then
installs both entry packages in one APT transaction. Obsidian is not mirrored
in this repository or the aggregate release. Its Vault and user configuration
remain under the desktop user's ownership. The installer does not select a
Vault, enable its sync plugin, download model weights, or provide model and
transport credentials.

Fresh installation selects twenty-one canonical packages. A migrated host may
also retain one documentation-only `mote-chatd` record protecting locked DPKG
configuration ownership. Only `mote-transportd` owns the messaging runtime.
The installer admits only the reviewed CX, Vault Sync and inference package
renames, and checks the final APT transaction before DPKG runs. It refuses
unrelated removals, downgrades and retirement of that protected record.

The supported product names are `cx-agent`, `model-router`, `model-llm`,
`mote-vault-sync` and `mote-vault-syncd`. There is no generic `agent.deb` or
separate Model Grid package. Historical `model-node`, `cx-node`, `mcp-run`,
`ultra-mcp-ssh` and the singular `agent-app` are outside the new composition.
Existing wire/configuration identifiers remain where compatibility requires.

## Release and acceptance contract

`agent-computer-apt-overlay.json` pins the aggregate
`motebus/download` release `agent-computer-v0.1.0-1`. The v3 contract admits
exactly twenty redistributable canonical DEBs, the optional protected retention
record, and one external official Obsidian prerequisite. Every runtime pin
records the actual successful committed-main build and reviewed payload digest.
The public aggregate contains no private implementation source or private
source-server address. Released artifacts and historical manifests are immutable.

The protected publication workflow validates those exact DEBs, their metadata
and safe archive permissions, signs the APT index and public pin set with the existing archive key,
and checks automatic resolution in clean Ubuntu 24.04 and 26.04 containers.
The full fixture seeds only the verified official Obsidian prerequisite before
resolving `apt install agent-sphere agent-apps`. It never seeds native runtime
components or the legacy retention record on a fresh host.

Package availability and resolver success do not establish full system
readiness. Live UltraOne/D/MSG connectivity, owner admission, real inference,
CX effective tool policy, a selected Vault and sync path, and reboot recovery
require separate runtime acceptance. Initial process fixtures cover the native
AGOS → Router → Model LLM chain with a test backend and
MCP → MoteD → MBox → MDrive with isolated local objects.

## Historical installation and removal

The existing v19 base remains available byte-for-byte alongside the new APT
versions. Its fixed legacy installer profiles describe that historical release.
They do not define the new two-package product.

For the active v3 composition, the root `uninstall.sh` refuses automatic removal
before inspecting or changing services, packages or data. This also protects
partial installations containing only shared runtime package names.
Full removal awaits a safe migration of protected configuration ownership.
Removing the two metapackages alone is not full runtime removal. The immutable
legacy uninstaller, manifest and checksum file are archived under
`legacy/medge-v5.10.0-1/`; that script is unsuitable for current Agent Computer
cleanup. Personal Vaults and locked transport identities must be preserved.

The following sections record historical transport releases and their original
contracts.

## Historical Mote Transport target-selector bundle

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

That historical bundle's application path is `schat -> local schatd -> local mote-proxy ->
D/MSG -> target moted -> remote schatd -> remote schat`. Interactive commands
`/help`, `/status`, `/inbox`, and `/quit` remain local and are never sent as
MSG payloads. Before its first prompt, interactive Schat performs a payload-free
connect through that complete path and prints `ready to chat` only after the
remote SchatD confirms the session. Its retired names and routing describe that
immutable bundle; the current UChat package contract is described below.

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

## Published v18 package set

The `medge-public-release/v18` contract replaces the physical `sphere` package
with `sphered` and updates dependent packages and systemd references together.
The installer URL remains `sphere.sh`; it selects sixteen packages and leaves
`ultra-mcp-ssh` to `sshkit.sh`. There is no legacy executable or service alias.
Sphered preserves trusted existing normal configuration during the explicit
package migration and keeps MoteBus data intact. Existing MoteChat topology
files remain unchanged. Historical v17 release evidence remains immutable.

The MoteChatD upgrade check includes an existing root-owned `0640` topology
conffile. It verifies that package upgrades preserve that file while the
service user validates the environment loaded by systemd. A separate read-only
root preflight checks the original files. Installation and configuration checks
do not establish live MoteBus registration or message-delivery readiness.

The v18 package set uses native Rust for MoteD, Mote Proxy, UChat, MoteChatD,
MDesk, Mote SecD, Mote Sync, and the complete Mote Bridge MCP facade. Medge
also uses Rust for its controller, scheduler, provider, and create-once
configuration helper. Rust is the default for Debian-owned runtime code;
maintainer scripts and build-time checks remain separate from the installed
runtime. The MLink shared C ABI, Obsidian plugin, and external browser and
MoteBus runtimes retain their required implementation languages.

Mote Bridge MCP 3.0 sends Screen and Telegram requests directly through
Sphered-native MoteBus contracts (`screen://spec` + `screen://mms` and
`tg://spec` + `tg://mms`). It is a peer of UltraMCP SS and UltraMCP Comm:
Codex selects one provider directly, Mote Bridge never calls those providers,
and no MCP provider may call another MCP provider. It does not mirror outbound
Codex Mesh sends. After `mote-chatd` durably commits a new, non-duplicate
`app=codex` inbox record, its internal `inbox-mirror` publishes an
`event/codex-inbox` event through logical `rc/broker`. Ehandle subscribes to
that event and sends the summary and packet identity through Comm's registered
`*codex-mesh` Telegram target. Operational logs remain local; mirror failure is
non-authoritative and never retries or rolls back inbox acceptance.

`medge-v5.9.0-1` extends the native migration to these runtime helpers:

| Package | Version | Native runtime scope |
| --- | --- | --- |
| `sphered` | `4.1.0-2` | Controller, launcher, provider |
| `mlink` | `2.0.0-1` | Broker, daemon, CLI, HID and CEC helpers |
| `mdesk` | `3.0.0-5` | Graphical-session provider |
| `mote-proxy` | `2.0.0-3` | SSH proxy and transport handoff checker |
| `ultra-mcp-ssh` / `mcp-run` | `2.0.0-1` | MCP-over-SSH client and restricted execution |
| `codex-mesh` | `1.0.0-1` | Mesh CLI and bounded local broker client |

The release also upgrades SS-WebOS to pinned Electron 44.2.0 and Node
24.20.0, enables Chromium renderer sandboxing and context isolation, and
rejects sandbox-disabling arguments. Package preparation verifies the complete
Electron executable, and graphical acceptance exercises the packaged runtime
on Ubuntu 24.04 and 26.04. Sync client and server updates are paired at
`1.1.0-2` for the revision protocol.

The signed release manifest remains the authority for published versions.

`medge-v5.9.0-8` upgrades MoteD to `3.5.0-8`. Host registration now
requires the complete successful terminal acknowledgement; an incomplete reply
cannot mark the host ready. Mote Proxy retains exact host lookup through
`rc.resolve`. The other sixteen package versions and all four release scripts
remain pinned to the preceding release.

Hosts use `<hostname>.mote`, for example `host-a.mote`. MoteD registers
`type: "moted", key: "host-a"` and renews that record. `rc.register`
automatically captures the source MMA from MoteBus; callers do not supply an
MMA or look one up before registration. Mote Proxy uses `rc.resolve` when a
host is accessed. `local.mote` selects the current host's same record.

The accompanying MoteC service correction restores `rc://spec` and
`rc.resolve` dispatch after MoteBus resolves a logical Resource Center to its
native application. It addresses the server's `undefined ... apply` error
that could appear as `Target MMA not found` in Mote Proxy. This service update
is distributed as a Redixs OCI release; the signed Sphere Debian package
manifest remains the package-version authority.

### Terminal setup and chat

`medge-v5.9.0-3` updates MLink to `2.0.0-3`. Run `mlink` or `mlink setup`
for a single reader list: press **Y** to use a reader or **N** to disable it.
Names are assigned automatically. A unique serial identifies the reader;
otherwise setup shows the local port binding. Each choice advances to the
next reader. Saved choices and actual capture readiness are shown separately.
Model editing, additional devices, and private scan tests remain available
with `mlink setup --advanced`.

`medge-v5.9.0-2` pairs `mlink 2.0.0-2` with `moted 3.5.0-4` and includes
`uchat 2.0.0-3`. Both MLink setup and UChat use native Rust terminal interfaces.
After installing the signed release, enable and start the services required by
MLink setup. This first command requires local administrator privileges:

```bash
sudo systemctl enable --now mlink.service moted.service
```

Then run the terminal interfaces as your normal operator user:

```bash
mlink setup
uchat
```

MLink setup lists supported readers and saves each PC's enrollment by hardware
serial or the displayed local port. Device names and event numbers are resolved
at runtime. Y enrolls a new reader and requests enable through MoteD. Advanced
setup provides support editing, disabled enrollment and private scan tests; frontend
keystrokes are suppressed while the reader holds exclusive capture and its
MoteD admission remains valid. Setup requires root or membership in the local
`mote` operator group. The initial reader support uses the US keyboard layout
with Enter or Tab termination. Physical-reader acceptance remains separate from
package validation.

If setup reports `SETUP_UNAVAILABLE: No such file or directory`, check
`systemctl status mlink.service moted.service`. MLink's package leaves its
service disabled on installation; the service-start step above is required
before setup can reach its control socket. After both services are running,
press `r` in setup to refresh. Starting the services does not enroll or enable
new readers.

The renewed `sphere.sh` also handles the Microsoft Edge stable repository GPG
error that can block APT before Sphere installs. It downloads Microsoft's
original release key from the [official key source](https://learn.microsoft.com/en-us/linux/packages),
checks its pinned fingerprint and verifies the live Edge repository signature
before repairing only Edge's `Signed-By` configuration. It supports `.list`
and `.sources` files, including embedded keys, and keeps originals under
`/var/backups/sphere-edge-apt-*`. It then retries APT with signature checking
still enabled. Mixed-repository stanzas and unsafe files require manual repair;
an unrelated repository failure still stops installation.

UChat provides the local inbox and peer conversations, terminal selection for
copying, explicit `/copy` commands where the terminal permits clipboard writes,
and bracketed multiline paste that stays in the draft until Enter is pressed.
Chat setup and delivery remain owned by MoteChatD.

An approved `medge-public-release/v18` bundle contains these independent Debian
packages in dependency-safe audit order:

```text
sphered
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
`sphered + mlink + mdesk + ss-webos`, and `sshkit.sh` for
`sphered + moted + mote-proxy + mote-secd + mote-bridge-mcp + ultra-mcp-ssh + mcp-run + mote-sync + mote-syncd + mote-chatd + uchat`.
`uninstall.sh` performs a bounded purge of the approved seventeen-package set
and the exact installer-managed APT source/key. All former
`install*.sh` and `*-install.sh` entries are retired without aliases.
Existing tags and release assets remain immutable historical evidence; they
are not copied into the new Pages site.

## Trust chain

The protected private owner creates a v18 bundle from exact private-source `main` or an
explicitly approved immutable rollback tag. This repository then:

1. validates the exact seventeen-package manifest, assets, SHA-256 checksums, env
   provenance, and the four executable release scripts;
2. installs the bundle in pinned Ubuntu 24.04 and 26.04 amd64 containers;
3. constructs the APT index from only that approved bundle;
4. signs `Release`, `InRelease`, and `release-manifest.json.asc` with the
   protected archive key; and
5. publishes the resulting site through GitHub Pages.

Before publication, the exact admitted CI bundle must pass the pinned Ubuntu
24.04/26.04 install/reinstall tests and all four protected-topology checks.
Record the source revision, test-script digest, manifest digest and all 23 asset
digests. An authorized engineering workstation may run these checks against
remote CI artifacts, using its existing approved Docker bridge and bounded
resources. This does not permit local package substitution or repacking.
The signing workflow consumes published release tags and repeats compatibility
checks before importing the protected archive key and deploying Pages.

The content auditor preserves the official Node 24.20.0 linux-x64 binary in
`ss-webos` at `usr/lib/ss-webos/node/bin/node`, only with SHA-256
`89af8424dd53e560b1933f87ba650d8bf57c83ca5a04600eefb31f416aabbae7`.
Its two public GitLab blog references are embedded upstream comments. The reviewed
official archive `node-v24.20.0-linux-x64.tar.xz` has SHA-256
`2f2c0da162318f0de47665410c7c8c2ed3d36c8f3105de4bbc61176c70a7cbf2`.
This exact vendor-file exception does not admit other files, changed bytes, private
configuration, or a GitLab APT acquisition origin. The separate exact Chromium
license-notice approvals remain in force.

The official Electron 44.2.0 linux-x64 executable is separately admitted only
for `ss-webos` at `usr/lib/ss-webos/runtime/node_modules/electron/dist/electron`,
with SHA-256 `9b827d38aacff0d69933481625c4c8f13b4732cbecd0e3477b1d2bac6102522c`.
Its official archive `electron-v44.2.0-linux-x64.zip` has SHA-256
`574f7d8cd2a82d77812849729a282b86639b050de120d58b138a126d16b48692`.
This exact binary contains the same two public upstream proxy-comment references;
its bytes, package boundary, and acquisition-origin requirements are preserved.

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
manifest-pinned `/usr/sbin/sphered post-install` command. The installers do not write user
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

After an approved v18 release has completed the Pages workflow, an ordinary
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

During the physical `sphere` to `sphered` upgrade, the installer permits only the
old `sphere` package removal. An APT pre-install hook checks the actual transaction
under the package-manager lock and rejects every other removal before dpkg runs.
Ordinary installs keep APT removal disabled. Old conffiles remain available to the
Sphered package migration; unrelated packages and user data remain outside this step.

## Agent Computer overlay v3 (prepared, inactive)

The existing tracked two-package overlay remains active until a separately
reviewed release changes `agent-computer-apt-overlay.json`. Schema
`agent-computer-apt-overlay/v3` adds the complete Agent Computer composition
without changing any legacy `medge-public-release/v19` catalog or installer
subset. It is a release publication contract, not a new package manager.

The canonical composition is exactly 21 packages: `agent-sphere`, `agent-apps`,
six Sphere components, and thirteen Apps components. The builder checks the
actual metapackage `Depends` fields against these ownership boundaries:

- Sphere: `sphered`, `moted`, `mote-proxy`, `mote-transportd`, `medge`, `mlink`.
- Apps: `agos`, `ss-webos`, `mdesk`, `mote-bridge-mcp`, `cx-agent`, `uchat`,
  `mote-vault-sync`, `mote-vault-syncd`, `mote-secd`, `codex-mesh`, `obsidian`,
  `model-router`, `model-llm`.

The v3 `release` object has exactly `repository`, `tag`, `source_commit`,
`packages`, `external_prerequisites`, and `retention_packages`. Its sole archive
source is `motebus/download`, with an exact `agent-computer-v<version>` tag
resolved to the recorded public commit. `packages` lists the twenty
redistributable packages in canonical order (the list above, excluding
Obsidian). Each record contains `name`, `version`, `architecture`, `asset`,
`sha256`, and `provenance`. The two metapackages are `all`; their runtime
components are `amd64`. Local preview versions are not publishable.

Each provenance record contains the actual `source_commit`,
`source_ref: refs/heads/main`, positive `main_pipeline_id`,
`build_status: success`, and `public_payload_reviewed: true`. These fields are
reviewed promotion evidence, not permission to invent successful CI or infer
approval. The publication owner must verify them against the completed source
pipeline and exact downloaded artifact before activating pins. Private URLs and
private deployment context must not be published. Existing public payload scans
remain mandatory; direct payloads at locked `/etc/**-mchat.env` paths are
rejected. Reviewed bootstrap templates remain bound to the exact DEB digest.

Obsidian is the sole `external_prerequisites` record, with `name`, `version`,
`architecture`, `asset`, `sha256`, `url`, and `redistribute: false`. Only the exact
versioned official `obsidianmd/obsidian-releases` GitHub asset URL is admitted.
Its SHA and Debian identity are checked separately; its DEB never enters the
aggregate release or the published APT site. Installing Apps requires this
upstream prerequisite to be available to APT in the same transaction or already
installed. Desktop installation does not
provision or modify user vaults.

`retention_packages` is empty or contains one explicit `mote-chatd` package with
the same record fields and `Architecture: all`. It must have documentation-only
payload and no `Provides` runtime alias. This guard is solely for reviewed
migration of existing configuration ownership; it is excluded from fresh
canonical membership and must not be selected by either fresh-install plan.
CX uses direct replacement and has no retention package. Retired runtimes
`mcp-run`, `ultra-mcp-ssh`, `model-node`, `model-grid`, `mote-sync`, `mote-syncd`,
`cx-node`, and `mote-chatd` are forbidden in fresh plans. Historical base DEBs
remain available byte-for-byte for legacy consumers.

Every base publication reloads the approved overlay. Optional workflow input
`agent_computer_tag` must match its active v3 tag; it cannot substitute another
release. The existing protected signing environment and immutable base
compatibility job remain in place. After signing, clean digest-pinned Ubuntu
24.04 and 26.04 images each check Sphere alone and the two-package Apps
composition. Only the exact official Obsidian prerequisite is seeded for the
latter. APT uses native signature checks, resolves all canonical component
versions automatically, and must select no retired runtime, guard, or removal.
The signed index and actual pool bytes must match every approved SHA.

Activation requires real main-CI artifacts, reviewed source and release
pins, protected workflow success, and signed deployed-index readback. Package
publication does not establish full runtime readiness.
Full uninstall remains unsupported pending a reviewed retention dependency
migration. A v3 site serves the reviewed preflight at root `uninstall.sh`, with
its own archive signature. It refuses the new composition before mutation and
preserves configuration and user vaults. The byte-identical base uninstaller,
manifest, and checksums remain under `legacy/medge-v<base-version>/`; the copied
manifest signature remains verifiable with the archive key. A legacy manifest
cannot authenticate the changed root script: its recorded digest differs, so
legacy signed callers reject it before mutation. The historical script remains
unsuitable for full Agent Computer cleanup.
