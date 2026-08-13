# MEdge Binary Packages

This public repository distributes install-only MEdge Debian packages for
Ubuntu 24.04 and 26.04 amd64.

It contains distribution documentation, the public APT key, release
manifests, and GitHub Pages automation. Component source code and Debian
source packages are intentionally absent. Public install artifacts contain no
private build-system URL.

## Install

Install MEdge on Ubuntu 24.04 or 26.04 amd64 with one command:

```bash
curl -fsSLo /tmp/medge-install.sh \
  https://motebus.github.io/medge-deb/medge-install.sh &&
sudo sh /tmp/medge-install.sh
```

The public installer checks the operating system and architecture, verifies
the downloaded archive key against this fingerprint, configures the signed
APT source, installs the six physical server packages in one transaction,
starts the MEdge system services,
and verifies that they are active:

```text
AECA A1DC DAF1 9C7B 7FEA  F0C0 82A0 E180 EDAE A7A0
```

To inspect it before installation:

```bash
curl -fsSL https://motebus.github.io/medge-deb/medge-install.sh
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

Current approved stable release: `medge-v4.0.0-4`.

Each approved GitHub Release contains:

- eight component binary DEBs;
- `release-manifest.json`;
- `SHA256SUMS`;
- `medge-install.sh` and `webos-install.sh`;
- optional binary `.changes` and `.buildinfo` provenance.

`medge.deb` is retired. `medge-install.sh` directly installs the headless
`sphered`, `moted`, `aport`, `qbix`, `mbox`, and `motessh` set. `webos-install.sh`
installs `desk + ss-webos`. MBox includes
the former MGate/UCLI roles and Qbix includes QFunc runtimes.

Every stable publication requires explicit owner approval. Existing release
tags and assets are immutable.

Historical bundles remain immutable lineage only. They never contribute
packages to the active APT index, which contains only the approved current
eight-package release.
