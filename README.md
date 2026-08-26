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
medge-install.sh      -> medge-all (complete reviewed bundle)
mdesk-install.sh      -> sphere + moted + mdesk
ss-webos-install.sh   -> ss-webos only
mote-proxy-install.sh -> sphere + mote-proxy
motemcp-install.sh    -> sphere + moted + motemcp
```

`medge-install.sh` and `mdesk-install.sh` download their exact immutable GitHub
release assets directly. The shared `install.sh` remains the internal component
dispatcher for the narrower APT-backed entry points and fails closed without an
explicit profile. No installer removes `desk` or `ss-desk` without a separately
approved migration and rollback plan.

The immutable public release `deb-v2026.08.26-3` contains the current reviewed
`moted_3.2.0-6_amd64.deb` and `mdesk_3.0.0-2_amd64.deb` built by the canonical
`main` pipelines. MoteD is the failure-isolated MEdge kernel/control plane;
MDesk and other optional leaf modules cannot propagate stop, restart, or
failure into it. MoteD requests an exact 300-second MoteC lease, refreshes it
every 90 seconds after success, and retries transport failures after 30 seconds
without overlapping registration requests. The MDesk package binds to
canonical `sphere.service`.

The MoteD artifact comes from commit
`643d651ad4343d56dddab568f287250ef26054eb` with SHA-256
`3cd1d0457c91fe038649fb7d861bcdc2a41e92b723b4a189b8d2a16487d05790`.
The MDesk artifact comes from commit
`e36bb2ed70dd40925497b40e395e9c01ce7fe74d` with SHA-256
`af4bf7493c962ba29c19712e9c12e4df3c08315a5464b53f74949906799942d4`.

Install the exact reviewed MDesk package set directly from that immutable
release. A newer installed package is never downgraded:

```bash
curl -fsSLo /tmp/mdesk-install.sh \
  https://raw.githubusercontent.com/motebus/medge-release/main/mdesk-install.sh
sudo sh /tmp/mdesk-install.sh
```

Install the complete reviewed MEdge bundle, including MEdge Core, MDesk,
SS-WebOS, and CX Node:

```bash
curl -fsSLo /tmp/medge-install.sh \
  https://raw.githubusercontent.com/motebus/medge-release/main/medge-install.sh
sudo sh /tmp/medge-install.sh
```

## Release requirements

Every stable publication requires explicit repository-owner approval and:

- exact Git `main` source provenance and environment-input hashes;
- binary/package-content disclosure audit;
- immutable `SHA256SUMS` and `release-manifest.json`;
- dependency installation tests on Ubuntu 24.04 and 26.04 amd64;
- successful signed APT construction and GitHub Pages deployment.

Existing release tags and assets remain immutable. A failed candidate receives
a new revision rather than changing an existing tag or asset.
