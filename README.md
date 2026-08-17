# MEdge Binary Packages

This public repository distributes install-only MEdge and CX Node Debian
packages for supported amd64 hosts.

It contains distribution documentation, the public APT key, release
manifests, and GitHub Pages automation. Component source code and Debian
source packages are intentionally absent. Public install artifacts contain no
private build-system URL.

## Install

Install MEdge on Ubuntu 24.04 or 26.04 amd64 with one command:

```bash
curl -fsSLo /tmp/medge-install.sh \
  https://motebus.github.io/medge-release/medge-install.sh &&
sudo sh /tmp/medge-install.sh
```

The public installer checks the operating system and architecture, verifies
the downloaded archive key against this fingerprint, configures the signed
APT source, installs the eight MEdge packages in one transaction,
starts the MEdge system services,
and verifies that they are active:

```text
AECA A1DC DAF1 9C7B 7FEA  F0C0 82A0 E180 EDAE A7A0
```

To inspect it before installation:

```bash
curl -fsSL https://motebus.github.io/medge-release/medge-install.sh
```

The repository uses:

```text
suite:        stable
component:    main
architecture: amd64
```

It does not use `apt-key`, `trusted=yes`, or a direct DEB URL.
The installer rejects an APT transaction plan containing any GitLab URL, and
publication rejects GitLab URLs in the public tree, release manifest, APT
site, Debian control metadata, or installed package content.
It does not create or modify MChat topology or service authorization policy.
If an older dependency-only `medge` meta-package leaves APT broken after a
component version changes, the installer verifies that the installed meta
contains no maintainer scripts, removes only that meta-package, confirms that
APT is otherwise consistent, and then installs the current coordinated
release. Component packages, configuration, and runtime data are preserved.
Before the package transaction, it stops and disables existing MEdge system
units in reverse dependency order. It then enables, starts, and verifies each
unit individually in dependency order. It then requires every system service
to remain active without increasing its systemd restart count during a
30-second stability window; a transient `active` state inside a restart loop
does not pass installation.
When exactly one local graphical session is active, it also reloads and
starts the Desk and SS-WebOS user-session helpers and creates a trusted
`SmartScreen.desktop` shortcut using the packaged SmartScreen icon. On a
headless install, the shortcut is created and the helpers start at graphical
login. The hardened `deskd-device.service` handles admitted USB NFC readers,
USB QR readers, QR cameras, and IoT buttons and forwards normalized input
events through Desk; it is started and health-checked after `deskd.service`.
If a system service
fails its health check, the installer prints its status and recent journal,
then stops, disables, and resets that unit so it does not remain in a failed
state or restart loop.

## GitHub Account Setup

An owner can create or verify the public install repository and push this
checkout's `main` branch with:

```bash
./github-setup.sh
```

The script interactively asks for the GitHub account or organization,
repository name, and token. Token input is hidden and is not stored in the
repository, remote URL, Git configuration, or a persistent credential helper.
The token must be able to create or administer the target public repository
and write repository contents. For an organization target, the account must
also be allowed to create repositories in that organization.

The script refuses a dirty worktree or a branch other than `main`, never
force-pushes, and does not create a tag, GitHub Release, or stable APT
publication.

## Releases

Current approved stable release: `medge-v4.2.0-1`.

Each approved GitHub Release contains:

- the coordinated MEdge component DEBs and, beginning with schema v7, the
  separately admitted `cx-node` DEB;
- `release-manifest.json`;
- `SHA256SUMS`;
- `medge-install.sh` and `webos-install.sh`;
- `cx-install.sh` when the release contains `cx-node`;
- optional binary `.changes` and `.buildinfo` provenance.

`medge.deb` is retired. `medge-install.sh` directly installs the headless
`sphered`, `moted`, `aport`, `qbix`, `mbox`, `motestream`, `motessh`, and
`moterdp` set. `webos-install.sh` installs `desk + ss-webos`. MoteStream is the
shared EdgeOS stream layer used independently by MOTESSH and MOTERDP. MBox includes
the former MGate/UCLI roles and Qbix includes QFunc runtimes.

Every stable publication requires explicit owner approval. Existing release
tags and assets are immutable.

Historical bundles remain immutable lineage only. They never contribute
packages to the active APT index, which contains only the approved current
release.

## Unified CX Node installation

CX Node is not installed by the MEdge server profile. Download and inspect the
dedicated installer, then provide a platform-owner-approved `CX<number>` node
identity, the admitted CX Hub MMA, and an absolute bootstrap file containing
only the canonical MoteChat topology keys. The node's separately approved
`*.mote` identity is also mandatory. Do not pipe a remote script into a
privileged shell: download and inspect the installer first.

```bash
curl --proto '=https' --tlsv1.2 -fsSLo /tmp/cx-install.sh \
  https://motebus.github.io/medge-release/cx-install.sh
sudo sh /tmp/cx-install.sh install \
  --node-id CX1 --node-mote cx1.edge.mote \
  --hub-mma j22/rc/cx-hub-app \
  --bootstrap /absolute/path/cx-node-bootstrap.env
```

The installer verifies the archive-key fingerprint, uses only the signed APT
source, preserves an existing locked topology file byte-for-byte, refuses a
silent node-identity change, and does not generate SSH keys or weaken OpenSSH
policy. It installs exactly `sphered`, `moted`, `motestream`, `motessh`,
`openssh-client`, `openssh-server`, and `cx-node` for this profile.

MoteSSH｜Mote 安全连接 owns discovery, short-lived authorization, and the
MoteBus/SSH channel handoff. MoteBus remains the continuous CX control plane.
Standard OpenSSH owns actual command execution, authentication, host-key
verification, encryption, and SSH session semantics. MoteSSH never transports
or stores an SSH private key and replaces neither MoteBus nor SSH.

```bash
sudo sh /tmp/cx-install.sh doctor
sudo sh /tmp/cx-install.sh upgrade
sudo sh /tmp/cx-install.sh uninstall
```

`doctor` verifies packages, commands, topology/config shape, OpenSSH syntax,
and service health. This is local package health, not node admission: approved
SSH trust and CX Hub enrollment must independently reach `ACTIVE`, otherwise
remote execution is `BLOCKED`. `upgrade` reuses the same signed APT path and preserves
admission state. `uninstall` removes only `cx-node`; shared MoteSSH/OpenSSH,
signed APT trust, node configuration, and locked topology are retained for
audit and safe reinstall.
