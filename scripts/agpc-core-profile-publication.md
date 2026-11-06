# Core package and Mesh/All installer publication

The Core product is the real Debian package `agpc-core`. Its Core installer
entry is `agpc-mesh.sh`; `agpc-all.sh` adds the application profile. The separate
runtime package remains `agpc-mesh`. Original CI keeps `agpc-core_0.1.0~core.20261106.1_amd64.deb`. GitHub normalizes
`~`, so the exact public filename is
`agpc-core_0.1.0.core.20261106.1_amd64.deb`; vModel likewise uses
`agpc-vmodel_0.1.0.vmodel.20261106.1_amd64.deb`. The original Debian Versions
and all DEB bytes remain unchanged. This explicit mapping is limited to those
two v13 packages. No stable `agpc-core.deb` URL is created by this change.

This source change prepares the producer and validators. The canonical producer baseline is the frozen v96/cohort85 fixture. The public
repository retains its existing v2/v46 root installers until a separate activation
change is approved from a new original main producer artifact. No placeholder input or future source commit is
committed. Existing signed assets and historical job records are immutable.

## Exact package contract

Overlay schema `agent-computer-apt-overlay/v13` adds exactly `agpc-core` and
`agpc-vmodel`. It preserves cohort85 except for the reviewed Manager `4.4.0-3`,
View `0.1.0-4` and Mesh `3.0.0-6` replacements. Core
`0.1.0~core.20261106.1` and vModel `0.1.0~vmodel.20261106.1` are the only new
candidate-version exceptions; all other package version rules remain intact.
The existing `model-llm` package is not replaced by the separate Model Provider
preview.

Core contains exactly three metadata files, no runtime, hooks, triggers or
conffiles. It depends on agent-sphere `0.3.0-43`, Manager `4.4.0-3`, View
`0.1.0-4`, Mesh `3.0.0-6`, RUN `0.2.0-4`, contextd `0.1.0-27`, iAgent
`1.0.0-1` and vModel `0.1.0~vmodel.20261106.1` at exact versions. CDP alone has
`>= 0.2.0-2`: the fresh signed cohort still pins `0.2.0-2`, while the existing
installer can retain an approved newer owner version without downgrading it.
The dependency graph permits only this metadata-only composition to depend on
Manager and View; existing runtime backedge and cycle prohibitions are unchanged.
Embedded Core build flags remain false. They cannot self-certify lifecycle,
release admission or runtime readiness.

## Original input and build

After verifying the successful original protected-main source/pipeline/job and
public component release of each of Manager, View, Mesh, Core and vModel, commit
`scripts/agpc-core-profile-release-input.json`. Its exact fields are:

- `schema`: `agpc-core-profile-input/v1`.
- `installer_tag` and `aggregate_tag`: new immutable installer and cohort tags.
- `baseline_source_commit`: the exact source containing the unchanged v96 and
  cohort85 bytes; `baseline_files` pins every path in the producer's
  `BASELINE_FILES` inventory by SHA-256.
- `components`: ordered Manager, View, Mesh, Core, vModel records, each with
  `package`, `source_tag` and positive original `main_job_id`. `package` is the
  exact overlay package record, including original successful main provenance.

`agpc-core-profile-release-artifacts` runs only on protected main when this
committed input exists and changes. `build_agpc_core_profiles.py` checks the clean
exact CI commit, reads the baseline from its immutable Git tree, fetches only
those pinned public component assets, checks their bytes/control/public content,
and reads back the closed Core payload. It derives removal hook and unit pins
from the actual DEBs and preserves previous policies as historical alternatives.
It produces unsigned `agpc-core-profiles/` containing:

- `agpc-mesh.sh`, `agpc.sh`, `agpc-all.sh`, `agpc-apps.sh`, and `uninstall.sh`.
- The four matching `*.source.json` receipts, all schema
  `agpc-installer-source/v4`, one actual producer commit and one new tag. Mesh and
  standard have identical bytes and both keep profile identity `standard`.
- `agent-computer-apt-overlay.json`, `release-manifest.json`,
  `aggregate-component-release.json`, and `SHA256SUMS`.

The Core profile remains named `core` in native acceptance. This is a download
entry rename, not a new profile or runtime identity. Both fresh installs and
upgrades explicitly select `medge=3.3.0-2` once, alongside the Core composition.

Renderer tests use the immutable public inputs in
`tests/fixtures/agpc-core-v96-baseline`, including original file modes and a hash
inventory. Advancing the current root installers must not replace that fixture
or relax the producer's v96/cohort85 baseline guard.

## Publication and activation

The existing component release process publishes the exact reviewed DEBs first.
The existing aggregate process copies their unchanged bytes into the new
cohort. The installer publisher must verify the original main job ZIP, tracked
input, release manifest and every source/asset hash before creating the new
versioned installer release. The new producer does not dispatch, sign, create
releases, activate Pages, or invent native acceptance.

The reviewed release sequence uses intermediate component tag
`agent-computer-v0.3.0-86` for the unchanged baseline plus the original
Manager/Mesh/View replacements; it does not activate Pages. After the separate
Core and vModel originals are published, the new producer binds aggregate
`agent-computer-v0.3.0-87` and installer `v0.3.0-97`. Confirm both tags are still
unused immediately before publication.

`publish_agpc_core_profiles.py prepare` takes the exact original job ZIP,
successful job and pipeline JSON, committed producer input, and a source checkout
containing the baseline commit. It emits the real
`scripts/agpc-core-profile-publication.json` for review. The publication workflow
rechecks protected current main, original successful job, input, baseline blobs,
ZIP and every output byte, then publishes the aggregate and installer separately.
It uses the existing release environment; Pages signing and native acceptance
still follow.

The producer and publication record share canonical source project 1341. Keep
canonical main at the original producer commit while its actual record is
reviewed and merged in the public repository. A canonical activation branch may
hold that record for review, but merging it before publication would advance
main and correctly fail the current-source guard. Publish both exact releases
first; then merge the canonical activation assets, record and workflow source
pin. Do not weaken freshness checks to change this ordering.

Activate all four receipts together with the new overlay and uninstaller from
that original bundle. Retain its exact `release-manifest.json` bytes at
`scripts/agpc-core-profile-release-manifest.json` alongside the committed input;
activation tests bind every current script and receipt back to that original
manifest. Remove only the current `agpc-core.sh`,
`agpc-core.source.json` and their detached signatures; preserve versioned releases
and all existing pool artifacts. Update the current README example to
`agpc-mesh.sh` in the same activation. The native site renderer selects Mesh links
and the versioned Core DEB from the v4/v13 records; historical v3 rendering stays
unchanged.

The signed Pages flow still verifies detached signatures and exact asset equality,
then runs all six native VM profiles: standard, core, full, apps, upgrade and
upgrade-home. Core/Full install and reinstall must observe the real Core,
vModel and iAgent versions. APT simulation must include those dependencies and
Manager/medge; a renamed launcher alone cannot satisfy admission. Native checks,
including owner CDP retention, must succeed before Pages deployment. Source
checks, building an unsigned bundle, or publishing a preview do not assert
complete AGPC readiness.
