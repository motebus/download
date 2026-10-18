# Current utility services native evidence — 2026-10-18

Owner: Cito. Reviewed component MR25/main `71b746438e8990ae6685b8ca86dd6bd9e0cdc9e9`
(job65966) adds 104 caller-number readback, 900 global language selection,
901 transient recording/replay and 222 one callback after authenticated caller hangup.
Continuous 117 time announcements and independent 909 radio are retained.

Canonical native run [39137785259](https://github.com/motebus/download/actions/runs/39137785259)
passed fresh/repeat/ABI and both upgrade/repeat/ABI/rollback/repeat modes, from the
accepted zh-TW and l1isolation.2 predecessors. It used reviewed consumer MR98/main
`61a1790a82462d7bfc7b995553ed69b3a610ed7f`, CI28204/job65976. Original artifact ZIPs,
phase states and receipts were independently verified. Source manifest SHA256:
`fba18c9ca1d504dbd36297c5329a82668a490756aab862d820e6df5162bed96a`.
Units stayed inactive, repeated transactions made no package writes, and both rollback
paths restored their exact predecessor and retained FreeSWITCH. This is native installer
evidence; it does not establish L1 installation, activation or telephone acceptance.

Evidence-backed owner admission is MR27/main `e9576897895d57b48f98f24974494f68d6f04e9b`.
Final human-reviewed consumer MR99/main `a6dccfb9eff632e342a5b7b9acd47bcc1022ffa9`
passed CI28208 and release producer job65985. Its unmodified original ZIP is
7846286 bytes, SHA256 `6a96fa3af3017cd20588ba57f11cc776c7f4c8f56dc337fc655a9abb0a6309b1`.
The publication JSON selects this release job, separate from the native-input job.

Selected Voice version:
`0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1`.
Voice package: 348352 bytes, SHA256
`394baefe1242a288f822f5df6d90dd5a6c0eac7d71891aa66f66da19b2cb829f`.
Canonical installer SHA256:
`32380145a06a6bd1d8a0f8b7c1428431b2b951f281f5f6885917738a9fbff251`.
The package and runtime helpers match the tested cohort; admission adds fixed public URLs
and enables the normal install contract after native evidence validation.

This update binds publication inputs. The existing signing workflow, Pages deployment
and versioned public readback are subsequent operations. L1 currently has owner-accepted
zh-TW continuous 117, 909, 123 and 456. Utility activation and phone acceptance are pending;
900 governs built-in prompts, with legacy 123/456 configuration and radio content retained.
No L1 routes, services or phone calls are operated by this repository update.

## Retained previous cohort evidence

# Current zh-TW continuous 117 native evidence — 2026-10-18

Owner: Cito. The unchanged MR22/main `0aa210b4c85cfa0071df62b0dba8835edf31125f`
component (job65941) adds Traditional Chinese Taiwan spoken time, with Asia/Taipei
and continuous announcements until caller hangup preserved.

Canonical native run [39113030565](https://github.com/motebus/download/actions/runs/39113030565)
used protected workflow main `744397c1ace388e9b7897775ddbc55ac134aa23c`, reviewed consumer
MR96/main `06175fe3898b3b25ea4774562a89523590e82294` and producer job65952.
Verified source manifest SHA256:
`2fdf8d2b9ba1f985eac26e8b0da75bca1cb065304d815d3cd49936285132fa4a`.

All three modes passed: fresh/repeat/ABI; accepted continuous117.1 upgrade/repeat/ABI/
rollback/repeat; l1isolation.2 upgrade/repeat/ABI/rollback/repeat. Original artifact ZIPs,
results, phase states and receipts were independently checked. Units remained inactive;
repeat transactions had no package writes; both upgrades restored their exact predecessor
and retained FreeSWITCH. These are finite CI observations, not a normal production
transaction, historical L1 clearance, runtime readiness or telephone acceptance.

The evidence-backed owner admission is MR24/main `588acde13496564580f2314aa740bd5c6f1b4d2f`.
Final human-reviewed consumer MR97/main `61cad4226536d51160db2bcc86bf0c40b47776b7`
binds the package pair, canonical installer, source/build records and public disclosure.
`scripts/agpc-voice-publication.json` must select its actual successful protected-main
release producer and original ZIP. Normal publication uses the existing signed publisher;
verify signatures and versioned public bytes before L1 upgrade.

Selected Voice version:
`0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1`.
Package SHA256: `9216cb1210083ca6e8fa2a8737451a4d8af120c7e92ff0c627b0b9cab890d4b1`.
Canonical installer SHA256: `43a9927d76884c6c0072b7d791e999de616c57f1504bb1444613fa4d6a7edb49`.

L1 zh-TW upgrade and audible phone acceptance remain separate. Preserve 123; no L1
route/service changes or calls occur in this public-source update. 909 activation and
900 global language selection remain pending.

## Retained previous cohort evidence

# Continuous117 and isolated909 native evidence — 2026-10-18

PR263/main bc42a5bd147f7b6f508659b89661a67fa2103a5f selected approved consumer
MR94/main c4539f337f544c2b9846bcc427258a0ce1297e7a, CI28182/job65924.
The unchanged MR19/main de92675ecc9396d0e1a8dab378600ef0afed08cc component
(job65891, 317632 bytes, SHA256
5e01f2793ac9697937d7c4beb9c23a8a4dd014fcd5e766d2c97016f2ae0031d2)
was verified against that original native-input archive.

Actual workflow run39098674528 passed fresh/repeat/ABI and two independent
upgrade/repeat/ABI/rollback/repeat modes from `.2` and `l1isolation.2`.
The original three evidence ZIPs, CI receipts, process completion, inactive units,
repeat no-ops and predecessor restoration were independently checked. No normal
production transaction or phone acceptance is inferred from CI authority.

Owner admission MR21/main4b32e500 and its CI28185 passed. Human-approved consumer
MR95/main b54ee350e76a189f244411ed1f4ac3a7bc2245d2 / CI28186 / release job65933
now provides the distinct formal release bundle. Its original ZIP is 7836792
bytes, SHA256 d4ddf3144522236d7c6dd2ab7e78e376050a91363e23d2b06f459c68f65f6fc5.
The publication JSON selects that release job, never the native-input job.
The admitted shell SHA256 is
4e994dd5351d0e4342a74d2e697dcc96d06a3a5c9df40fb048b1b0f37d7ae392.

This PR binds publication inputs; signing, Pages deployment and public readback
remain separate subsequent actions. L1 continuous117 and909 activation/phone
acceptance are pending, owned by Cito. Preserve123. Global900 language and
zh-TW remain pending. The native workflow topology, permissions and existing
signing/access controls are unchanged.

## Retained previous native preparation notes

# Canonical-entry native CI preparation

SIP-auth Live workflow preparation: component MR15 and consumer MR92 are
approved and merged. MR92 preserves reviewed head
`0207e2bda1abf39773a56f2ab020c871975d173b` in main merge
`44b5ad12521fe0164baebe70c0786c8f8af99cc9`. Its main pipeline 28160 passed:
source-validation job 65856 ran 554 tests and native-entry input producer job
65857 emitted the original 8,006,620-byte ZIP, SHA256
`fac8b24d1149cd7e79c526b6b15307e541c4710788e854c47ef7b6a17236adb7`.
The active public input JSON binds that exact main job and unmodified archive.
All thirteen payloads match the reviewed source, and the selected Voice DEB
matches original component main job 65848. This is input/provenance evidence;
the three native lifecycle jobs have not run for this cohort. PR merge and
manual workflow execution remain separate subsequent actions.

This separate workflow tests the selected closed-gate installer through its
canonical shell entry on disposable Ubuntu 24.04 amd64. The historical
`verify-agpc-voice-native.yml` package-only workflow is unchanged. Neither route
signs or publishes a release, enables Voice, changes SIP routing, contacts a
speech provider or makes a phone call.

The committed `scripts/agpc-voice-native-entry-ci.json` binds the selected
installer main artifact. Update it only after the reviewed installer source is
merged and its protected main producer finishes, using these exact fields:

| Field | Required value |
| --- | --- |
| `schema` | `agpc.voice-native-entry-ci-public-inputs/v1` |
| `source_commit` | Actual 40-character installer main merge revision |
| `ci_job` | Successful `agpc-voice-native-entry-ci-inputs` job for that revision |
| `install_review` | Actual merged installer MR with a recorded Maintainer approval |
| `archive_bytes` | Exact original job artifact ZIP length |
| `archive_sha256` | SHA256 of that original ZIP, without repacking |

The consumer re-reads both source jobs/pipelines and both review approvals using
the existing read-only GitLab connection. Component source is fixed to
`3451049dea8e9014a50a6adef7bf2666604173e8`, pipeline 28156, job 65848 and MR 15.
The selected `0.1.0~office117.20261015.2+l1isolation.2+sipauth.1` Voice DEB is 266,432 bytes,
SHA256 `653d156881ade2b1093a4951bad94a1759abd374f758c1aef0ba2bce6dcb3fd6`.
The original component job's DEB must exactly equal the staged archive member.
The `upgrade` predecessor remains `0.1.0~office117.20261015.2`, SHA256
`4f3daddb1e6b1290fb2bbc411b75a3ff04f26ffc9eb9f097416db40220a20453`.
The distinct `upgrade-l1-isolation` predecessor is
`0.1.0~office117.20261015.2+l1isolation.2`, SHA256
`89005f0c53235e7f72370a624a397d4ef4221a52d1a36d23fcb6b129f4c8d15a`.
FreeSWITCH `1.11.3+agpc1` retains SHA256
`a207b111702e7ae7c8682cffa7468a450b66b4acb69203a8f545edcff25a25e4`.
Both the read-only stager and root session helper require that same exact
four-package set. The historical candidate.6 workflow inputs cannot admit
this cohort.

The producer ZIP must contain only `agpc-voice-native-entry-ci/` with thirteen
manifested files plus `SOURCE.json`: six helper modules, two native verifiers,
the deterministically rendered `agpc-voice.sh`, and four fixed DEBs. The
consumer verifies hashes, bounded archive expansion, exact paths, the source
record's false acceptance flags, and embedded-helper parity without executing
input code. There is no artifact, entrypoint or source override on dispatch.

The workflow copies verified bytes to the fixed root-owned bundle directory.
A separate root helper rechecks the bundle against the verified manifest hash
before writing a new mode-0600 `CI-SESSION.json`. The session binds the actual
workflow/run/attempt/revision, current disposable hostname, selected test mode,
installer commit and manifest hash, and expires after 30 minutes. Environment
strings are execution metadata, not an independent grant. Authority remains
the reviewed workflow and its root invocation. The installer CI contract must
pin the distinct `verify-agpc-voice-native-entry.yml` workflow reference.

Fresh mode exercises install/repeat/ABI. Each of the two upgrade modes seeds
its own fixed predecessor and exercises upgrade/repeat/ABI/rollback/repeat.
Mode-specific session/receipt ownership and pre-writer checks reject a different
known predecessor; neither mode accepts an arbitrary version selector. The source
runner owns process supervision, exact phase ordering, receipts, inactive
package checks, restoration, and failure holds. A timeout or lost VM remains
incomplete; it is never converted into passed evidence. Only that run's output
directory is archived. The root-private session is not an uploaded input or a
production receipt. CI-origin receipts cannot be promoted to production or to
the historical L1 admission contract.

Changing these pins does not establish a native-run result. Retain each actual
workflow run and its original artifacts; an earlier `.2` or candidate.6 result
is not acceptance of this new installer and package cohort. Source review,
native installation acceptance, signed publication and L1 phone acceptance
remain distinct records. No L1 host operation occurs in this workflow.
