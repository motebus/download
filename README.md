# MEdge Binary Packages

This public repository distributes install-only MEdge Debian packages for
supported amd64 hosts. It contains public release metadata, the APT signing
key, install scripts, and GitHub Pages automation. Private implementation
source, Debian source packages, private topology, and private build-system
addresses are not published here.

The current coordinated release contains exactly seven packages:

- headless MEdge: `sphere`, `moted`, `aport`, `qbix`, and `mbox`;
- WebOS desktop: `desk` and `ss-webos`.

## Install MEdge

Install the headless profile on Ubuntu 24.04 or 26.04 amd64:

```bash
curl -fsSLo /tmp/medge-install.sh \
  https://motebus.github.io/medge-release/medge-install.sh &&
sudo sh /tmp/medge-install.sh
```

To inspect the installer first:

```bash
curl -fsSL https://motebus.github.io/medge-release/medge-install.sh
```

The installer validates the host, verifies the archive key fingerprint,
configures the signed APT source, installs the five headless packages in one
transaction, and verifies their system services:

```text
AECA A1DC DAF1 9C7B 7FEA  F0C0 82A0 E180 EDAE A7A0
```

The public repository uses:

```text
suite:        stable
component:    main
architecture: amd64
```

It does not use `apt-key`, `trusted=yes`, or direct package URLs. Publication
rejects private GitLab URLs in the public tree, manifest, APT metadata, Debian
control metadata, and installed package content. The installer also rejects
an APT transaction plan containing a GitLab URL.

The installer does not create or modify locked MoteChat topology. Before an
upgrade it stops existing MEdge units in reverse dependency order; afterward
it enables, starts, and verifies each current unit in dependency order. It
requires services to remain active without increasing their restart count
during a stability window and prints focused systemd evidence on failure.

## Install WebOS desktop components

The release also publishes `webos-install.sh`, which installs the coordinated
`desk` and `ss-webos` packages from the same signed APT release. Desk handles
admitted local device input and SS-WebOS provides the user-facing runtime.

## Retired transports

SSH, RDP, PTY, and raw-byte forwarding are not MoteD capabilities. The former
`motestream`, `motessh`, `moterdp`, and `mote-proxy` package paths are retired
and excluded from the active package index. Ordinary host administration SSH
remains an operating-system service outside MoteD and MoteBus.

CX Node is also outside this MEdge public package set. It is not installed or
published by these installers.

## Releases

Current approved stable release: `medge-v5.0.0-1`.

Each approved release contains:

- the seven coordinated binary Debian packages;
- `release-manifest.json` with package hashes and source provenance;
- `SHA256SUMS`;
- `medge-install.sh` and `webos-install.sh`.

Existing release tags and assets are immutable. Historical bundles remain
lineage only and do not contribute packages to the active APT index.

Every stable publication requires explicit repository-owner approval. The
release workflow validates the exact package set and manifest before rebuilding
the signed GitHub Pages APT repository.

## GitHub account setup

An owner can create or verify this public install repository and push a clean
`main` branch with:

```bash
./github-setup.sh
```

The setup script asks interactively for the GitHub owner, repository name,
and token. Token input is hidden and is not stored in repository files, the
remote URL, Git configuration, or a persistent credential helper. The script
refuses a dirty worktree or a branch other than `main`, never force-pushes,
and does not create a release tag or publish the stable APT repository.
