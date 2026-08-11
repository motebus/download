#!/bin/sh
set -eu

BASE_URL="https://motebus.github.io/medge-deb"
EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
KEYRING_PATH="/etc/apt/keyrings/medge-archive-keyring.gpg"
SOURCES_PATH="/etc/apt/sources.list.d/medge.sources"
SYSTEM_UNITS="
sphered.service
mgated.service
ss-webosd.service
moted.service
qbix.service
agosd.service
deskd.service
deskd-device.service
"
STOP_SYSTEM_UNITS="
deskd-device.service
deskd.service
agosd.service
qbix.service
moted.service
ss-webosd.service
mgated.service
sphered.service
"
DESKTOP_UNITS="
deskd-session.service
ss-webos-session.service
"
SERVICE_STABILITY_SECONDS=30

fail() {
    printf 'MEdge install failed: %s\n' "$*" >&2
    exit 1
}

system_unit_failed() {
    failed_unit="$1"
    printf '\n%s\n' "Status for failed unit $failed_unit:" >&2
    systemctl --no-pager --full status "$failed_unit" >&2 || true
    printf '\n%s\n' "Recent journal for $failed_unit:" >&2
    journalctl --no-pager -n 50 -u "$failed_unit" >&2 || true
    systemctl disable "$failed_unit" >/dev/null 2>&1 || true
    systemctl stop "$failed_unit" >/dev/null 2>&1 || true
    systemctl reset-failed "$failed_unit" >/dev/null 2>&1 || true
    fail "$failed_unit did not become healthy; it was stopped, disabled, and reset to prevent a restart loop"
}

[ "$(id -u)" -eq 0 ] ||
    fail "run this installer as root (for example: sudo sh /tmp/medge-install.sh)"

[ -r /etc/os-release ] || fail "cannot identify the operating system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:24.04|ubuntu:26.04) ;;
    *) fail "Ubuntu 24.04 or 26.04 is required" ;;
esac

command -v dpkg >/dev/null 2>&1 || fail "dpkg is unavailable"
[ "$(dpkg --print-architecture)" = "amd64" ] ||
    fail "amd64 architecture is required"
[ -d /run/systemd/system ] ||
    fail "systemd must be running to start the MEdge services"
command -v systemctl >/dev/null 2>&1 ||
    fail "required runtime command is unavailable: systemctl"

export DEBIAN_FRONTEND=noninteractive
apt-get update

if ! apt-get check; then
    MEDGE_DPKG_STATUS="$(
        dpkg-query -W -f='${db:Status-Status}' medge 2>/dev/null || true
    )"
    case "$MEDGE_DPKG_STATUS" in
        installed|unpacked|half-configured|half-installed|triggers-awaited|triggers-pending) ;;
        *)
            fail "APT has broken dependencies unrelated to an installed MEdge meta-package; repair them before retrying"
            ;;
    esac
    for maintainer_script in preinst postinst prerm postrm config; do
        [ ! -e "/var/lib/dpkg/info/medge.$maintainer_script" ] ||
            fail "refusing to remove a medge package that contains maintainer scripts"
    done
    printf '%s\n' \
        'Removing the stale dependency-only MEdge meta-package; installed components are preserved.'
    dpkg --remove medge ||
        fail "the stale dependency-only MEdge meta-package could not be removed"
    apt-get check ||
        fail "APT remains broken after removing the stale MEdge meta-package"
fi

apt-get install -y --no-install-recommends ca-certificates curl gnupg

TEMP_DIR="$(mktemp -d /tmp/medge-install.XXXXXX)"
cleanup() {
    rm -f \
        "$TEMP_DIR/medge-archive-keyring.gpg" \
        "$TEMP_DIR/medge.sources" \
        "$TEMP_DIR/expected.sources" \
        "$TEMP_DIR/service-restarts"
    rmdir "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

curl --proto '=https' --tlsv1.2 -fsSLo \
    "$TEMP_DIR/medge-archive-keyring.gpg" \
    "$BASE_URL/medge-archive-keyring.gpg"
curl --proto '=https' --tlsv1.2 -fsSLo \
    "$TEMP_DIR/medge.sources" \
    "$BASE_URL/medge.sources"

ACTUAL_FINGERPRINT="$(
    gpg --batch --show-keys --with-colons \
        "$TEMP_DIR/medge-archive-keyring.gpg" |
        awk -F: '
            $1 == "pub" { public_keys += 1 }
            $1 == "fpr" && fingerprint == "" { fingerprint = $10 }
            END {
                if (public_keys != 1 || fingerprint == "") {
                    exit 1
                }
                print fingerprint
            }
        '
)" || fail "the downloaded archive key is invalid"
[ "$ACTUAL_FINGERPRINT" = "$EXPECTED_FINGERPRINT" ] ||
    fail "archive-key fingerprint mismatch (received $ACTUAL_FINGERPRINT)"

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

apt-get update

APT_INSTALL_PLAN="$(apt-get --print-uris -y install medge)" ||
    fail "cannot resolve the MEdge APT transaction"
