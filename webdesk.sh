#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE_NAME="webdesk"
readonly BASE_URL="https://motebus.github.io/medge-release"
readonly EXPECTED_FINGERPRINT="AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
readonly KEYRING_PATH="/etc/apt/keyrings/medge-archive-keyring.gpg"
readonly SOURCES_PATH="/etc/apt/sources.list.d/medge.sources"

fail() {
    printf '%s install failed: %s\n' "$PROFILE_NAME" "$*" >&2
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail "run this installer as root"
[[ -r /etc/os-release ]] || fail "cannot identify the operating system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:24.04|ubuntu:26.04) ;;
    *) fail "Ubuntu 24.04 or 26.04 is required" ;;
esac
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail "amd64 is required"

for command_name in apt-cache apt-get awk cmp curl dpkg dpkg-query gpg gpgv install python3; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done

TEMP_DIR="$(mktemp -d "/tmp/${PROFILE_NAME}-install.XXXXXX")"
cleanup() {
    rm -f "$TEMP_DIR/medge-archive-keyring.gpg" \
        "$TEMP_DIR/medge.sources" \
        "$TEMP_DIR/expected.sources" \
        "$TEMP_DIR/package-plan" \
        "$TEMP_DIR/release-manifest.json" \
        "$TEMP_DIR/release-manifest.json.asc"
    rmdir "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

SCRIPT_SOURCE="${BASH_SOURCE[0]-}"
FETCH_RELEASE_MANIFEST=0
if [[ -n "${MEDGE_RELEASE_MANIFEST:-}" ]]; then
    manifest_path="$MEDGE_RELEASE_MANIFEST"
elif [[ -n "$SCRIPT_SOURCE" ]]; then
    script_dir="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
    manifest_path="$script_dir/release-manifest.json"
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
    fail "approved release-manifest.json is required beside the installer"
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
    "motemcp",
    "ultra-mcp-ssh",
    "mcp-run",
    "cx-pivot",
    "mote-sync",
    "mote-syncd",
)
selected = (
    "sphere",
    "mlink",
    "mdesk",
    "ss-webos",
)
version_re = re.compile(r"^[0-9][0-9A-Za-z.+:~]*-[0-9]+$")
with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
if manifest.get("schema") != "medge-public-release/v10":
    raise SystemExit("release manifest schema is not medge-public-release/v10")
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
for item in packages:
    name = item["name"]
    version = item.get("version")
    architecture = item.get("architecture")
    asset = item.get("asset")
    if not isinstance(version, str) or version_re.fullmatch(version) is None:
        raise SystemExit(f"{name}: invalid Debian version")
    if architecture not in {"amd64", "all"}:
        raise SystemExit(f"{name}: invalid Debian architecture")
    if asset != f"{name}_{version}_{architecture}.deb":
        raise SystemExit(f"{name}: invalid release asset identity")
    if name in selected:
        print(f"{name}\t{version}\t{asset}")
PY

mapfile -t PACKAGE_RECORDS <"$TEMP_DIR/package-plan"
[[ "${#PACKAGE_RECORDS[@]}" -eq 4 ]] || fail "release manifest package plan is incomplete for $PROFILE_NAME"

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

PACKAGE_ARGS=()
for record in "${PACKAGE_RECORDS[@]}"; do
    IFS=$'\t' read -r package_name package_version package_asset <<<"$record"
    apt-cache madison "$package_name" |
        awk -F'|' -v version="$package_version" -v base="$BASE_URL" '
            $2 ~ "^[[:space:]]*" version "[[:space:]]*$" && index($3, base) { found = 1 }
            END { exit(found ? 0 : 1) }
        ' || fail "$package_name=$package_version is absent from the signed Sphere source"
    PACKAGE_ARGS+=("$package_name=$package_version")
    [[ "$package_asset" == "${package_name}_${package_version}_"*.deb ]] ||
        fail "$package_name release asset does not match its pinned version"
done

APT_INSTALL_PLAN="$(apt-get --print-uris -y install "${PACKAGE_ARGS[@]}")" ||
    fail "cannot resolve the pinned Sphere APT transaction"
if grep -Eiq "(https?|ssh|git)://[^[:space:]\"']*gitlab[.]" <<<"$APT_INSTALL_PLAN"; then
    fail "the APT transaction contains a forbidden GitLab URL"
fi

# The signed APT index supplies the exact manifest-pinned packages. Package
# dependencies are resolved together, so this remains one atomic APT request.
apt-get install -y "${PACKAGE_ARGS[@]}"

for record in "${PACKAGE_RECORDS[@]}"; do
    IFS=$'\t' read -r package_name package_version _ <<<"$record"
    installed_version="$(dpkg-query -W -f='${Version}' "$package_name")"
    [[ "$installed_version" == "$package_version" ]] ||
        fail "$package_name installed as $installed_version instead of $package_version"
    printf '%s=%s\n' "$package_name" "$installed_version"
done

printf '%s profile installation completed from the signed APT source.\n' "$PROFILE_NAME"
