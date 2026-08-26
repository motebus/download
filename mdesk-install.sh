#!/bin/sh
set -eu

RELEASE_URL="https://github.com/motebus/medge-release/releases/download/deb-v2026.08.26-1"
SPHERE_ASSET="sphere_4.0.0-1_amd64.deb"
MOTED_ASSET="moted_3.2.0-2_amd64.deb"
MDESK_ASSET="mdesk_3.0.0-1_amd64.deb"

fail() {
    printf 'MDesk install failed: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || fail "run this installer as root"
[ -r /etc/os-release ] || fail "cannot identify the operating system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:24.04|ubuntu:26.04) ;;
    *) fail "Ubuntu 24.04 or 26.04 is required" ;;
esac
[ "$(dpkg --print-architecture)" = amd64 ] || fail "amd64 is required"
for command_name in apt-get curl dpkg sha256sum; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done

PACKAGE_DIR="$(mktemp -d /tmp/mdesk-install.XXXXXX)"
cleanup() {
    rm -f "$PACKAGE_DIR/$SPHERE_ASSET" \
        "$PACKAGE_DIR/$MOTED_ASSET" \
        "$PACKAGE_DIR/$MDESK_ASSET" \
        "$PACKAGE_DIR/SHA256SUMS"
    rmdir "$PACKAGE_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

for asset in "$SPHERE_ASSET" "$MOTED_ASSET" "$MDESK_ASSET"; do
    curl --proto '=https' --tlsv1.2 -fL \
        "$RELEASE_URL/$asset" -o "$PACKAGE_DIR/$asset"
done

cat >"$PACKAGE_DIR/SHA256SUMS" <<EOF
7e0be26927afa349001caee54cf46117587386f7d42ce82a9611fa50ea1e7065  $SPHERE_ASSET
d162a144c35b218f6c0a08280373da4707d3f6cf4805536601c2acd921dbc37f  $MOTED_ASSET
6228537734a19026eed5dde0435c2d913392aedb01d188980393b46fbbc436ae  $MDESK_ASSET
EOF
(
    cd "$PACKAGE_DIR"
    sha256sum --check SHA256SUMS
)

for asset in "$SPHERE_ASSET" "$MOTED_ASSET" "$MDESK_ASSET"; do
    package_name="$(dpkg-deb -f "$PACKAGE_DIR/$asset" Package)"
    case "$asset:$package_name" in
        "$SPHERE_ASSET:sphere"|"$MOTED_ASSET:moted"|"$MDESK_ASSET:mdesk") ;;
        *) fail "unexpected package identity in $asset: $package_name" ;;
    esac
done

# Select only missing or older components. A newer installed package is never
# downgraded merely because the immutable release contains an older version.
set --
for package_spec in \
    "sphere:4.0.0-1:$SPHERE_ASSET" \
    "moted:3.2.0-2:$MOTED_ASSET" \
    "mdesk:3.0.0-1:$MDESK_ASSET"; do
    package_name="${package_spec%%:*}"
    package_rest="${package_spec#*:}"
    package_version="${package_rest%%:*}"
    package_asset="${package_rest#*:}"
    installed_version="$(
        dpkg-query -W -f='${Version}' "$package_name" 2>/dev/null || true
    )"
    if [ -z "$installed_version" ] ||
        dpkg --compare-versions "$installed_version" lt "$package_version"; then
        set -- "$@" "$PACKAGE_DIR/$package_asset"
    else
        printf 'Keeping %s=%s (release version is %s)\n' \
            "$package_name" "$installed_version" "$package_version"
    fi
done

# One APT transaction installs the selected MDesk boundary. It never removes
# desk/ss-desk or writes a locked MChat topology file.
if [ "$#" -gt 0 ]; then
    apt-get install -y "$@"
fi

dpkg-query -W -f='${Package}=${Version}\n' sphere moted mdesk
