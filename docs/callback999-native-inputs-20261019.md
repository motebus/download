# Callback center 999 native inputs — 2026-10-19

Owner Cito. 222 remains the inbound trigger; its one callback uses source 999.
No inbound 999 service is added.

The exact reviewed MR100 / CI28215 / job66001 archive is pinned in
scripts/agpc-voice-native-entry-ci.json. The companion JSON records the original
archive and manifest hashes. The selected component remains reviewed MR28/main
242a5e3441735e88c23164605487f87444e2c851 / CI28210 / job65990.

Use the existing finite Ubuntu 24.04 workflow for fresh/repeat/ABI and two
upgrade/repeat/ABI/rollback/repeat paths from utilities.1 and l1isolation.2.
Downloader and root session require the same selected/predecessor archives.
Authority, secrets, workflow environment, supervision and holds are unchanged.

The publisher permits this reviewed 110-character version and rejects longer
strings and path/control characters. Review, provenance, immutable assets and
signature checks are retained. This input PR does not admit installation or
publish a signed release. Native results, final admission, publication and L1
phone caller-ID acceptance remain separate steps. No L1 runtime change or call.
