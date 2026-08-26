# MEdge Binary Packages

This public repository contains reviewed Debian release metadata, the public
APT key, installer source, and GitHub Pages automation. Private implementation
source, private topology, Debian source packages, and private build-system
addresses are not published here.

## Publication status

No current coordinated MEdge release is deployed. `medge-v5.0.0-1` is retained
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
sphere + moted + medge + mdesk + ss-webos + mote-proxy + motemcp
```

- `sphere` provides native local MoteBus and DC.
- `medge` contains the MEdge manager and assembled EdgeOS, APort, Qbix, and
  daemonless QFunc modules.
- `moted` owns MoteData, profiles, registration, resolution, typed sessions,
  and the common `mote` CLI.
- `mdesk` is the sole Linux desktop-integration package and owns
  `mdesk://mms`.
- `ss-webos` is the independent SmartScreen/WebOS browser runtime.
- `mote-proxy` is the independent SSH proxy boundary.
- `motemcp` is the optional on-demand MCP provider through MoteD.

`desk`, `mote-desk`, `ultra-desk`, and the proposed `ss-desk` package are
retired without aliases. `ss-webos` remains active and separate from MDesk.

Two dependency-only meta-packages are also defined: `medge-core` installs
`medge + moted + mote-proxy + motemcp`; `medge-all` adds `mdesk + ss-webos +
cx-node`. `vdevice` and `mlink` remain separate optional packages.

## Required installers

A compliant release publishes exactly these self-contained installers:

```text
medge-install.sh      -> sphere + moted + medge
mdesk-install.sh      -> sphere + moted + mdesk
ss-webos-install.sh   -> ss-webos only
mote-proxy-install.sh -> sphere + mote-proxy
motemcp-install.sh    -> sphere + moted + motemcp
```

The shared `install.sh` is an internal component dispatcher used by those
named entry points; running it without an explicit profile fails closed. No
installer removes `desk` or `ss-desk` without a separately approved migration
and rollback plan.

The immutable public release `deb-v2026.08.25-2` already contains the reviewed
`mdesk_3.0.0-1_amd64.deb` built from canonical `mdesk-deb` main commit
`3bf4455c2f6b60729d2bc40f0e28b934312e0d14` with SHA-256
`6228537734a19026eed5dde0435c2d913392aedb01d188980393b46fbbc436ae`.

## Release requirements

Every stable publication requires explicit repository-owner approval and:

- exact Git `main` source provenance and environment-input hashes;
- binary/package-content disclosure audit;
- immutable `SHA256SUMS` and `release-manifest.json`;
- dependency installation tests on Ubuntu 24.04 and 26.04 amd64;
- successful signed APT construction and GitHub Pages deployment.

Existing release tags and assets remain immutable. A failed candidate receives
a new revision rather than changing an existing tag or asset.
