# Install Sphere Debian Distribution

This public repository is the reviewed GitHub release and signed APT boundary
for the Sphere/Mote Transport Debian aggregate. Private implementation source,
GitLab addresses, credentials, topology, source packages, and loose env files
are forbidden here.

## Current v9 package set

An approved `medge-public-release/v9` bundle contains these independent Debian
packages in dependency-safe audit order:

```text
sphere
moted
medge
mlink
mdesk
ss-webos
mote-proxy
motemcp
cx-pivot
mote-sync
mote-syncd
```

The first eight entries are the active Sphere runtime catalog. CX Pivot keeps
its independent CX ownership. `mote-sync` and `mote-syncd` are the client and
endpoint packages used by the Sync-service acceptance row. WebOS Server, SS
Server, Redixs, and every other OCI-only service are excluded; `ss-webos` is
the independent Debian client runtime and remains included.

`medge` and `cx-pivot` are independent package boundaries. Their publication
and installation do not depend on or query UltraMap. Historical `cx-node`
release evidence does not create an UltraMap relationship.

There is no aggregate `sphere`, `medge-core`, or `medge-all` meta-package.
`vdevice` remains optional and separate.

## Clean break

`install-sphere.sh` is the only current aggregate entry. The former
`install-medge-all.sh` compatibility wrapper and its `medge-install.sh` target
are retired without aliases. Existing tags and release assets remain immutable
historical evidence; they are not copied into the new Pages site.

The source tree still retains separately scoped component and historical Mote
Transport installer sources where they are not aliases for the retired
aggregate. A v9 release bundle and the generated Pages site admit only
`install-sphere.sh` as their installation entry.

## Trust chain

The protected private owner creates a v9 bundle from exact GitLab `main` or an
explicitly approved immutable rollback tag. This repository then:

1. validates the exact eleven-package manifest, assets, SHA-256 checksums, env
   provenance, and the single executable installer;
2. installs the bundle in pinned Ubuntu 24.04 and 26.04 amd64 containers;
3. constructs the APT index from only that approved bundle;
4. signs `Release`, `InRelease`, and `release-manifest.json.asc` with the
   protected archive key; and
5. publishes the resulting site through GitHub Pages.

The installer pins archive fingerprint
`AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0`, verifies the manifest detached
signature, accepts only the exact Pages `.sources` definition, proves every
manifest version is present in the signed APT source, performs one APT
transaction, and verifies installed versions. It rejects any GitLab URL in the
resolved package plan.

After an approved v9 release has completed the Pages workflow, install with:

```bash
curl -fsSLo /tmp/install-sphere.sh \
  https://motebus.github.io/medge-release/install-sphere.sh
curl -fsSLo /tmp/release-manifest.json \
  https://motebus.github.io/medge-release/release-manifest.json
curl -fsSLo /tmp/release-manifest.json.asc \
  https://motebus.github.io/medge-release/release-manifest.json.asc
sudo bash /tmp/install-sphere.sh
```

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
