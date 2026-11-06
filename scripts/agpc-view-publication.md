# AGPC View standalone publication

This publisher copies the reviewed native DEB from project 1336 main CI to a
versioned GitHub release. It does not compile or install software, change Pages
or APT, or admit View into the Core/All installers. The runtime remains owned by
the private Core source project.

First collect the final successful pipeline, `agpc-view-native` and
`agpc-view-gui-native` job API receipts and original native job artifacts.
The job IDs must belong to the same successful main pipeline and source commit.
Prepare a reviewable candidate with:

```sh
python3 scripts/publish_agpc_view.py prepare \
  --bundle /path/to/original-ci-dist \
  --pipeline /path/to/pipeline.json \
  --native-job /path/to/native-job.json \
  --gui-job /path/to/gui-job.json \
  --output /path/to/new-candidate-bundle \
  --record-output scripts/agpc-view-release.json
```

Preparation verifies package identity, fixed dependency boundary, scriptless
control, the eight-file payload, clean exact source provenance and native GTK4
ELF metadata, including GIO for the system browser and the Local/Mode/SSO source modules. Native TLS increases the executable size; payload members have a bounded 4 MiB limit, while JSON and downloadable assets retain the 2 MiB limit. It never executes the package binary. The original packaged
provenance stays unchanged. The public manifest removes the producer's local
library-resolution text and adds the source project/commit/pipeline/job IDs.
It contains no private repository URLs or source archive.

Review the input record and candidate bytes. Stage exactly the three files
from the candidate directory in the draft `candidate-agpc-view-v0.1.0-4`
release: the DEB, `MANIFEST.json`, and `SHA256SUMS`. Do not replace an existing
asset with different bytes. Merge the reviewed record, publisher, tests and
workflow before dispatch:

```sh
gh workflow run publish-agpc-view.yml --repo motebus/download --ref main
```

The release job freshly verifies private source main and both mandatory CI
jobs, then downloads the original native-job DEB and manifest through the
authenticated project API. Bounded downloads must match the committed record
and candidate bytes. It rejects source/public-main movement, failed or optional
jobs, changed artifacts, unknown candidate files and existing public release
tags. Hash consistency alone is not treated as compilation evidence.

The existing release-environment archive key signs `MANIFEST.json` and
`SHA256SUMS`; both bind the exact DEB. The trusted fingerprint is
`AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0`. The signer verifies each generated
signature before publishing the five immutable assets as
`agpc-view-v0.1.0-4`. It neither reads nor prints owner credentials.

After publication, download the release independently, verify both signatures
with established archive-key trust, check `SHA256SUMS` and manifest identity,
and then use the target's authorized package transaction. The GUI runs as the
desktop user. Package installation does not establish Mesh runtime readiness.
