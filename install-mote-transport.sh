#!/usr/bin/env bash
set -euo pipefail

RELEASE_URL="https://github.com/motebus/medge-release/releases/download/mote-transport-v2026.08.28-1"
SPHERE_ASSET="sphere_4.0.0-1_amd64.deb"
MOTED_ASSET="moted_3.2.0-26_amd64.deb"
MOTE_PROXY_ASSET="mote-proxy_1.3.0-35_all.deb"

fail() {
    printf 'Mote Transport install failed: %s\n' "$*" >&2
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
for command_name in apt-get chmod curl dpkg dpkg-deb dpkg-query sha256sum systemctl; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done

PACKAGE_DIR="$(mktemp -d /tmp/mote-transport-install.XXXXXX)"
chmod 0755 "$PACKAGE_DIR"
cleanup() {
    rm -f "$PACKAGE_DIR/$SPHERE_ASSET" \
        "$PACKAGE_DIR/$MOTED_ASSET" \
        "$PACKAGE_DIR/$MOTE_PROXY_ASSET" \
        "$PACKAGE_DIR/SHA256SUMS"
    rmdir "$PACKAGE_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

for asset in "$SPHERE_ASSET" "$MOTED_ASSET" "$MOTE_PROXY_ASSET"; do
    curl --proto '=https' --tlsv1.2 -fL \
        "$RELEASE_URL/$asset" -o "$PACKAGE_DIR/$asset"
    chmod 0644 "$PACKAGE_DIR/$asset"
done

cat >"$PACKAGE_DIR/SHA256SUMS" <<EOF
7e0be26927afa349001caee54cf46117587386f7d42ce82a9611fa50ea1e7065  $SPHERE_ASSET
cf1ee92aaad8ba06e63532667dcc420f279b53d16bc1b73a87d5093bce946a63  $MOTED_ASSET
e158cb68d7888074dd90b263d8ce262ba1d136cc3193553b021bf0768926daaa  $MOTE_PROXY_ASSET
EOF
(
    cd "$PACKAGE_DIR"
    sha256sum --check SHA256SUMS
)

for asset in "$SPHERE_ASSET" "$MOTED_ASSET" "$MOTE_PROXY_ASSET"; do
    package_name="$(dpkg-deb -f "$PACKAGE_DIR/$asset" Package)"
    package_version="$(dpkg-deb -f "$PACKAGE_DIR/$asset" Version)"
    package_architecture="$(dpkg-deb -f "$PACKAGE_DIR/$asset" Architecture)"
    case "$asset:$package_name:$package_version:$package_architecture" in
        "$SPHERE_ASSET:sphere:4.0.0-1:amd64"|\
        "$MOTED_ASSET:moted:3.2.0-26:amd64"|\
        "$MOTE_PROXY_ASSET:mote-proxy:1.3.0-35:all") ;;
        *) fail "unexpected package identity in $asset" ;;
    esac
done

# Install only missing or older Mote Transport components. An existing newer
# package is never downgraded by this immutable release.
set --
for package_spec in \
    "sphere:4.0.0-1:$SPHERE_ASSET" \
    "moted:3.2.0-26:$MOTED_ASSET" \
    "mote-proxy:1.3.0-35:$MOTE_PROXY_ASSET"; do
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
fi

# Package and service readiness is the install boundary. MoteD registration is
# asynchronous and is intentionally not polled or awaited here.
systemctl daemon-reload
systemctl enable --now \
    sphere.service ssh.service moted.service moted-ssh-relay.service mote-proxy.service
systemctl restart moted.service moted-ssh-relay.service mote-proxy.service
systemctl is-active --quiet \
    sphere.service ssh.service moted.service moted-ssh-relay.service mote-proxy.service

dpkg-query -W -f='${Package}=${Version}\n' sphere moted mote-proxy
printf 'Mote Transport is installed and running; MoteD registration continues asynchronously.\n'
