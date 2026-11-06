# Core and All with AGPC View publication

`publish-agpc-view-profiles.yml` publishes two immutable prereleases from one reviewed protected-main producer: installer `v0.3.0-96` and aggregate `agent-computer-v0.3.0-85`. It uses the existing `release` environment and serial publication group. It does not sign assets, deploy Pages, install packages, or claim native profile acceptance. No private source checkout or export is published by this workflow.

The committed `scripts/agpc-view-profile-publication.json` must be prepared only after project 1341 protected main has a successful full pipeline and `agpc-view-profile-release-artifacts` job. There is intentionally no placeholder record. Download that job's exact `agpc-view-profiles/` directory, the pipeline and job API JSON receipts, and the committed `scripts/agpc-view-profile-release-input.json` blob at that source commit. Prepare the review record locally:

```sh
python3 scripts/publish_agpc_view_profiles.py prepare \
  --bundle /absolute/path/agpc-view-profiles \
  --pipeline /absolute/path/pipeline.json \
  --job /absolute/path/job.json \
  --inputs /absolute/path/agpc-view-profile-release-input.json \
  --record-output scripts/agpc-view-profile-publication.json
```

Review and merge the real record together with the publisher. The record pins source commit, job, pipeline, tracked input SHA256, and every one of the 13 artifact filenames, SHA256s, and byte counts. Publication independently reads the current protected main, pipeline, exact non-optional job, tracked input blob, and original job artifacts through the authenticated API. It requires the same source commit and successful pipeline, and also requires this workflow's commit to remain current public main. An advanced source or publisher main requires review; there is no override.

Dispatch on public main with `release=aggregate`, then `release=installer`. Each mode first verifies the selected tag and release do not exist. If the counterpart exists, it downloads and checks every counterpart asset against the same record before creating the missing release. No operation replaces, deletes, or repairs an existing tag or asset. A completed-mode rerun refuses publication. If a command or connection fails after release creation, inspect its exact release inventory and hashes; dispatch only the other missing mode after the completed release matches. Partial or mismatched existing releases require separate review and fail closed.

The installer release contains the 13 unchanged CI files: five shell entries including `agpc-core.sh`, four source records, the overlay, release manifest, aggregate component record, and checksums. The Core entry must equal the standard entry byte for byte. The aggregate downloads the original 33 baseline packages plus the existing signed standalone View DEB, and verifies every digest. All source URLs remain private; public metadata uses only project/commit/job identifiers. The same source commit, input package identity, manifest, overlay, aggregate record and checksum inventory must agree.

Pages activation remains a separate protected workflow: run the full private-source tests before its explicit public-source export, retain archive signatures and required native Core/All profile acceptance, and preserve the unrelated current Pages content. Publishing these prereleases does not bypass those gates.
