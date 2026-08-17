#!/bin/sh
set -eu

BASE_URL="https://motebus.github.io/medge-release"
EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
PACKAGES="ca-certificates curl gnupg openssh-client openssh-server sphered moted aport qbix mbox motestream motessh moterdp cx-node"
SYSTEM_UNITS="sphered.service mbox.service moted.service qbix.service agosd.service ssh.service cx-node.service"
SERVICE_STABILITY_SECONDS=10
MODE="install"
NODE_ID=""
NODE_MOTE=""
HUB_MMA=""
CX_BOOTSTRAP=""
MOTESSH_BOOTSTRAP=""
CX_TOPOLOGY=/etc/mote/cx-node/cx-node-mchat.env
MOTESSH_TOPOLOGY=/etc/mote/motessh/motessh-mchat.env
CX_CONFIG=/etc/mote/cx-node/cx-node.env

fail() {
    printf 'CX installation failed: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  sudo sh cx-install.sh install --node-id CX<number> --node-mote <name.mote> \
    --hub-mma <mma> --cx-bootstrap <absolute-file> \
    --motessh-bootstrap <absolute-file>
  sudo /usr/libexec/cx-node/cx-install.sh doctor
  sudo /usr/libexec/cx-node/cx-install.sh uninstall

Re-run install with the same identities and byte-identical bootstrap files to
upgrade from the signed stable APT channel. Uninstall removes only cx-node;
shared MEdge, MoteSSH, OpenSSH, locked topology, configuration, and state stay.
EOF
}

case "${1:-}" in
    install|doctor|uninstall) MODE=$1; shift ;;
    --help|-h) usage; exit 0 ;;
esac

while [ "$#" -gt 0 ]; do
    case "$1" in
        --node-id) [ "$#" -ge 2 ] || fail "--node-id requires a value"; NODE_ID=$2; shift 2 ;;
        --node-mote) [ "$#" -ge 2 ] || fail "--node-mote requires a value"; NODE_MOTE=$2; shift 2 ;;
        --hub-mma) [ "$#" -ge 2 ] || fail "--hub-mma requires a value"; HUB_MMA=$2; shift 2 ;;
        --cx-bootstrap) [ "$#" -ge 2 ] || fail "--cx-bootstrap requires a value"; CX_BOOTSTRAP=$2; shift 2 ;;
        --motessh-bootstrap) [ "$#" -ge 2 ] || fail "--motessh-bootstrap requires a value"; MOTESSH_BOOTSTRAP=$2; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || fail "run as root"
[ -r /etc/os-release ] || fail "cannot identify operating system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:24.04|ubuntu:26.04) ;;
    *) fail "Ubuntu 24.04 or 26.04 is required" ;;
esac
command -v dpkg >/dev/null 2>&1 || fail "dpkg is unavailable"
[ "$(dpkg --print-architecture)" = amd64 ] || fail "amd64 is required"
[ -d /run/systemd/system ] || fail "systemd must be running"

