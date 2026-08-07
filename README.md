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
  https://motebus.github.io/medge-deb/install.sh &&
sudo sh /tmp/medge-install.sh
```

The public installer checks the operating system and architecture, verifies
the downloaded archive key against this fingerprint, configures the signed
APT source, runs `apt-get install medge`, starts the MEdge system services,
and verifies that they are active:

```text
AECA A1DC DAF1 9C7B 7FEA  F0C0 82A0 E180 EDAE A7A0
```

To inspect it before installation:

```bash
curl -fsSL https://motebus.github.io/medge-deb/install.sh
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
Before the package transaction, it stops and disables existing MEdge system
units in reverse dependency order. It then enables, starts, and verifies each
unit individually in dependency order. It then requires every system service
to remain active without increasing its systemd restart count during a
30-second stability window; a transient `active` state inside a restart loop
does not pass installation.
When exactly one local graphical session is active, it also reloads and
starts the Desk and SS-WebOS user-session helpers. On a headless install,
those helpers remain enabled and start at graphical login. If a system service
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

Each approved GitHub Release contains:

- nine component binary DEBs;
- one dependency-only `medge` meta-package DEB;
- `release-manifest.json`;
- `SHA256SUMS`;
- optional binary `.changes` and `.buildinfo` provenance.

The `medge` package installs the exact coordinated versions of `sphered`,
`mgate`, `ss-webos`, `moted`, `agos`, `qbix`, `qbix-func`, `mote`, and `desk`.

Every stable publication requires explicit owner approval. Existing release
tags and assets are immutable.

The publisher may validate the exact v3.1.0-8 eight-package bundle only as
immutable previous-release lineage. It never copies that historical package
set into the active APT index; the current index contains only the approved
nine-package release.
