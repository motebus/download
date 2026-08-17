#!/bin/sh
set -eu

BASE_URL="https://motebus.github.io/medge-release"
EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
REQUIRED_PACKAGES="sphered moted motestream motessh openssh-client openssh-server cx-node"
ACTION="install"
NODE_ID=""
NODE_MOTE=""
HUB_MMA=""
BOOTSTRAP=""

fail() { printf 'CX Install failed: %s\n' "$*" >&2; exit 1; }
usage() {
    printf '%s\n' \
        "Usage:" \
        "  sudo sh cx-install.sh install --node-id CX<number> --node-mote <name.mote> --hub-mma <mma> --bootstrap <absolute-file>" \
        "  sudo sh cx-install.sh doctor" \
        "  sudo sh cx-install.sh upgrade" \
        "  sudo sh cx-install.sh uninstall"
}

case "${1:-}" in
    install|doctor|upgrade|uninstall) ACTION=$1; shift ;;
    --help|-h) usage; exit 0 ;;
esac

while [ "$#" -gt 0 ]; do
    case "$1" in
        --node-id) [ "$#" -ge 2 ] || fail "--node-id requires a value"; NODE_ID=$2; shift 2 ;;
        --node-mote) [ "$#" -ge 2 ] || fail "--node-mote requires a value"; NODE_MOTE=$2; shift 2 ;;
        --hub-mma) [ "$#" -ge 2 ] || fail "--hub-mma requires a value"; HUB_MMA=$2; shift 2 ;;
        --bootstrap) [ "$#" -ge 2 ] || fail "--bootstrap requires a value"; BOOTSTRAP=$2; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

require_root() {
    [ "$(id -u)" -eq 0 ] || fail "run as root"
}

check_platform() {
    [ -r /etc/os-release ] || fail "cannot identify operating system"
    . /etc/os-release
    case "${ID:-}:${VERSION_ID:-}" in
        debian:12|debian:13|ubuntu:24.04|ubuntu:26.04) ;;
        *) fail "Debian 12/13 or Ubuntu 24.04/26.04 is required" ;;
    esac
    [ "$(dpkg --print-architecture)" = amd64 ] || fail "amd64 is required"
    [ -d /run/systemd/system ] || fail "systemd must be running"
}