if printf '%s\n' "$APT_INSTALL_PLAN" |
    grep -Eiq "(https?|ssh|git)://[^[:space:]\"']*gitlab[.]"; then
    fail "the MEdge APT transaction contains a forbidden GitLab URL"
fi

systemctl daemon-reload
for unit in $STOP_SYSTEM_UNITS; do
    systemctl disable "$unit" >/dev/null 2>&1 || true
    systemctl stop "$unit" >/dev/null 2>&1 || true
    systemctl reset-failed "$unit" 2>/dev/null || true
done

apt-get install -y medge

for command_name in awk getent loginctl runuser systemctl; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required runtime command is unavailable: $command_name"
done

systemctl daemon-reload
for unit in $SYSTEM_UNITS; do
    systemctl reset-failed "$unit" 2>/dev/null || true
    systemctl enable "$unit" ||
        system_unit_failed "$unit"
    systemctl start "$unit" ||
        system_unit_failed "$unit"
    systemctl is-active --quiet "$unit" ||
        system_unit_failed "$unit"
done

: >"$TEMP_DIR/service-restarts"
for unit in $SYSTEM_UNITS; do
    restart_count="$(systemctl show "$unit" -p NRestarts --value)" ||
        system_unit_failed "$unit"
    case "$restart_count" in
        ''|*[!0-9]*) system_unit_failed "$unit" ;;
    esac
    printf '%s %s\n' "$unit" "$restart_count" >>"$TEMP_DIR/service-restarts"
done

printf 'Verifying MEdge service stability for %s seconds...\n' \
    "$SERVICE_STABILITY_SECONDS"
sleep "$SERVICE_STABILITY_SECONDS"
for unit in $SYSTEM_UNITS; do
    systemctl is-active --quiet "$unit" ||
        system_unit_failed "$unit"
done
while read -r unit before_restarts; do
    after_restarts="$(systemctl show "$unit" -p NRestarts --value)" ||
        system_unit_failed "$unit"
    [ "$after_restarts" = "$before_restarts" ] || {
        printf '%s restarted during the stability window: before=%s after=%s\n' \
            "$unit" "$before_restarts" "$after_restarts" >&2
        system_unit_failed "$unit"
    }
done <"$TEMP_DIR/service-restarts"

DESKTOP_SESSION=""
DESKTOP_USER=""
for session_id in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
    [ "$(loginctl show-session "$session_id" -p Active --value)" = "yes" ] ||
        continue
    [ "$(loginctl show-session "$session_id" -p Remote --value)" = "no" ] ||
        continue
    session_type="$(
        loginctl show-session "$session_id" -p Type --value
    )"
    [ "$session_type" = "wayland" ] || [ "$session_type" = "x11" ] ||
        continue
    session_user="$(
        loginctl show-session "$session_id" -p Name --value
    )"
    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] &&
        [ "$session_user" != "$SUDO_USER" ]; then
        continue
    fi
    [ -z "$DESKTOP_SESSION" ] ||
        fail "more than one active local graphical session is eligible"
    DESKTOP_SESSION="$session_id"
    DESKTOP_USER="$session_user"
done

if [ -n "$DESKTOP_SESSION" ]; then
    DESKTOP_UID="$(id -u "$DESKTOP_USER")"
    DESKTOP_HOME="$(
        getent passwd "$DESKTOP_USER" | awk -F: '{print $6}'
    )"
    [ -n "$DESKTOP_HOME" ] ||
        fail "home directory is unavailable for $DESKTOP_USER"
    user_systemctl() {
        runuser -u "$DESKTOP_USER" -- env \
            "HOME=$DESKTOP_HOME" \
            "XDG_RUNTIME_DIR=/run/user/$DESKTOP_UID" \
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$DESKTOP_UID/bus" \
            systemctl --user "$@"
    }
    user_systemctl daemon-reload
    runuser -u "$DESKTOP_USER" -- env \
        "HOME=$DESKTOP_HOME" \
        "XDG_RUNTIME_DIR=/run/user/$DESKTOP_UID" \
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$DESKTOP_UID/bus" \
        /usr/libexec/ss-webos/install-desktop-shortcut ||
        fail "SmartScreen desktop shortcut could not be installed for $DESKTOP_USER"
    for unit in $DESKTOP_UNITS; do
        user_systemctl reset-failed "$unit" 2>/dev/null || true
        user_systemctl restart "$unit" ||
            fail "$unit did not start for graphical user $DESKTOP_USER"
    done
    sleep 2
    for unit in $DESKTOP_UNITS; do
        user_systemctl is-active --quiet "$unit" ||
            fail "$unit is not active for graphical user $DESKTOP_USER"
    done
    printf 'MEdge desktop helpers are running for %s (session %s)\n' \
        "$DESKTOP_USER" "$DESKTOP_SESSION"
else
    printf '%s\n' \
        'No active local graphical session; the SmartScreen shortcut and desktop helpers will start at login.'
fi

INSTALLED_VERSION="$(dpkg-query -W -f='${Version}' medge)"
printf 'MEdge %s installed and running successfully from %s\n' \
    "$INSTALLED_VERSION" "$BASE_URL"
