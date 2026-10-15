# Canonical-entry native CI preparation

This separate workflow tests the selected closed-gate installer through its
canonical shell entry on disposable Ubuntu 24.04 amd64. The historical
`verify-agpc-voice-native.yml` package-only workflow is unchanged. Neither route
signs or publishes a release, enables Voice, changes SIP routing, contacts a
speech provider or makes a phone call.

There is deliberately no active `scripts/agpc-voice-native-entry-ci.json` yet.
After the reviewed installer source is merged and its protected main producer
finishes, commit that file with these exact fields:

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
`d3349db4caa44e357650f0e225ce9526727e08a7`, pipeline 28063, job 65655 and MR 5.
The unchanged `.2` Voice DEB is 48,834 bytes, SHA256
`4f3daddb1e6b1290fb2bbc411b75a3ff04f26ffc9eb9f097416db40220a20453`.
The original component job's DEB must exactly equal the staged archive member.
Candidate.6 and FreeSWITCH retain their existing exact archive pins.

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

This preparation has no native-run result. The active input remains absent
until real protected-main artifacts and review references can be supplied.
