#!/usr/bin/env bash
# Only disposable verification containers use this mirror; installer sources
# and package trust are unchanged. An explicit fixture root supports local tests.
set -euo pipefail
[[ $# -le 1 ]] || exit 2
fixture_root=${1:-/}
if [[ $fixture_root == / ]]; then
    [[ -f /.dockerenv ]] || { echo 'Disposable Docker verification root required' >&2; exit 1; }
fi
[[ -d "$fixture_root/etc/apt" ]] || exit 1
for source in "$fixture_root/etc/apt/sources.list" \
    "$fixture_root/etc/apt/sources.list.d/"*.list \
    "$fixture_root/etc/apt/sources.list.d/"*.sources; do
    [[ -f $source && ! -L $source ]] || continue
    # Preserve HTTPS when already configured, all suites and Signed-By fields.
    # https://learn.microsoft.com/azure/virtual-machines/linux/create-upload-ubuntu
    sed -i 's#\(https\?://\)\(archive\|security\)\.ubuntu\.com/ubuntu#\1azure.archive.ubuntu.com/ubuntu#g' "$source"
done
mkdir -p "$fixture_root/etc/apt/apt.conf.d"
printf '%s\n' 'Acquire::Retries "2";' 'Acquire::http::Timeout "30";' \
    'Acquire::https::Timeout "30";' >"$fixture_root/etc/apt/apt.conf.d/99-agpc-ci-downloads"
echo 'AGPC verification: Ubuntu Azure mirror selected; signed APT verification remains enabled'
