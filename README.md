# MEdge Binary Packages

This public repository contains reviewed Debian release metadata, the public
APT key, installer source, and GitHub Pages automation. Private implementation
source, private topology, Debian source packages, and private build-system
addresses are not published here.

## Publication status

No AgentSpec-v5 release is currently deployed. `medge-v5.0.0-1` is retained
as a prerelease compatibility-failure record; its failed workflow did not
change the live APT repository. A corrected release remains withheld until
every canonical package passes source, disclosure, bundle, and Ubuntu 24.04 /
26.04 compatibility gates.

Historical releases and the current Pages index are immutable migration
evidence. They are not the active package architecture and must not be used to
restore retired packages or transports.

## Canonical catalog

The exact active Debian catalog is:

```text
sphere + medge + moted + ss-desk + motemcp
```

- `sphere` provides native local MoteBus and DC.
- `medge` contains the MEdge manager and assembled EdgeOS, APort, Qbix, and
  daemonless QFunc modules.
- `moted` owns MoteData, profiles, registration, resolution, typed sessions,
  and the common `mote` CLI.
- `ss-desk` is the unified SmartScreen WebOS and Linux desktop runtime.
- `motemcp` is the optional on-demand MCP provider through MoteD.

The former independent `sphered`, `mbox`, `aport`, `qbix`, `qbix-func`,
`motestream`, `motessh`, `moterdp`, `mote-proxy`, `desk`, `ss-webos`, and
`cx-node` paths are excluded from a current MEdge release. SSH, RDP, PTY, and
raw-byte forwarding are not MoteD capabilities. Ordinary host administration
SSH remains outside MoteD and MoteBus.

## Required installers

A compliant release publishes exactly these self-contained installers:

```text
medge-install.sh    -> sphere + moted + medge
ss-desk-install.sh  -> sphere + moted + ss-desk
motemcp-install.sh  -> sphere + moted + motemcp
```

There is no approved generic `install.sh`, `webos-install.sh`, CX installer,
or MEdge-All installer. Do not treat files retained in repository history or
an older Pages deployment as current installation authority.

## Release requirements

Every stable publication requires explicit repository-owner approval and:

- exact Git `main` source provenance and environment-input hashes;
- binary/package-content disclosure audit;
- immutable `SHA256SUMS` and `release-manifest.json`;
- dependency installation tests on Ubuntu 24.04 and 26.04 amd64;
- successful signed APT construction and GitHub Pages deployment.

Existing release tags and assets remain immutable. A failed candidate receives
a new revision rather than changing an existing tag or asset.
