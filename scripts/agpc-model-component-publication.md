# Signed Core composition, Consumer and Model Provider artifact previews

`publish-agpc-model-components.yml` publishes three independently reviewed component
previews using the established archive signing key. The scope is a source-bound
DEB download. These assets do not admit an installer cohort, native installation,
ABI support, live inference, or AGPC Ready. Existing Core/Full installers and APT
selection are separate releases.

| Component input | Delivery product | Binary package/version | Original producer |
| --- | --- | --- | --- |
| `core` | `agpc-core` | `agpc-core`, `0.1.0~core.20261106.1` | Project 1336, `agpc-core-package` |
| `vmodel` | `agpc-core` | `agpc-vmodel`, `0.1.0~vmodel.20261106.1` | Project 1336, `vmodel-package-native` |
| `model` | `agpc-model` | `model-llm`, `0.1.0-5~agpcmodel20261106.1` | Project 1363, `provider-native` |

The reviewed public tags are `agpc-core-v0.1.0-core.20261106.1`,
`agpc-vmodel-v0.1.0-vmodel.20261106.1` and
`agpc-model-v0.1.0-5-agpcmodel20261106.1`. Tags are public labels; the DEB versions,
package identities, installed paths and source ownership retain their original
values. A new version, source project or producer requires a source review.

## Original evidence and asset contract

Each publication record is an actual generated
`scripts/component-publications/{core,vmodel,model}.json` document with schema
`agpc.component-publication/v1`. It binds the exact source commit, successful
original main pipeline/job, original ZIP byte count/SHA256, producer manifest
byte count/SHA256, source inventory digest and all three unsigned public assets.
No empty, template or local-build record is a publication input.

The Core ZIP must contain its original DEB and `CORE-PACKAGE-MANIFEST.json`
under `packaging/core/dist/`. Its exact tracked source closure and six package
checks must match the successful original `agpc-core-package` main job. The DEB
contains only the three reviewed metadata files, no runtime or lifecycle hooks.
Its dependency cohort and embedded source provenance retain false admission
claims; the signed preview does not activate the Mesh/All installer cohort.

The Consumer ZIP must contain its DEB, `PUBLICATION-MANIFEST.json`,
`BUILD-RECEIPT.json` and `PACKAGE-PLAN.json` under `packaging/vmodel/dist/`.
The original compiled `vmodel-native` job is independently verified at its own
successful main revision. The current packaging main may differ only outside
the exact `native/vmodel/` source inventory. Both inventories and their tracked
blobs are verified at their actual commits. The DEB executable must equal the
original compiled artifact. Build and package-plan pins are checked against
their original ZIP bytes.

The Provider ZIP must contain its DEB and `PROVIDER-MANIFEST.json` under `dist/`.
Its 23 producer checks must succeed, including a native unprivileged build,
contracts, management, shlibs, package readback and the three offline probes.
The package's internal provenance must match the source, producer and composition
in that original manifest. A local package cannot be relabelled as CI output.

For each component, the public unsigned bundle contains exactly:

- The original amd64 DEB bytes under the reviewed GitHub asset filename.
  GitHub normalizes `~` to `.`, so the manifest distinguishes the original CI
  filename from the public filename; the Debian Version and bytes are unchanged.
- `MANIFEST.json`, schema `agpc.component-artifact-preview/v1`, with source and
  producer identifiers, original evidence hashes and false producer admission.
- `SHA256SUMS`, covering that DEB and manifest.

Publication adds `MANIFEST.json.asc` and `SHA256SUMS.asc`, signed by archive key
`AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0`. The existing `sign_files` implementation
also verifies both detached signatures. Original source archives, CI logs,
credentials and local test fixtures are not public assets.

## Preparation, source review and publication

1. Obtain the actual successful original main job/pipeline API receipts and ZIP.
   Verify them against the current protected source main. For the Consumer,
   retain the separately pinned successful original compiled main evidence.
2. Run `publish_agpc_model_components.py prepare` with component, `--archive`,
   `--pipeline`, `--job`, `--record-output` and `--bundle-output`. It writes new
   local review outputs only. Inspect the actual generated record and bundle;
   preparation does not grant runtime or installation admission.
3. Review the record and publisher changes in canonical project 1341. Run its
   source checks. Export only the established public allowlist using
   `export_agpc_public_source.py` from a clean committed revision, then apply
   the selected changed public files to the current `motebus/download` main
   through its normal reviewed PR. Preserve independent public changes.
4. Stage the three exact unsigned bundle files under `candidate-` plus the
   reviewed final tag using the existing draft-candidate release lifecycle.
   Candidate storage alone does not satisfy any publication gate.
5. Dispatch the existing `release` environment workflow on the current public
   main with only `component=core`, `component=vmodel` or `component=model`. The workflow requires
   the committed record, re-downloads original CI artifacts and tracked source,
   compares staged bytes, signs in an isolated keyring, then repeats producer,
   source-main, publisher-main and absent-final-tag checks before creating a
   prerelease with `latest=false`.
6. Read back the final release's five assets and verify byte counts, hashes and
   both signatures. Report the exact artifact-preview scope and evidence.

The workflow refuses stale/unprotected source main, branch-only or optional
producer jobs, failed checks, altered source/archive/package bytes, contradictory
admission claims and existing final tags. Missing original CI evidence must be
completed by the source producer; a draft release is not a substitute.
