# MEdge Binary Packages

This public repository contains reviewed Debian release metadata, the public
APT key, installer source, and GitHub Pages automation. Private implementation
source, private topology, Debian source packages, and private build-system
addresses are not published here.

## Publication status

The immutable public release `deb-v2026.08.26-6` is the current complete
MEdge installer bundle. It contains the reviewed component packages directly;
there is no `medge-core.deb` or `medge-all.deb`.

Historical releases and the current Pages index are immutable migration
evidence. They are not the active package architecture and must not be used to
restore retired packages or transports.

## Canonical catalog

The exact active Debian catalog is:

```text
sphere + moted + medge + mlink + mdesk + ss-webos + mote-proxy + motemcp
```

- `sphere` provides native local MoteBus and DC.
- `medge` contains the MEdge manager and assembled EdgeOS, APort, Qbix, and
  daemonless QFunc modules.
- `moted` owns MoteData, profiles, registration, resolution, typed sessions,
  and the common `mote` CLI.
- `mlink` owns all physical and local I/O, including NFC and QR devices.
- `mdesk` is the sole Linux desktop-integration package and owns
  `mdesk://mms`; it consumes MLink I/O and does not own device drivers.
- `ss-webos` is the independent SmartScreen/WebOS browser runtime.
- `mote-proxy` is the independent SSH proxy boundary.
- `motemcp` is the optional on-demand MCP provider through MoteD.

`desk`, `mote-desk`, `ultra-desk`, and the proposed `ss-desk` package are
retired without aliases. `ss-webos` remains active and separate from MDesk.

There is no `medge-core` or `medge-all` Debian package. Complete composition is
owned by `medge-install.sh`, which installs the reviewed component DEBs
directly. `vdevice` remains a separate optional package. MLink is included in
the complete bundle and in every MDesk installation.

## Required installers

A compliant release publishes exactly these self-contained installers:

```text
medge-install.sh      -> complete reviewed component bundle
mdesk-install.sh      -> sphere + moted + mlink + mdesk
ss-webos-install.sh   -> ss-webos only
mote-proxy-install.sh -> sphere + mote-proxy
motemcp-install.sh    -> sphere + moted + motemcp
```

`medge-install.sh` and `mdesk-install.sh` download their exact immutable GitHub
release assets directly. The shared `install.sh` remains the internal component
dispatcher for the narrower APT-backed entry points and fails closed without an
explicit profile. No installer removes `desk` or `ss-desk` without a separately
approved migration and rollback plan.

The immutable public release `deb-v2026.08.26-6` contains the current reviewed
`medge_1.1.0-3_all.deb`, `moted_3.2.0-6_amd64.deb`,
`mlink_0.1.0-2_amd64.deb`, and `mdesk_3.0.0-2_amd64.deb` built by the canonical
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
The MEdge artifact comes from main commit
`6286cb8c7ac9d5ef064a2c837c3c1e29632a447d` with SHA-256
`332f927952bcb1bc68ee3ce6ee860c347d2000d26dbc8fc30963c68bf1bb964f`.

Install the exact reviewed MDesk package set directly from that immutable
release. A newer installed package is never downgraded:

```bash
curl -fsSLo /tmp/mdesk-install.sh \
  https://raw.githubusercontent.com/motebus/medge-release/main/mdesk-install.sh
sudo bash /tmp/mdesk-install.sh
```

Install the complete reviewed MEdge component bundle, including the MEdge
runtime, MDesk, and SS-WebOS. CX Node is an independent runtime and is not
part of the public MEdge installer. There is no `medge-core.deb` or
`medge-all.deb`; the script installs the component DEBs directly:

```bash
curl -fsSLo /tmp/medge-install.sh \
  https://raw.githubusercontent.com/motebus/medge-release/main/medge-install.sh
sudo bash /tmp/medge-install.sh
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