validate_topology() {
    topology=$1
    [ -f "$topology" ] && [ ! -L "$topology" ] || fail "topology must be a regular non-symlink file"
    awk -F= '
      /^[[:space:]]*($|#)/ { next }
      {
        key=$1; value=substr($0,index($0,"=")+1)
        if ($0 !~ /=/ || key !~ /^MCHAT_(APPNAME|EINAME|DC|IOC|MBGWIP|WATCHLEVEL)$/ || value=="" || ++seen[key]>1) bad=1
      }
      END {
        if (!seen["MCHAT_APPNAME"] || !seen["MCHAT_DC"] || !seen["MCHAT_IOC"] || !seen["MCHAT_MBGWIP"] || !seen["MCHAT_WATCHLEVEL"] || bad) exit 1
      }
    ' "$topology" || fail "topology must contain only the complete canonical MCHAT_* set"
}

validate_install_input() {
    printf '%s' "$NODE_ID" | grep -Eq '^CX[1-9][0-9]*$' || fail "node identity must be CX<number>"
    printf '%s' "$NODE_MOTE" | grep -Eq '^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+mote$' || fail "node mote must be an approved *.mote identity"
    printf '%s' "$HUB_MMA" | grep -Eq '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$' || fail "Hub MMA must have three explicit segments"
    case "$BOOTSTRAP" in /*) ;; *) fail "bootstrap path must be absolute" ;; esac
    validate_topology "$BOOTSTRAP"
}

prepare_signed_apt() {
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
}

install_packages() {
    install_plan=$(apt-get --print-uris -y install $REQUIRED_PACKAGES)
    printf '%s\n' "$install_plan" | grep -Eqi 'gitlab\.' && fail "APT transaction contains a forbidden GitLab URL"
    apt-get install -y $REQUIRED_PACKAGES
}

configure_node() {
    install -d -o root -g cx-node -m 0750 /etc/mote/cx-node
    target=/etc/mote/cx-node/cx-node-mchat.env
    if [ -e "$target" ]; then
        [ -f "$target" ] && [ ! -L "$target" ] || fail "locked topology target must be a regular non-symlink file"
        cmp -s "$BOOTSTRAP" "$target" || fail "locked topology already exists with different bytes"
    else
        install -o root -g cx-node -m 0640 "$BOOTSTRAP" "$target"
    fi

    config_tmp=$(mktemp /etc/mote/cx-node/cx-node.env.XXXXXX)
    umask 027
    printf 'CX_NODE_ID=%s\nCX_NODE_MOTE=%s\nCX_CONTROLLER_TARGET=%s\nCX_HEARTBEAT_SECONDS=30\n' \
        "$NODE_ID" "$NODE_MOTE" "$HUB_MMA" >"$config_tmp"
    chown root:cx-node "$config_tmp"
    chmod 0640 "$config_tmp"
    if [ -e /etc/mote/cx-node/cx-node.env ]; then
        [ -f /etc/mote/cx-node/cx-node.env ] && [ ! -L /etc/mote/cx-node/cx-node.env ] || fail "node config must be a regular non-symlink file"
        if cmp -s "$config_tmp" /etc/mote/cx-node/cx-node.env; then
            rm -f "$config_tmp"
        else
            rm -f "$config_tmp"
            fail "existing node configuration differs; re-admission is not an installer upgrade"
        fi
    else
        mv "$config_tmp" /etc/mote/cx-node/cx-node.env
    fi
}

doctor() {
    failed=0
    for package in $REQUIRED_PACKAGES; do
        if [ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" = "install ok installed" ]; then
            printf 'PASS package %s\n' "$package"
        else
            printf 'FAIL package %s is not installed\n' "$package" >&2
            failed=1
        fi
    done
    for command_name in cx-node motessh ssh sshd; do
        if command -v "$command_name" >/dev/null 2>&1; then
            printf 'PASS command %s\n' "$command_name"
        else
            printf 'FAIL command %s is missing\n' "$command_name" >&2
            failed=1
        fi
    done
    if validate_topology /etc/mote/cx-node/cx-node-mchat.env; then
        printf 'PASS locked topology\n'
    else
        failed=1
    fi
    if [ -f /etc/mote/cx-node/cx-node.env ] && [ ! -L /etc/mote/cx-node/cx-node.env ] && \
       grep -Eq '^CX_NODE_ID=CX[1-9][0-9]*$' /etc/mote/cx-node/cx-node.env && \
       grep -Eq '^CX_NODE_MOTE=([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+mote$' /etc/mote/cx-node/cx-node.env && \
       grep -Eq '^CX_CONTROLLER_TARGET=[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$' /etc/mote/cx-node/cx-node.env; then
        printf 'PASS node configuration\n'
    else
        printf 'FAIL node configuration is missing or invalid\n' >&2
        failed=1
    fi
    if sshd -t; then printf 'PASS OpenSSH configuration\n'; else failed=1; fi
    if systemctl is-enabled --quiet cx-node.service && systemctl is-active --quiet cx-node.service; then
        printf 'PASS cx-node.service enabled and active\n'
    else
        printf 'FAIL cx-node.service is not enabled and active\n' >&2
        failed=1
    fi
    printf '%s\n' "INFO MoteSSH | Mote 安全连接 performs discovery, short-lived authorization, and MoteBus/SSH channel handoff."
    printf '%s\n' "INFO Continuous CX control uses MoteBus; standard OpenSSH owns execution, authentication, host-key verification, and encryption."
    printf '%s\n' "INFO Local doctor does not admit the node; CX Hub enrollment and approved SSH trust must independently reach ACTIVE."
    [ "$failed" -eq 0 ] || fail "doctor found one or more failures"
    printf 'CX Doctor complete: healthy\n'
}

require_root
check_platform

case "$ACTION" in
    install)
        validate_install_input
        prepare_signed_apt
        install_packages
        configure_node
        systemctl daemon-reload
        systemctl enable --now cx-node.service
        doctor
        printf 'CX Install complete: node=%s hub=%s\n' "$NODE_ID" "$HUB_MMA"
        ;;
    doctor)
        [ "$#" -eq 0 ] || fail "doctor accepts no admission arguments"
        doctor
        ;;
    upgrade)
        [ "$#" -eq 0 ] || fail "upgrade accepts no admission arguments"
        [ -f /etc/mote/cx-node/cx-node.env ] || fail "install CX Node before upgrade"
        validate_topology /etc/mote/cx-node/cx-node-mchat.env
        prepare_signed_apt
        install_packages
        systemctl daemon-reload
        systemctl enable --now cx-node.service
        doctor
        printf 'CX Upgrade complete\n'
        ;;
    uninstall)
        [ "$#" -eq 0 ] || fail "uninstall accepts no admission arguments"
        systemctl disable --now cx-node.service 2>/dev/null || true
        apt-get remove -y cx-node
        printf '%s\n' "CX Uninstall complete: node configuration, locked topology, signed APT trust, MoteSSH, and OpenSSH were preserved."
        printf '%s\n' "Re-run install with identical admission data to restore this node; shared transport/security packages are never auto-removed."
        ;;
esac
