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
