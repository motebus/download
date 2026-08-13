#!/bin/sh
set -eu

BASE_URL="https://motebus.github.io/medge-release"
RETIRED_BASE_URL="https://motebus.github.io/medge-deb"
INSTALL_PROFILE="${MEDGE_INSTALL_PROFILE:-medge}"
EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
KEYRING_PATH="/etc/apt/keyrings/medge-archive-keyring.gpg"
SOURCES_PATH="/etc/apt/sources.list.d/medge.sources"
case "$INSTALL_PROFILE" in
medge)
SYSTEM_UNITS="
sphered.service
mbox.service
moted.service
qbix.service
agosd.service
"
STOP_SYSTEM_UNITS="
agosd.service
qbix.service
moted.service
mbox.service
mgated.service
sphered.service
"
APT_PACKAGES="sphered moted aport qbix mbox motessh"
RETIRED_PACKAGES="agos mote mgate ucli qbix-func qbix-wasm moteos"
;;
webos)
SYSTEM_UNITS="
ss-webosd.service
deskd.service
deskd-device.service
"
STOP_SYSTEM_UNITS="
deskd-device.service
deskd.service
ss-webosd.service
"
APT_PACKAGES="desk ss-webos"
RETIRED_PACKAGES=""
;;
*) printf 'MEdge install failed: unknown install profile: %s\n' "$INSTALL_PROFILE" >&2; exit 1 ;;
esac

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

# The GitHub repository rename does not redirect the former Pages origin.
# Migrate only the exact package-owned legacy URI before the first APT refresh;
# the signed canonical source file is downloaded and installed again below.
if [ -f "$SOURCES_PATH" ] &&
    grep -Fqx "URIs: $RETIRED_BASE_URL" "$SOURCES_PATH"; then
    [ "$(grep -c '^URIs:' "$SOURCES_PATH")" -eq 1 ] ||
        fail "the retired MEdge source contains an unexpected additional URI"
    sed -i "s#^URIs: $RETIRED_BASE_URL\$#URIs: $BASE_URL#" "$SOURCES_PATH"
    printf 'Migrated retired MEdge APT source to %s\n' "$BASE_URL"
fi

apt-get update

