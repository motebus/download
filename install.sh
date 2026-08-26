#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://motebus.github.io/medge-release"
EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
KEYRING_PATH="/etc/apt/keyrings/medge-archive-keyring.gpg"
SOURCES_PATH="/etc/apt/sources.list.d/medge.sources"
INSTALL_PROFILE="${MEDGE_INSTALL_PROFILE:-}"

case "$INSTALL_PROFILE" in
    medge)      APT_PACKAGES="sphere moted medge" ;;
    mdesk)      APT_PACKAGES="sphere moted mlink mdesk" ;;
    ss-webos)   APT_PACKAGES="ss-webos" ;;
    mote-proxy) APT_PACKAGES="sphere mote-proxy" ;;
    motemcp)    APT_PACKAGES="sphere moted motemcp" ;;
    *)
        printf 'MEdge install failed: use a named component installer\n' >&2
        exit 1
        ;;
esac

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
for command_name in apt-get awk cmp curl dpkg dpkg-query gpg install; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done

TEMP_DIR="$(mktemp -d /tmp/medge-install.XXXXXX)"
cleanup() {
    rm -f "$TEMP_DIR/medge-archive-keyring.gpg" \
        "$TEMP_DIR/medge.sources" "$TEMP_DIR/expected.sources"
    rmdir "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

curl --proto '=https' --tlsv1.2 -fsSLo \
    "$TEMP_DIR/medge-archive-keyring.gpg" \
    "$BASE_URL/medge-archive-keyring.gpg"
curl --proto '=https' --tlsv1.2 -fsSLo \
    "$TEMP_DIR/medge.sources" "$BASE_URL/medge.sources"

ACTUAL_FINGERPRINT="$(
    gpg --batch --show-keys --with-colons \
        "$TEMP_DIR/medge-archive-keyring.gpg" |
        awk -F: '
            $1 == "pub" { public_keys += 1 }
            $1 == "fpr" && fingerprint == "" { fingerprint = $10 }
            END {
                if (public_keys != 1 || fingerprint == "") exit 1
                print fingerprint
            }
        '
)" || fail "the downloaded archive key is invalid"
[ "$ACTUAL_FINGERPRINT" = "$EXPECTED_FINGERPRINT" ] ||
    fail "archive-key fingerprint mismatch"

cat >"$TEMP_DIR/expected.sources" <<EOF
Types: deb
URIs: $BASE_URL
Suites: stable
Components: main
Architectures: amd64
Signed-By: $KEYRING_PATH
EOF
cmp -s "$TEMP_DIR/medge.sources" "$TEMP_DIR/expected.sources" ||
    fail "the downloaded APT source definition is invalid"

install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$TEMP_DIR/medge-archive-keyring.gpg" "$KEYRING_PATH"
install -m 0644 "$TEMP_DIR/medge.sources" "$SOURCES_PATH"

export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::http::No-Cache=true update
APT_INSTALL_PLAN="$(apt-get --print-uris -y install $APT_PACKAGES)" ||
    fail "cannot resolve the APT transaction"
if printf '%s\n' "$APT_INSTALL_PLAN" |
    grep -Eiq "(https?|ssh|git)://[^[:space:]\"']*gitlab[.]"; then
    fail "the APT transaction contains a forbidden GitLab URL"
fi

# One package transaction, scoped to the selected component boundary. This
# installer never removes a retired package or changes a locked topology file.
apt-get install -y $APT_PACKAGES
dpkg-query -W -f='${Package}=${Version}\n' $APT_PACKAGES
