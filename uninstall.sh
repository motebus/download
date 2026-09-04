#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE_NAME="sphere"
readonly BASE_URL="https://motebus.github.io/download"
readonly EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
readonly KEYRING_PATH="/etc/apt/keyrings/medge-archive-keyring.gpg"
readonly SOURCES_PATH="/etc/apt/sources.list.d/medge.sources"
readonly SSH_PROFILE_PATH="/etc/ssh/ssh_config.d/50-mote-proxy.conf"

fail() {
    printf '%s uninstall failed: %s\n' "$PROFILE_NAME" "$*" >&2
    exit 1
}

[[ "$#" -eq 0 ]] || fail "this uninstaller accepts no arguments"
[[ "$(id -u)" -eq 0 ]] || fail "run this uninstaller as root"
[[ -r /etc/os-release ]] || fail "cannot identify the operating system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:24.04|ubuntu:26.04) ;;
    *) fail "Ubuntu 24.04 or 26.04 is required" ;;
esac
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail "amd64 is required"

for command_name in apt-get awk cmp curl dpkg dpkg-query gpg gpgv python3; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done

TEMP_DIR="$(mktemp -d "/tmp/${PROFILE_NAME}-uninstall.XXXXXX")"
cleanup() {
    rm -f "$TEMP_DIR/medge-archive-keyring.gpg" \
        "$TEMP_DIR/medge.sources" \
        "$TEMP_DIR/package-plan" \
        "$TEMP_DIR/purge-plan" \
        "$TEMP_DIR/mote-proxy-ssh-profile" \
        "$TEMP_DIR/release-manifest.json" \
        "$TEMP_DIR/release-manifest.json.asc"
    rmdir "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

SCRIPT_SOURCE="${BASH_SOURCE[0]-}"
FETCH_RELEASE_MANIFEST=0
if [[ -n "${MEDGE_RELEASE_MANIFEST:-}" ]]; then
    manifest_path="$MEDGE_RELEASE_MANIFEST"
else
    manifest_path="$TEMP_DIR/release-manifest.json"
    FETCH_RELEASE_MANIFEST=1
fi
manifest_signature_path="${MEDGE_RELEASE_MANIFEST_SIGNATURE:-${manifest_path}.asc}"
readonly MANIFEST_PATH="$manifest_path"
readonly MANIFEST_SIGNATURE_PATH="$manifest_signature_path"

if [[ "$FETCH_RELEASE_MANIFEST" -eq 1 ]]; then
    curl --proto '=https' --tlsv1.2 -fsSLo \
        "$MANIFEST_PATH" "$BASE_URL/release-manifest.json" ||
        fail "approved Sphere release is not published at $BASE_URL"
    if [[ -z "${MEDGE_RELEASE_MANIFEST_SIGNATURE:-}" ]]; then
        curl --proto '=https' --tlsv1.2 -fsSLo \
            "$MANIFEST_SIGNATURE_PATH" "$BASE_URL/release-manifest.json.asc" ||
            fail "approved Sphere manifest signature is not published at $BASE_URL"
    fi
fi

[[ -r "$MANIFEST_PATH" ]] ||
    fail "approved release-manifest.json is required beside the uninstaller"
[[ -r "$MANIFEST_SIGNATURE_PATH" ]] ||
    fail "release-manifest.json.asc is required beside the approved manifest"

python3 - "$MANIFEST_PATH" >"$TEMP_DIR/package-plan" <<'PY'
import json
import re
import sys

expected = (
    "sphere",
    "moted",
    "medge",
    "mlink",
    "mdesk",
    "ss-webos",
    "mote-proxy",
    "mote-secd",
    "mote-bridge-mcp",
    "ultra-mcp-ssh",
    "mcp-run",
    "cx-node",
    "mote-sync",
    "mote-syncd",
    "mote-chatd",
    "uchat",
    "codex-mesh",
)
expected_installers = ("sphere.sh", "webdesk.sh", "sshkit.sh", "uninstall.sh")
hex64_re = re.compile(r"^[0-9a-f]{64}$")
with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
if manifest.get("schema") != "medge-public-release/v17":
    raise SystemExit("release manifest schema is not medge-public-release/v17")
if manifest.get("status") != "approved":
    raise SystemExit("release manifest is not approved")
if (
    manifest.get("suite") != "stable"
    or manifest.get("component") != "main"
    or manifest.get("architecture") != "amd64"
):
    raise SystemExit("release manifest distribution boundary is invalid")
packages = manifest.get("packages")
if not isinstance(packages, list) or tuple(item.get("name") for item in packages) != expected:
    raise SystemExit("release manifest package set or dependency order is invalid")
installers = manifest.get("installers")
if not isinstance(installers, list) or tuple(item.get("name") for item in installers) != expected_installers:
    raise SystemExit("release manifest uninstaller boundary is invalid")
if any(not isinstance(item.get("sha256"), str) or hex64_re.fullmatch(item["sha256"]) is None for item in installers):
    raise SystemExit("release manifest installer digest is invalid")
for name in expected:
    print(name)
PY

mapfile -t APPROVED_PACKAGES <"$TEMP_DIR/package-plan"
[[ "${#APPROVED_PACKAGES[@]}" -eq 17 ]] ||
    fail "release manifest package boundary is incomplete"

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
[[ "$ACTUAL_FINGERPRINT" == "$EXPECTED_FINGERPRINT" ]] ||
    fail "archive-key fingerprint mismatch"
gpgv --keyring "$TEMP_DIR/medge-archive-keyring.gpg" \
    "$MANIFEST_SIGNATURE_PATH" "$MANIFEST_PATH" >/dev/null 2>&1 ||
    fail "release-manifest signature verification failed"

if [[ -e "$KEYRING_PATH" ]]; then
    [[ -f "$KEYRING_PATH" ]] || fail "Sphere archive-key path is not a regular file"
    cmp -s "$KEYRING_PATH" "$TEMP_DIR/medge-archive-keyring.gpg" ||
        fail "installed Sphere archive key differs from the approved release key"
fi
if [[ -e "$SOURCES_PATH" ]]; then
    [[ -f "$SOURCES_PATH" ]] || fail "Sphere source path is not a regular file"
    cmp -s "$SOURCES_PATH" "$TEMP_DIR/medge.sources" ||
        fail "installed Sphere source differs from the approved release source"
fi

PURGE_ARGS=()
for package_name in "${APPROVED_PACKAGES[@]}"; do
    package_state="$(
        dpkg-query -W -f='${db:Status-Status}' "$package_name" 2>/dev/null || true
    )"
    case "$package_state" in
        installed|config-files) PURGE_ARGS+=("$package_name") ;;
        "") ;;
        *)
            fail "$package_name is in unsupported dpkg state: $package_state"
            ;;
    esac
