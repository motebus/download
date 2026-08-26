#!/usr/bin/env bash
set -euo pipefail

RELEASE_URL="https://github.com/motebus/medge-release/releases/download/deb-v2026.08.26-6"
ASSETS="
sphere_4.0.0-1_amd64.deb
moted_3.2.0-6_amd64.deb
medge_1.1.0-3_all.deb
mote-proxy_1.3.0-2_all.deb
motemcp_1.0.0-3_all.deb
mlink_0.1.0-2_amd64.deb
mdesk_3.0.0-2_amd64.deb
ss-webos_2.0.0-8_amd64.deb
cx-node_0.3.1-7_amd64.deb
"

fail() {
    printf 'MEdge install failed: %s\n' "$*" >&2
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
for command_name in apt-get chmod curl dpkg dpkg-deb dpkg-query sha256sum; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done

PACKAGE_DIR="$(mktemp -d /tmp/medge-install.XXXXXX)"
chmod 0755 "$PACKAGE_DIR"
cleanup() {
    for asset in $ASSETS; do
        rm -f "$PACKAGE_DIR/$asset"
    done
    rm -f "$PACKAGE_DIR/SHA256SUMS"
    rmdir "$PACKAGE_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

for asset in $ASSETS; do
    curl --proto '=https' --tlsv1.2 -fL \
        "$RELEASE_URL/$asset" -o "$PACKAGE_DIR/$asset"
    chmod 0644 "$PACKAGE_DIR/$asset"
done

cat >"$PACKAGE_DIR/SHA256SUMS" <<EOF
7e0be26927afa349001caee54cf46117587386f7d42ce82a9611fa50ea1e7065  sphere_4.0.0-1_amd64.deb
3cd1d0457c91fe038649fb7d861bcdc2a41e92b723b4a189b8d2a16487d05790  moted_3.2.0-6_amd64.deb
332f927952bcb1bc68ee3ce6ee860c347d2000d26dbc8fc30963c68bf1bb964f  medge_1.1.0-3_all.deb
7cb24140a812ff8c59c4d6f165996e47f3b2136a39434305edaeb9ed62e9c762  mote-proxy_1.3.0-2_all.deb
173734eb1cbc50a16a033a6566d0ad9743392c74b79c677f3524faf514d140bd  motemcp_1.0.0-3_all.deb
63905693cab16dde8a4e472431010051f9297835c8d730a02e2db4ff5cba9d5d  mlink_0.1.0-2_amd64.deb
af4bf7493c962ba29c19712e9c12e4df3c08315a5464b53f74949906799942d4  mdesk_3.0.0-2_amd64.deb
803119844bbc3d4f01c578080e94ed365574e63cb4fcc32c5c004b00eb9f14b0  ss-webos_2.0.0-8_amd64.deb
7a3657a6e159dd82d5af4f7ff921dee132142aa6a27804f314a740ad2efd8a12  cx-node_0.3.1-7_amd64.deb
EOF
(
    cd "$PACKAGE_DIR"
    sha256sum --check SHA256SUMS
)

for asset in $ASSETS; do
    package_name="$(dpkg-deb -f "$PACKAGE_DIR/$asset" Package)"
    case "$asset:$package_name" in
        sphere_4.0.0-1_amd64.deb:sphere|\
        moted_3.2.0-6_amd64.deb:moted|\
        medge_1.1.0-3_all.deb:medge|\
        mote-proxy_1.3.0-2_all.deb:mote-proxy|\
        motemcp_1.0.0-3_all.deb:motemcp|\
        mlink_0.1.0-2_amd64.deb:mlink|\
        mdesk_3.0.0-2_amd64.deb:mdesk|\
        ss-webos_2.0.0-8_amd64.deb:ss-webos|\
        cx-node_0.3.1-7_amd64.deb:cx-node) ;;
        *) fail "unexpected package identity in $asset: $package_name" ;;
    esac
done

# Select only missing or older components. A newer installed package is never
# downgraded merely because the immutable release contains an older version.
set --
for package_spec in \
    "sphere:4.0.0-1:sphere_4.0.0-1_amd64.deb" \
    "moted:3.2.0-6:moted_3.2.0-6_amd64.deb" \
    "medge:1.1.0-3:medge_1.1.0-3_all.deb" \
    "mote-proxy:1.3.0-2:mote-proxy_1.3.0-2_all.deb" \
    "motemcp:1.0.0-3:motemcp_1.0.0-3_all.deb" \
    "mlink:0.1.0-2:mlink_0.1.0-2_amd64.deb" \
    "mdesk:3.0.0-2:mdesk_3.0.0-2_amd64.deb" \
    "ss-webos:2.0.0-8:ss-webos_2.0.0-8_amd64.deb" \
    "cx-node:0.3.1-7:cx-node_0.3.1-7_amd64.deb"; do
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

if [ "$#" -gt 0 ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y "$@"
else
    printf 'MEdge complete bundle is already current.\n'
fi

dpkg-query -W -f='${Package}=${Version}\n' \
    sphere moted medge mote-proxy motemcp mlink mdesk ss-webos cx-node