if [ "$INSTALL_PROFILE" = medge ]; then
    QBIX_DPKG_STATUS="$(
        dpkg-query -W -f='${db:Status-Status}' qbix 2>/dev/null || true
    )"
    QBIX_INSTALLED_VERSION="$(
        dpkg-query -W -f='${Version}' qbix 2>/dev/null || true
    )"
    case "$QBIX_DPKG_STATUS:$QBIX_INSTALLED_VERSION" in
        unpacked:2.0.0-2|half-configured:2.0.0-2|half-installed:2.0.0-2)
            QBIX_CANDIDATE_VERSION="$(
                apt-cache policy qbix |
                    awk '/^[[:space:]]*Candidate:/ { print $2; exit }'
            )"
            [ -n "$QBIX_CANDIDATE_VERSION" ] &&
                [ "$QBIX_CANDIDATE_VERSION" != '(none)' ] &&
                [ "$QBIX_CANDIDATE_VERSION" != '2.0.0-2' ] ||
                fail "Qbix 2.0.0-2 is interrupted and no repaired public package is available"
            QBIX_RECOVERY_DIR="$(mktemp -d /tmp/qbix-recovery.XXXXXX)"
            chmod 0755 "$QBIX_RECOVERY_DIR"
            printf 'Recovering interrupted Qbix 2.0.0-2 with public package %s.\n' \
                "$QBIX_CANDIDATE_VERSION"
            (
                cd "$QBIX_RECOVERY_DIR"
                apt-get download "qbix=$QBIX_CANDIDATE_VERSION"
            ) || fail "could not download the repaired Qbix package"
            QBIX_RECOVERY_DEB="$(
                find "$QBIX_RECOVERY_DIR" -maxdepth 1 -type f -name 'qbix_*.deb' -print
            )"
            [ -n "$QBIX_RECOVERY_DEB" ] &&
                [ "$(printf '%s\n' "$QBIX_RECOVERY_DEB" | wc -l)" -eq 1 ] ||
                fail "the Qbix recovery download is ambiguous"
            [ "$(dpkg-deb -f "$QBIX_RECOVERY_DEB" Package)" = qbix ] &&
                [ "$(dpkg-deb -f "$QBIX_RECOVERY_DEB" Version)" = "$QBIX_CANDIDATE_VERSION" ] &&
                [ "$(dpkg-deb -f "$QBIX_RECOVERY_DEB" Architecture)" = amd64 ] ||
                fail "the downloaded Qbix recovery package is invalid"
            dpkg --install "$QBIX_RECOVERY_DEB" ||
                fail "the repaired Qbix package could not be installed"
            rm -f "$QBIX_RECOVERY_DEB"
            rmdir "$QBIX_RECOVERY_DIR"
            ;;
    esac

    MEDGE_DPKG_STATUS="$(
        dpkg-query -W -f='${db:Status-Status}' medge 2>/dev/null || true
    )"
    case "$MEDGE_DPKG_STATUS" in
        installed|unpacked|half-configured|half-installed|triggers-awaited|triggers-pending)
            for maintainer_script in preinst postinst prerm postrm config; do
                [ ! -e "/var/lib/dpkg/info/medge.$maintainer_script" ] ||
                    fail "refusing to remove a medge package that contains maintainer scripts"
            done
            printf '%s\n' \
                'Removing the stale dependency-only MEdge meta-package; installed components are preserved.'
            dpkg --remove medge ||
                fail "the stale dependency-only MEdge meta-package could not be removed"
            ;;
        ''|config-files|not-installed) ;;
        *) fail "unsupported installed state for the retired MEdge meta-package: $MEDGE_DPKG_STATUS" ;;
    esac
    INSTALLED_RETIRED=""
    for retired_package in $RETIRED_PACKAGES; do
        retired_status="$(
            dpkg-query -W -f='${db:Status-Status}' "$retired_package" \
                2>/dev/null || true
        )"
        case "$retired_status" in
            installed|unpacked|half-configured|half-installed|triggers-awaited|triggers-pending)
                INSTALLED_RETIRED="$INSTALLED_RETIRED $retired_package"
                ;;
            ''|config-files|not-installed) ;;
            *) fail "unsupported installed state for retired package $retired_package: $retired_status" ;;
        esac
    done
    if [ -n "$INSTALLED_RETIRED" ]; then
        printf 'Removing retired MEdge packages (configuration and data are preserved):%s\n' \
            "$INSTALLED_RETIRED"
        # Intentionally omit purge and autoremove: only the explicit retired
        # package set and any direct dependency-only blockers may be removed.
        apt-get remove -y --no-auto-remove $INSTALLED_RETIRED ||
            fail "retired MEdge packages could not be removed"
    fi
    apt-get check ||
        fail "APT has broken dependencies after stale MEdge meta-package recovery; repair them before retrying"
else
    apt-get check ||
        fail "APT has broken dependencies; repair them before retrying"
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

# A newly published GitHub Pages repository can briefly share an intermediary
# cache entry with the preceding release.  Force revalidation after installing
# the canonical source so APT does not resolve against a stale Packages index.
apt-get -o Acquire::http::No-Cache=true update

APT_INSTALL_PLAN="$(apt-get --print-uris -y install $APT_PACKAGES)" ||
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

apt-get install -y $APT_PACKAGES

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

if [ "$INSTALL_PROFILE" = webos ]; then
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

fi

INSTALLED_VERSIONS="$(dpkg-query -W -f='${Package}=${Version}\n' $APT_PACKAGES)"
printf '%s profile installed and running successfully from %s:\n%s\n' \
    "$INSTALL_PROFILE" "$BASE_URL" "$INSTALLED_VERSIONS"
