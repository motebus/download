#!/bin/sh
set -eu

BASE_URL="https://motebus.github.io/medge-release"
EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
NODE_ID=""
HUB_MMA=""
BOOTSTRAP=""

fail() { printf 'CX Install failed: %s\n' "$*" >&2; exit 1; }
usage() {
    printf '%s\n' "Usage: sudo sh cx-install.sh --node-id CX<number> --hub-mma <mma> --bootstrap <absolute-file>"
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --node-id) [ "$#" -ge 2 ] || fail "--node-id requires a value"; NODE_ID=$2; shift 2 ;;
        --hub-mma) [ "$#" -ge 2 ] || fail "--hub-mma requires a value"; HUB_MMA=$2; shift 2 ;;
        --bootstrap) [ "$#" -ge 2 ] || fail "--bootstrap requires a value"; BOOTSTRAP=$2; shift 2 ;;
        --help) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done
[ "$(id -u)" -eq 0 ] || fail "run as root"
printf '%s' "$NODE_ID" | grep -Eq '^CX[1-9][0-9]*$' || fail "node identity must be CX<number>"
printf '%s' "$HUB_MMA" | grep -Eq '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$' || fail "Hub MMA must have three explicit segments"
case "$BOOTSTRAP" in /*) ;; *) fail "bootstrap path must be absolute" ;; esac
[ -f "$BOOTSTRAP" ] && [ ! -L "$BOOTSTRAP" ] || fail "bootstrap must be a regular non-symlink file"
[ -r /etc/os-release ] || fail "cannot identify operating system"
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    debian:12|debian:13|ubuntu:24.04|ubuntu:26.04) ;;
    *) fail "Debian 12/13 or Ubuntu 24.04/26.04 is required" ;;
esac
[ "$(dpkg --print-architecture)" = amd64 ] || fail "amd64 is required"
[ -d /run/systemd/system ] || fail "systemd must be running"

awk -F= '
 /^[[:space:]]*($|#)/ { next }
 { key=$1; value=substr($0,index($0,"=")+1); if ($0 !~ /=/ || key !~ /^MCHAT_(APPNAME|EINAME|DC|IOC|MBGWIP|WATCHLEVEL)$/ || value=="" || ++seen[key]>1) bad=1 }
 END { for (i in seen) count++; if (!seen["MCHAT_APPNAME"] || !seen["MCHAT_DC"] || !seen["MCHAT_IOC"] || !seen["MCHAT_MBGWIP"] || !seen["MCHAT_WATCHLEVEL"] || bad) exit 1 }
' "$BOOTSTRAP" || fail "bootstrap must contain only the complete canonical MCHAT_* topology set"

target=/etc/mote/cx-node/cx-node-mchat.env
if [ -e "$target" ]; then
    [ -f "$target" ] && [ ! -L "$target" ] || fail "locked topology target must be a regular non-symlink file"
    cmp -s "$BOOTSTRAP" "$target" || fail "locked topology already exists with different bytes"
fi

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg
tmp=$(mktemp -d /tmp/cx-install.XXXXXX)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
curl --proto '=https' --tlsv1.2 -fsSLo "$tmp/key.gpg" "$BASE_URL/medge-archive-keyring.gpg"
fingerprint=$(gpg --batch --show-keys --with-colons "$tmp/key.gpg" | awk -F: '$1=="fpr" {print $10; exit}')
[ "$fingerprint" = "$EXPECTED_FINGERPRINT" ] || fail "archive key fingerprint mismatch"
install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$tmp/key.gpg" /etc/apt/keyrings/medge-archive-keyring.gpg
cat >"$tmp/medge.sources" <<EOF
Types: deb
URIs: $BASE_URL
Suites: stable
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/medge-archive-keyring.gpg
EOF
install -m 0644 "$tmp/medge.sources" /etc/apt/sources.list.d/medge.sources
apt-get -o Acquire::http::No-Cache=true update
install_plan=$(apt-get --print-uris -y install sphered moted aport qbix mbox motestream motessh moterdp cx-node)
printf '%s\n' "$install_plan" | grep -Eqi 'gitlab\.' && fail "APT transaction contains a forbidden GitLab URL"
apt-get install -y sphered moted aport qbix mbox motestream motessh moterdp cx-node

install -d -o root -g cx-node -m 0750 /etc/mote/cx-node
if [ -e "$target" ]; then
    cmp -s "$BOOTSTRAP" "$target" || fail "locked topology changed during installation"
else
    install -o root -g cx-node -m 0640 "$BOOTSTRAP" "$target"
fi
umask 027
printf 'CX_NODE_ID=%s\nCX_CONTROLLER_TARGET=%s\nCX_HEARTBEAT_SECONDS=30\n' "$NODE_ID" "$HUB_MMA" > /etc/mote/cx-node/cx-node.env
chown root:cx-node /etc/mote/cx-node/cx-node.env
systemctl daemon-reload
systemctl enable --now cx-node.service
systemctl is-active --quiet cx-node.service || fail "cx-node service did not become active"
printf 'CX Install complete: node=%s hub=%s\n' "$NODE_ID" "$HUB_MMA"