done

if [[ "${#PURGE_ARGS[@]}" -gt 0 ]]; then
    LC_ALL=C apt-get --simulate purge "${PURGE_ARGS[@]}" >"$TEMP_DIR/purge-plan" ||
        fail "cannot resolve the approved Sphere purge transaction"
    python3 - "$TEMP_DIR/purge-plan" "${APPROVED_PACKAGES[@]}" <<'PY'
import sys

plan_path, *approved_names = sys.argv[1:]
approved = set(approved_names)
scheduled = set()
with open(plan_path, encoding="utf-8") as handle:
    for line in handle:
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "Inst":
            raise SystemExit("purge plan unexpectedly installs a package")
        if fields[0] not in {"Remv", "Purg"}:
            continue
        name = fields[1].split(":", 1)[0]
        scheduled.add(name)
outside = sorted(scheduled - approved)
if outside:
    raise SystemExit("purge plan would remove packages outside Sphere: " + ", ".join(outside))
PY

    export DEBIAN_FRONTEND=noninteractive
    LC_ALL=C apt-get purge -y "${PURGE_ARGS[@]}"
fi

for package_name in "${APPROVED_PACKAGES[@]}"; do
    package_state="$(
        dpkg-query -W -f='${db:Status-Status}' "$package_name" 2>/dev/null || true
    )"
    case "$package_state" in
        installed|config-files) fail "$package_name remains installed or configured after purge" ;;
    esac
done

remove_managed_ssh_proxy_profile() {
    [[ ! -e "$SSH_PROFILE_PATH" && ! -L "$SSH_PROFILE_PATH" ]] && return 0
    [[ -f "$SSH_PROFILE_PATH" && ! -L "$SSH_PROFILE_PATH" ]] ||
        fail "package-owned SSH proxy profile is not a regular file"

    printf '%s\n' \
        'Host *.mote' \
        '    ProxyCommand /usr/libexec/mote-proxy/ssh-proxy %h %p' \
        >"$TEMP_DIR/mote-proxy-ssh-profile"
    cmp -s "$SSH_PROFILE_PATH" "$TEMP_DIR/mote-proxy-ssh-profile" ||
        fail "package-owned SSH proxy profile was modified; refusing removal"

    rm -f -- "$SSH_PROFILE_PATH"
    [[ ! -e "$SSH_PROFILE_PATH" ]] ||
        fail "package-owned SSH proxy profile remains after cleanup"
}

remove_managed_ssh_proxy_profile

[[ ! -e "$SOURCES_PATH" ]] || rm -f -- "$SOURCES_PATH"
[[ ! -e "$KEYRING_PATH" ]] || rm -f -- "$KEYRING_PATH"

printf '%s\n' \
    "Sphere approved packages, SSH proxy profile, and installer-managed APT registration were removed"
printf '%s\n' \
    "User data, SSH identities, unrelated packages, and non-Sphere services were preserved"
