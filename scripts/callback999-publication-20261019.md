# Callback center 999 publication — 2026-10-19

This publication selects the reviewed project1341 main build
`f94bcab3751e9fc5f37a0cfd57c294954a99ca4d`, CI28226/job66028, MR102.
The exact original archive is 7847428 bytes with SHA256
`45b864d854a4f896fd9c7ceea64d70e55080612085ce3c6f40d6a4e700a826e6`.
The installer SHA256 is
`2e1eb64e01d5398e9492237dae1bb25eca2f258fa075aa4190241f7cce7a57a0`.

Component provenance remains project1348 MR28/main
`242a5e3441735e88c23164605487f87444e2c851`, CI28210/job65990.
The package is `0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1+callback999.1`,
348352 bytes, SHA256
`d30efe600ab1cff0f6fe22283b16fb296439c0d5b19c0cc71f3d1e2c9f3c1b70`.

222 remains the incoming trigger. After the authenticated caller hangs up,
one callback to the same extension uses From user 999. No incoming 999
service is added. Global language, ephemeral recording and durable consumed
callback attempts are retained.

Native validation runs 39187285890 and39187420722 each passed fresh install
and both upgrade/rollback modes. Earlier run39185137410 failed in rollback;
its cause remains undetermined, the failure was not reproduced in the two
new runs, and its retained hold evidence was not cleared. Source MR31 and
consumer MR102 include this disposition. Tests do not establish telephone
caller-ID display or live activation.

This change updates publication selection only. It reuses the existing signing
workflow, key, permissions and Pages lock. L1 installation and activation use
a separate owner-executed packet with baseline checks, backup and rollback.
