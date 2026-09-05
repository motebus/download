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

for command_name in apt-get awk chmod cmp curl dpkg dpkg-query gpg gpgv install mktemp python3; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done

# A local override is a pair; never mix local and downloaded release evidence.
if [[ -n "${MEDGE_RELEASE_MANIFEST:-}" || -n "${MEDGE_RELEASE_MANIFEST_SIGNATURE:-}" ]]; then
    [[ -n "${MEDGE_RELEASE_MANIFEST:-}" && -n "${MEDGE_RELEASE_MANIFEST_SIGNATURE:-}" ]] ||
        fail "set both MEDGE_RELEASE_MANIFEST and MEDGE_RELEASE_MANIFEST_SIGNATURE"
fi

readonly ORIGINAL_UMASK="$(umask)"
umask 077
TEMP_DIR="$(mktemp -d "/tmp/${PROFILE_NAME}-uninstall.XXXXXX")"
readonly TEMP_DIR
cleanup() {
    python3 - "$TEMP_DIR" "$PROFILE_NAME-uninstall" <<'PY'
import os
from pathlib import Path
import shutil
import sys

path = Path(sys.argv[1])
if (path.parent != Path("/tmp") or not path.name.startswith(sys.argv[2] + ".")
        or path.is_symlink() or path.stat().st_uid != os.geteuid()):
    raise SystemExit("refusing cleanup outside the owned installer temporary directory")
shutil.rmtree(path)
PY
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

install -d -m 0700 "$TEMP_DIR/verified"
readonly MANIFEST_PATH="$TEMP_DIR/verified/release-manifest.json"
readonly MANIFEST_SIGNATURE_PATH="$TEMP_DIR/verified/release-manifest.json.asc"
if [[ -n "${MEDGE_RELEASE_MANIFEST:-}" ]]; then
    [[ -f "$MEDGE_RELEASE_MANIFEST" && -r "$MEDGE_RELEASE_MANIFEST" ]] ||
        fail "the explicit release manifest must be a readable regular file"
    [[ -f "$MEDGE_RELEASE_MANIFEST_SIGNATURE" && -r "$MEDGE_RELEASE_MANIFEST_SIGNATURE" ]] ||
        fail "the explicit manifest signature must be a readable regular file"
    install -m 0400 -- "$MEDGE_RELEASE_MANIFEST" "$MANIFEST_PATH"
    install -m 0400 -- "$MEDGE_RELEASE_MANIFEST_SIGNATURE" "$MANIFEST_SIGNATURE_PATH"
else
    curl --proto '=https' --tlsv1.2 -fsSLo \
        "$MANIFEST_PATH" "$BASE_URL/release-manifest.json" ||
        fail "approved Sphere release is not published at $BASE_URL"
    curl --proto '=https' --tlsv1.2 -fsSLo \
        "$MANIFEST_SIGNATURE_PATH" "$BASE_URL/release-manifest.json.asc" ||
        fail "approved Sphere manifest signature is not published at $BASE_URL"
fi
chmod 0400 "$MANIFEST_PATH" "$MANIFEST_SIGNATURE_PATH"

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

# Parse only the authenticated private snapshot.
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
    umask "$ORIGINAL_UMASK"
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
