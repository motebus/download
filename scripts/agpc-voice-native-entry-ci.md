# Canonical-entry native CI preparation

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
`1acb212b6c7d34be994b7f67c23821c0430fcd59`, pipeline 28133, job 65812 and MR 11.
The selected `0.1.0~office117.20261015.2+l1isolation.2` Voice DEB is 266,432 bytes,
SHA256 `89005f0c53235e7f72370a624a397d4ef4221a52d1a36d23fcb6b129f4c8d15a`.
The original component job's DEB must exactly equal the staged archive member.
The predecessor is `0.1.0~office117.20261015.2`, SHA256
`4f3daddb1e6b1290fb2bbc411b75a3ff04f26ffc9eb9f097416db40220a20453`.
FreeSWITCH `1.11.3+agpc1` retains SHA256
`a207b111702e7ae7c8682cffa7468a450b66b4acb69203a8f545edcff25a25e4`.
Both the read-only stager and root session helper require that same exact
three-package set. The historical candidate.6 workflow inputs cannot admit
this cohort.

The producer ZIP must contain only `agpc-voice-native-entry-ci/` with twelve
manifested files plus `SOURCE.json`: six helper modules, two native verifiers,
the deterministically rendered `agpc-voice.sh`, and three fixed DEBs. The
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

Fresh mode exercises install/repeat/ABI; upgrade mode additionally seeds the
fixed predecessor and exercises upgrade/repeat/rollback/repeat. The source
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