validate_topology() {
    topology_file=$1
    topology_label=$2
    [ -f "$topology_file" ] && [ ! -L "$topology_file" ] ||
        fail "$topology_label must be a regular non-symlink file"
    awk -F= '
      /^[[:space:]]*($|#)/ { next }
      {
        key=$1
        value=substr($0,index($0,"=")+1)
        if ($0 !~ /=/ || key !~ /^MCHAT_(APPNAME|EINAME|DC|IOC|MBGWIP|WATCHLEVEL)$/ || value=="" || ++seen[key]>1) bad=1
      }
      END {
        if (!seen["MCHAT_APPNAME"] || !seen["MCHAT_DC"] || !seen["MCHAT_IOC"] ||
            !seen["MCHAT_MBGWIP"] || !seen["MCHAT_WATCHLEVEL"] || bad) exit 1
      }
    ' "$topology_file" ||
        fail "$topology_label must contain only the complete canonical MCHAT_* topology set"
}

validate_locked_input() {
    source_file=$1
    target_file=$2
    target_label=$3
    if [ -e "$target_file" ]; then
        [ -f "$target_file" ] && [ ! -L "$target_file" ] ||
            fail "$target_label target must be a regular non-symlink file"
        cmp -s "$source_file" "$target_file" ||
            fail "$target_label already exists with different bytes"
    fi
}

validate_cx_config() {
    [ -f "$CX_CONFIG" ] && [ ! -L "$CX_CONFIG" ] ||
        fail "CX Node configuration is missing or is not a regular file"
    awk -F= '
      /^[[:space:]]*($|#)/ { next }
      {
        key=$1
        value=substr($0,index($0,"=")+1)
        if ($0 !~ /=/ || key !~ /^CX_(NODE_ID|NODE_MOTE|CONTROLLER_TARGET|HEARTBEAT_SECONDS)$/ || value=="" || ++seen[key]>1) bad=1
      }
      END {
        if (!seen["CX_NODE_ID"] || !seen["CX_NODE_MOTE"] || !seen["CX_CONTROLLER_TARGET"] ||
            !seen["CX_HEARTBEAT_SECONDS"] || bad) exit 1
      }
    ' "$CX_CONFIG" || fail "CX Node configuration is incomplete or contains unknown keys"
}

env_value() {
    awk -F= -v wanted="$2" '$1 == wanted { print substr($0,index($0,"=")+1); exit }' "$1"
}

unit_failure() {
    failed_unit=$1
    printf '\nStatus for %s:\n' "$failed_unit" >&2
    systemctl --no-pager --full status "$failed_unit" >&2 || true
    printf '\nRecent journal for %s:\n' "$failed_unit" >&2
    journalctl --no-pager -n 50 -u "$failed_unit" >&2 || true
    fail "$failed_unit is not healthy"
}

doctor() {
    for package_name in $PACKAGES; do
        [ "$(dpkg-query -W -f='${db:Status-Status}' "$package_name" 2>/dev/null || true)" = installed ] ||
            fail "required package is not installed: $package_name"
    done
    for command_name in ssh sshd motessh cx-node systemctl runuser; do
        command -v "$command_name" >/dev/null 2>&1 ||
            fail "required runtime command is unavailable: $command_name"
    done

    validate_topology "$CX_TOPOLOGY" "installed CX Node topology"
    validate_topology "$MOTESSH_TOPOLOGY" "installed MoteSSH topology"
    validate_cx_config
    [ "$(stat -c '%U:%G:%a' "$CX_TOPOLOGY")" = root:cx-node:640 ] ||
        fail "CX Node topology ownership/mode must be root:cx-node:640"
    [ "$(stat -c '%U:%G:%a' "$MOTESSH_TOPOLOGY")" = root:root:644 ] ||
        fail "MoteSSH topology ownership/mode must be root:root:644"

    sshd -t || fail "OpenSSH server configuration validation failed"
    /usr/bin/motessh --help >/dev/null || fail "MoteSSH self-check failed"

    runuser -u cx-node -- env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        CX_NODE_ID="$(env_value "$CX_CONFIG" CX_NODE_ID)" \
        CX_NODE_MOTE="$(env_value "$CX_CONFIG" CX_NODE_MOTE)" \
        CX_CONTROLLER_TARGET="$(env_value "$CX_CONFIG" CX_CONTROLLER_TARGET)" \
        CX_HEARTBEAT_SECONDS="$(env_value "$CX_CONFIG" CX_HEARTBEAT_SECONDS)" \
        MCHAT_APPNAME="$(env_value "$CX_TOPOLOGY" MCHAT_APPNAME)" \
        MCHAT_EINAME="$(env_value "$CX_TOPOLOGY" MCHAT_EINAME)" \
        MCHAT_DC="$(env_value "$CX_TOPOLOGY" MCHAT_DC)" \
        MCHAT_IOC="$(env_value "$CX_TOPOLOGY" MCHAT_IOC)" \
        MCHAT_MBGWIP="$(env_value "$CX_TOPOLOGY" MCHAT_MBGWIP)" \
        MCHAT_WATCHLEVEL="$(env_value "$CX_TOPOLOGY" MCHAT_WATCHLEVEL)" \
        /usr/bin/cx-node --check-config >/dev/null ||
        fail "CX Node configuration self-check failed"

    for unit_name in $SYSTEM_UNITS; do
        systemctl is-enabled --quiet "$unit_name" || unit_failure "$unit_name"
        systemctl is-active --quiet "$unit_name" || unit_failure "$unit_name"
    done
    restart_snapshot=$(
        for unit_name in $SYSTEM_UNITS; do
            printf '%s=%s\n' "$unit_name" "$(systemctl show "$unit_name" -p NRestarts --value)"
        done
    )
    sleep "$SERVICE_STABILITY_SECONDS"
    for unit_name in $SYSTEM_UNITS; do
        systemctl is-active --quiet "$unit_name" || unit_failure "$unit_name"
        restarts_before=$(printf '%s\n' "$restart_snapshot" |
            awk -F= -v wanted="$unit_name" '$1 == wanted { print $2; exit }')
        restarts_after=$(systemctl show "$unit_name" -p NRestarts --value)
        [ "$restarts_after" = "$restarts_before" ] || unit_failure "$unit_name"
    done
    printf 'CX doctor OK: CX Node + MoteSSH + MoteBus control + OpenSSH execution are healthy\n'
}

if [ "$MODE" = doctor ]; then
    doctor
    exit 0
fi

if [ "$MODE" = uninstall ]; then
    systemctl disable --now cx-node.service >/dev/null 2>&1 || true
    if dpkg-query -W -f='${db:Status-Status}' cx-node 2>/dev/null | grep -qx installed; then
        apt-get remove -y --no-auto-remove cx-node
    fi
    printf '%s\n' \
        'CX Node removed. MEdge, MoteSSH, OpenSSH, locked topology, configuration, and state were preserved.'
    exit 0
fi

printf '%s' "$NODE_ID" | grep -Eq '^CX[1-9][0-9]*$' ||
    fail "node identity must be CX<number>"
printf '%s' "$NODE_MOTE" | grep -Eq '^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+mote$' ||
    fail "node Mote must be an approved *.mote identity"
printf '%s' "$HUB_MMA" | grep -Eq '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$' ||
    fail "Hub MMA must have three explicit segments"
case "$CX_BOOTSTRAP" in /*) ;; *) fail "CX bootstrap path must be absolute" ;; esac
case "$MOTESSH_BOOTSTRAP" in /*) ;; *) fail "MoteSSH bootstrap path must be absolute" ;; esac
validate_topology "$CX_BOOTSTRAP" "CX bootstrap"
validate_topology "$MOTESSH_BOOTSTRAP" "MoteSSH bootstrap"
validate_locked_input "$CX_BOOTSTRAP" "$CX_TOPOLOGY" "locked CX Node topology"
validate_locked_input "$MOTESSH_BOOTSTRAP" "$MOTESSH_TOPOLOGY" "locked MoteSSH topology"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg
temporary_dir=$(mktemp -d /tmp/cx-install.XXXXXX)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM
curl --proto '=https' --tlsv1.2 -fsSLo "$temporary_dir/key.gpg" \
    "$BASE_URL/medge-archive-keyring.gpg"
fingerprint=$(gpg --batch --show-keys --with-colons "$temporary_dir/key.gpg" |
    awk -F: '$1=="fpr" {print $10; exit}')
[ "$fingerprint" = "$EXPECTED_FINGERPRINT" ] || fail "archive key fingerprint mismatch"
install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$temporary_dir/key.gpg" /etc/apt/keyrings/medge-archive-keyring.gpg
cat >"$temporary_dir/medge.sources" <<EOF
Types: deb
URIs: $BASE_URL
Suites: stable
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/medge-archive-keyring.gpg
EOF
install -m 0644 "$temporary_dir/medge.sources" /etc/apt/sources.list.d/medge.sources
apt-get -o Acquire::http::No-Cache=true update
mkdir "$temporary_dir/motessh-package"
(
    cd "$temporary_dir/motessh-package"
    apt-get download motessh
)
motessh_deb=$(find "$temporary_dir/motessh-package" -maxdepth 1 -type f -name 'motessh_*.deb' -print)
[ -n "$motessh_deb" ] && [ "$(printf '%s\n' "$motessh_deb" | wc -l)" -eq 1 ] ||
    fail "the signed MoteSSH package download is missing or ambiguous"
[ "$(dpkg-deb -f "$motessh_deb" Package)" = motessh ] &&
    [ "$(dpkg-deb -f "$motessh_deb" Architecture)" = amd64 ] ||
    fail "the downloaded MoteSSH package identity is invalid"
dpkg-deb --extract "$motessh_deb" "$temporary_dir/motessh-extracted"
signed_motessh_topology="$temporary_dir/motessh-extracted/usr/share/motessh/motessh-mchat.env"
validate_topology "$signed_motessh_topology" "signed MoteSSH package topology"
cmp -s "$MOTESSH_BOOTSTRAP" "$signed_motessh_topology" ||
    fail "MoteSSH bootstrap does not match the topology bound into the signed package"
install_plan=$(apt-get --print-uris -y install $PACKAGES)
printf '%s\n' "$install_plan" | grep -Eqi 'gitlab\.' &&
    fail "APT transaction contains a forbidden GitLab URL"
apt-get install -y --no-install-recommends $PACKAGES

install -d -o root -g cx-node -m 0750 /etc/mote/cx-node
install -d -o root -g root -m 0755 /etc/mote/motessh
if [ ! -e "$CX_TOPOLOGY" ]; then
    install -o root -g cx-node -m 0640 "$CX_BOOTSTRAP" "$CX_TOPOLOGY"
fi
if [ ! -e "$MOTESSH_TOPOLOGY" ]; then
    install -o root -g root -m 0644 "$MOTESSH_BOOTSTRAP" "$MOTESSH_TOPOLOGY"
fi
cmp -s "$CX_BOOTSTRAP" "$CX_TOPOLOGY" || fail "locked CX Node topology changed during installation"
cmp -s "$MOTESSH_BOOTSTRAP" "$MOTESSH_TOPOLOGY" || fail "locked MoteSSH topology changed during installation"

umask 027
printf 'CX_NODE_ID=%s\nCX_NODE_MOTE=%s\nCX_CONTROLLER_TARGET=%s\nCX_HEARTBEAT_SECONDS=30\n' \
    "$NODE_ID" "$NODE_MOTE" "$HUB_MMA" >"$temporary_dir/cx-node.env"
install -o root -g cx-node -m 0640 "$temporary_dir/cx-node.env" "$CX_CONFIG"
systemctl daemon-reload
for unit_name in $SYSTEM_UNITS; do
    systemctl enable --now "$unit_name" || unit_failure "$unit_name"
done
doctor
printf 'CX installation complete: node=%s hub=%s; re-run this install command to upgrade\n' \
    "$NODE_ID" "$HUB_MMA"
