# AGPC Voice publication review

This route extends the existing signed Pages publisher without changing its
permissions, archive key, release environment, or `medge-apt-pages` concurrency
lock. It restores the last successful main Pages artifact, preserves unrelated
files and publishes an immutable version directory plus the latest script and
source-record aliases. It never installs packages, activates services, executes
the embedded installer or contacts telephone/runtime endpoints.

The active production input `scripts/agpc-voice-publication.json` remains the
reviewed v1 `.2` publication. This revision-contract change does not replace that
input or dispatch the workflow. A later input must bind the genuine new reviewed
main build and original ZIP; future CI identities must not be invented.

The committed input record uses schema `agpc.voice-publication-inputs/v1` and
requires `version`, `source_commit` (40 hexadecimal characters), positive
`ci_job`, the exact GitLab artifact ZIP `archive_sha256` and `archive_bytes`, and
`install_review` (project1341 MR number) / `disclosure_review`
(`project`1341 or1348 and positive `iid`). No private source URL is disclosed. The install review must
be approved, merged into project1341 main, and bind the exact build commit.
At least one approver must have current Maintainer/Owner membership. Repository
write access or an ordinary Developer approval cannot substitute for that role.
Disclosure review must similarly bind that commit or the component main commit.
Input records cannot select a different host, repository, download URL or key.
Public records contain project/commit/CI/MR identities, not private host URLs.
The existing public-tree and expanded-runtime URL disclosure checks remain in force.

The project1341 successful main CI artifact contains exactly:

```text
agpc-voice-bundle/agpc-voice.sh
agpc-voice-bundle/BUILD-RECEIPT.json
agpc-voice-bundle/SHA256SUMS
agpc-voice-bundle/SOURCE-RELEASE.json
agpc-voice-bundle/packages/agpc-voice_<version>_all.deb
agpc-voice-bundle/packages/agpc-freeswitch-core_<version>_amd64.deb
```

The packaging helper must emit release-staging with admitted exact committed
runtime, verified installer/package binding and complete `package_pins`. The
publisher inspects the compressed runtime without execution, independently
requires its literal source install gate to be True, and verifies all source
hashes, package metadata and checksums. It never changes that gate.
Native runtime readiness is not a publishing prerequisite; the source record
explicitly keeps `runtime_ready=false`.

`SOURCE-RELEASE.json` has only schema `agpc.voice-component-main-ci/v1`,
`voice_commit`, `voice_ci_job`, and `voice_review` (project1348 MR number). The component job and pipeline
must be successful project1348 main builds for that exact commit; the DEB at
`components/agpc-voice/dist/<package_filename>` must also match the staged bytes; the review
must be approved and merged at that commit. Local candidate builds do not
satisfy this contract.

The original source CI job must add this component record after the reviewed
bundle build. `SHA256SUMS` remains the builder's complete four-file inventory
(script, build receipt and both packages); the input ZIP hash also covers the
additional source record. Neither a private Git tree/history nor extra files
are accepted in the ZIP. The exact public artifact disclosure review remains
required and cannot be replaced by a clean credential scan.

The source owner must pin package URLs to:

```text
https://motebus.github.io/download/agpc-voice/<voice-version>/packages/<package_filename>
```

The route refuses a version lower than the current public Voice record and
refuses changes to an existing version directory. It reuses and verifies
existing version signatures. Rollback publication is a separately reviewed
action; this workflow has no override for its downgrade check. Package rollback
belongs to the source-owned installer receipt and predecessor contract.

The existing protected `AGPC_GITLAB_SOURCE_URL` supplies the source authority;
its origin and exact installer repository path are checked. Only the existing
`AGPC_GITLAB_READ_TOKEN` is used for same-origin read-only job,
pipeline, review and artifact API requests. Its current protected-environment
API capability is not proven by local `glab` access. If this existing credential
cannot read those records, stop; do not create credentials or broaden grants.
The original publisher owner must supply an already permitted artifact route.
Authenticated cross-host redirects fail closed rather than forwarding the token.

Source validation discovers `tests/test_agpc_voice_publication.py` through the
existing public-source CI suite. The release workflow contains no runtime tests,
Ops probes or new readiness stage. Fixture signatures are test evidence only.

## Independent immutable installer revision

Existing v1 input, receipt and public-source records retain their shape and
version-directory behavior. V1 explicitly forbids an `installer_revision` field.
A correction that retains an already published component uses:

- `agpc.voice-publication-inputs/v2` in the reviewed publisher input.
- `agpc.voice-standalone-build/v2` in the original source-main build receipt.
- The same integer `installer_revision` from1 through999999 in both.
- `agpc.voice-install-source/v2` plus that revision in the signed public record.

The source-selected packaging input is also v2 and the builder binds its
revision into the receipt before the checksum inventory/ZIP is created. V2
rejects omitted, boolean, null, fractional, string, out-of-range and traversal
values. Explicit schemas ensure an older v1 publisher refuses the new contract
instead of ignoring the revision. `SOURCE-RELEASE.json` retains its component
v1 schema and original component-main MR/job/DEB identities.

The exact proposed correction is component `0.1.0~office117.20261015.2`,
installer revision1:

```text
agpc-voice/0.1.0~office117.20261015.2/installers/1/agpc-voice.sh
agpc-voice/0.1.0~office117.20261015.2/installers/1/agpc-voice.source.json
agpc-voice/0.1.0~office117.20261015.2/installers/1/BUILD-RECEIPT.json
```

Each has its own detached `.asc` signature. Original `.2` script/source/receipt
and both `.2/packages/*.deb` URLs remain byte-identical, including signatures;
no DEB is copied into the new installer directory. Before staging any revision,
verify both latest aliases against their immutable signed records, then verify
the original signed base script, source record, receipt and both DEBs. The
base component identity/package inventory, receipt/source/script hashes and
package hashes must match the unchanged component proof from the new original
main-CI bundle. Missing or mismatched base content/signatures fail before writes.

Only the three new revision files/signatures and four latest alias files may
change. Original base/package paths are excluded from the mutation allowlist.
The same package version cannot move to a lower revision, including from v2
back to v1. A conflicting existing revision is immutable; an exact rerun
verifies and reuses its signatures. A newer package version can still use the
original v1 initial-publication route. Existing version downgrade protection,
GitLab main/approved-review checks, original component byte equality, source
gate, artifact/hash validation, protected signing environment and Pages lock
remain in force. No workflow, credential, permission or runtime control changes
are required. Revision publication continues to record `runtime_ready=false`.

This PR implements the contract and tests it with fixture signatures only.
The active publication input stays unchanged until a later normal review can
bind actual new main-CI IDs and the original ZIP hash. No signing, publication,
installation or phone acceptance is claimed by these fixtures.
