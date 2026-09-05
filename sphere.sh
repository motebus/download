#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE_NAME="sphere"
readonly BASE_URL="https://motebus.github.io/download"
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

for command_name in apt-get awk chmod cmp curl dpkg dpkg-deb dpkg-query gpg gpgv install mktemp python3; do
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
TEMP_DIR="$(mktemp -d "/tmp/${PROFILE_NAME}-install.XXXXXX")"
readonly TEMP_DIR
cleanup() {
    python3 - "$TEMP_DIR" "$PROFILE_NAME-install" <<'PY'
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
selected = tuple(name for name in expected if name != "ultra-mcp-ssh")
version_re = re.compile(r"^[0-9][0-9A-Za-z.+:~]*-[0-9]+$")
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
    sha256 = item.get("sha256")
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise SystemExit(f"{name}: invalid release SHA-256")
    if name in selected:
        print(f"{name}\t{version}\t{asset}\t{sha256}")
PY

mapfile -t PACKAGE_RECORDS <"$TEMP_DIR/package-plan"
[[ "${#PACKAGE_RECORDS[@]}" -eq 16 ]] || fail "release manifest package plan is incomplete for $PROFILE_NAME"

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

# Keep this invocation's indexes and archives separate from the system cache.
# Only the APT directories are readable by the acquisition sandbox.
chmod 0755 "$TEMP_DIR"
install -d -m 0755 "$TEMP_DIR/apt" "$TEMP_DIR/apt/lists" "$TEMP_DIR/apt/archives"
APT_OPTIONS=(
    -o "Dir::State::lists=$TEMP_DIR/apt/lists"
    -o "Dir::Cache::archives=$TEMP_DIR/apt/archives"
    -o 'Dir::Cache::pkgcache='
    -o 'Dir::Cache::srcpkgcache='
    -o Acquire::http::No-Cache=true
    -o Acquire::Languages=none
    -o APT::Update::Error-Mode=any
    -o Acquire::AllowInsecureRepositories=false
    -o Acquire::AllowDowngradeToInsecureRepositories=false
    -o APT::Get::AllowUnauthenticated=false
)
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C
apt-get "${APT_OPTIONS[@]}" update

PACKAGE_ARGS=()
for record in "${PACKAGE_RECORDS[@]}"; do
    IFS=$'\t' read -r package_name package_version package_asset package_sha256 <<<"$record"
    PACKAGE_ARGS+=("$package_name=$package_version")
done

verify_apt_artifacts() {
    python3 - "$1" "$MANIFEST_PATH" "$TEMP_DIR/package-plan" \
        "$TEMP_DIR/apt-install-plan" "$TEMP_DIR/apt/archives" "$BASE_URL" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
from urllib.parse import unquote, urlsplit

mode, manifest_path, selection_path, plan_path, archives_path, base_url = sys.argv[1:]
catalog = {item["name"]: item for item in json.loads(Path(manifest_path).read_text())["packages"]}
selected = {line.split("\t", 1)[0] for line in Path(selection_path).read_text().splitlines()}
base = urlsplit(base_url)
archives = Path(archives_path)
planned = {}
planned_packages = set()
for line in Path(plan_path).read_text().splitlines():
    # apt-get --print-uris quotes acquisition rows; other lines are progress.
    if not line.startswith("'"):
        continue
    fields = shlex.split(line)
    if len(fields) != 4 or not fields[2].isdigit():
        raise SystemExit("invalid APT acquisition record")
    uri, filename, size, _index_hash = fields
    decoded = unquote(filename)
    identity = re.fullmatch(r"([a-z0-9][a-z0-9+.-]*)_([^/\\\s]+)_([a-z0-9-]+)\.deb", decoded)
    if identity is None or "/" in filename or "\\" in filename or filename in planned:
        raise SystemExit("unsafe or duplicate APT archive filename")
    name, version, architecture = identity.groups()
    if name in planned_packages:
        raise SystemExit(f"{name}: duplicate APT package acquisition")
    source = urlsplit(uri)
    if (source.scheme not in {"https", "http"} or not source.hostname
            or source.username is not None or source.password is not None
            or source.fragment or "gitlab" in source.hostname.lower()):
        raise SystemExit("the APT transaction contains a forbidden source URL")
    if name in catalog:
        item = catalog[name]
        first = name[:4] if name.startswith("lib") else name[0]
        expected_path = f"{base.path}/pool/main/{first}/{name}/{item['asset']}"
        if (source.scheme != base.scheme or source.netloc != base.netloc
                or source.query or unquote(source.path) != expected_path
                or decoded != item["asset"]):
            raise SystemExit(f"{name}: APT origin or asset differs from the signed manifest")
    planned[filename] = (name, version, architecture, int(size))
    planned_packages.add(name)
missing = selected - planned_packages
if missing:
    raise SystemExit("APT must reacquire every selected package: " + ", ".join(sorted(missing)))
if mode == "plan":
    raise SystemExit(0)
if mode != "staged":
    raise SystemExit("invalid artifact verification mode")
actual = {path.name for path in archives.iterdir() if path.name not in {"lock", "partial"}}
if actual != set(planned):
    raise SystemExit("staged APT archive set differs from the reviewed acquisition plan")
for filename, (name, version, architecture, size) in planned.items():
    path = archives / filename
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022
            or metadata.st_size != size):
        raise SystemExit(f"{name}: unsafe or incomplete staged APT archive")
    if name in catalog:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != catalog[name]["sha256"]:
            raise SystemExit(f"{name}: staged package SHA-256 differs from the signed manifest")
    fields = subprocess.check_output([
        "dpkg-deb", "--show", "--showformat=${Package}\t${Version}\t${Architecture}\n", str(path),
    ], text=True).strip().split("\t")
    if fields != [name, version, architecture]:
        raise SystemExit(f"{name}: staged Debian metadata differs from the reviewed acquisition plan")
PY
}

# Reinstall forces verification even when an identical version is installed.
# Every APT phase independently refuses removals, including the final mutation.
apt-get "${APT_OPTIONS[@]}" --no-remove --allow-downgrades --reinstall \
    --print-uris -y install "${PACKAGE_ARGS[@]}" >"$TEMP_DIR/apt-install-plan" ||
    fail "cannot resolve the pinned Sphere APT transaction without removals"
verify_apt_artifacts plan
apt-get "${APT_OPTIONS[@]}" --no-remove --allow-downgrades --reinstall \
    --download-only -y install "${PACKAGE_ARGS[@]}"
verify_apt_artifacts staged

# Preserve the caller's creation mask for package maintainer scripts.
umask "$ORIGINAL_UMASK"
# This is the only package mutation. No new download may bypass verification.
apt-get "${APT_OPTIONS[@]}" --no-remove --allow-downgrades --reinstall \
    --no-download -y install "${PACKAGE_ARGS[@]}"

for record in "${PACKAGE_RECORDS[@]}"; do
    IFS=$'\t' read -r package_name package_version _ <<<"$record"
    installed_state="$(dpkg-query -W -f='${db:Status-Status} ${Version}' "$package_name")"
    [[ "$installed_state" == "installed $package_version" ]] ||
        fail "$package_name did not reach the installed state at $package_version: $installed_state"
    installed_version="${installed_state#installed }"
    printf '%s=%s\n' "$package_name" "$installed_version"
done

printf '%s profile installation completed from the signed APT source.\n' "$PROFILE_NAME"
