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

for command_name in apt-get awk chmod cmp curl dpkg dpkg-deb dpkg-query gpg gpgv install mktemp python3 tee; do
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
    "sphered",
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
if manifest.get("schema") != "medge-public-release/v18":
    raise SystemExit("release manifest schema is not medge-public-release/v18")
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

repair_edge_signing_key() {
    printf '%s\n' 'Repairing the Microsoft Edge repository key from Microsoft...'
    install -d -m 0700 "$TEMP_DIR/edge-gnupg"
    curl --proto '=https' --tlsv1.2 -fsSLo "$TEMP_DIR/microsoft.asc" \
        https://packages.microsoft.com/keys/microsoft.asc || return 1
    curl --proto '=https' --tlsv1.2 -fsSLo "$TEMP_DIR/edge-InRelease" \
        https://packages.microsoft.com/repos/edge/dists/stable/InRelease || return 1
    local fingerprint
    fingerprint="$(gpg --homedir "$TEMP_DIR/edge-gnupg" --batch --show-keys --with-colons \
        "$TEMP_DIR/microsoft.asc" | awk -F: '
        $1 == "pub" { count++ }
        $1 == "fpr" && fingerprint == "" { fingerprint = $10 }
        END { if (count != 1 || fingerprint == "") exit 1; print fingerprint }')" || return 1
    [[ "$fingerprint" == BC528686B50D79E339D3721CEB3E94ADBE1229CF ]] || return 1
    gpg --homedir "$TEMP_DIR/edge-gnupg" --batch --yes --dearmor \
        --output "$TEMP_DIR/microsoft-edge.gpg" "$TEMP_DIR/microsoft.asc" || return 1
    gpgv --homedir "$TEMP_DIR/edge-gnupg" --keyring "$TEMP_DIR/microsoft-edge.gpg" \
        "$TEMP_DIR/edge-InRelease" || return 1
    python3 - / "$TEMP_DIR/microsoft-edge.gpg" <<'PY_EDGE_REPAIR'
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import uuid

root, key_input = map(Path, sys.argv[1:])
edge = 'https://packages.microsoft.com/repos/edge'
key_name = '/etc/apt/keyrings/microsoft-edge.gpg'
insecure = {'trusted', 'allow-insecure', 'allow-weak', 'allow-downgrade-to-insecure'}

def directory(path):
    if not path.exists():
        directory(path.parent)
        path.mkdir(mode=0o755)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise SystemExit(f'unsafe APT directory: {path}')

def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or info.st_size > 1048576):
            raise SystemExit(f'unsafe APT file: {path}')
        return handle.read(1048577), stat.S_IMODE(info.st_mode)

def list_text(text):
    global matched
    output = []
    for line in text.splitlines(keepends=True):
        match = re.fullmatch(r'(\s*deb(?:-src)?\s+)(?:\[([^\]\n]*)\]\s+)?'
                             r'(https://packages\.microsoft\.com/repos/edge/?)'
                             r'([ \t]+stable[ \t]+[^\n]+)(\n?)', line)
        if match:
            matched = True
            options = shlex.split(match[2] or '')
            for option in options:
                name, _, value = option.partition('=')
                if name.lower() in insecure and value.lower() not in {'no', 'false', '0'}:
                    raise SystemExit('Edge source already permits insecure packages; repair it manually')
            options = [v for v in options if v.partition('=')[0].lower() != 'signed-by']
            options.append('signed-by=' + key_name)
            line = match[1] + '[' + ' '.join(options) + '] ' + match[3] + match[4] + match[5]
        output.append(line)
    return ''.join(output)

def stanza_text(stanza):
    global matched
    lines = stanza.splitlines(keepends=True)
    fields = {}
    spans = {}
    current = None
    for i, line in enumerate(lines):
        if line.startswith('#'):
            continue
        match = re.match(r'^([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)', line)
        if match:
            current = match[1].lower()
            if current in fields:
                raise SystemExit('duplicate field in APT source stanza')
            fields[current] = match[2].strip()
            spans[current] = [i]
        elif line[:1].isspace() and current:
            fields[current] += ' ' + line.strip()
            spans[current].append(i)
    uris = fields.get('uris', '').split()
    if edge not in [u.rstrip('/') for u in uris] or fields.get('enabled', 'yes').lower() == 'no':
        return stanza
    if any(u.rstrip('/') != edge for u in uris):
        raise SystemExit('Edge shares an APT stanza with another repository; split that stanza first')
    if 'stable' not in fields.get('suites', '').split():
        return stanza
    matched = True
    for name in insecure:
        if name in fields and fields[name].lower() not in {'no', 'false', '0'}:
            raise SystemExit('Edge source already permits insecure packages; repair it manually')
    remove = set(spans.get('signed-by', []))
    result = ''.join(line for i, line in enumerate(lines) if i not in remove)
    return result.rstrip('\n') + '\nSigned-By: ' + key_name + '\n'

apt = root / 'etc/apt'
directory(apt)
directory(apt / 'sources.list.d')
paths = [apt / 'sources.list'] if (apt / 'sources.list').exists() else []
paths += sorted(p for p in (apt / 'sources.list.d').iterdir() if p.suffix in {'.list', '.sources'})
plan = []
matched = False
for path in paths:
    original, mode = read(path)
    text = original.decode('utf-8')
    if path.suffix == '.sources':
        revised = ''.join(part if not part.strip() else stanza_text(part)
                          for part in re.split(r'(\n[ \t]*\n)', text))
    else:
        revised = list_text(text)
    if revised != text:
        plan.append((path, original, revised.encode(), mode))
if not matched:
    raise SystemExit('No supported active Edge stable source found; APT configuration was not changed')

directory(apt / 'keyrings')
key_path = root / key_name.lstrip('/')
previous_key, key_mode = read(key_path) if key_path.exists() or key_path.is_symlink() else (None, 0o644)
new_key = key_input.read_bytes()
if not new_key or len(new_key) > 65536:
    raise SystemExit('invalid verified Edge key size')
plan.insert(0, (key_path, previous_key, new_key, 0o644))
backup_root = root / 'var/backups'
directory(backup_root)
backup = backup_root / ('sphere-edge-apt-' + uuid.uuid4().hex)
backup.mkdir(mode=0o700)
records = []
for i, (path, before, after, mode) in enumerate(plan):
    if before is not None:
        saved = backup / str(i)
        saved.write_bytes(before)
        saved.chmod(0o600)
    records.append({'path': '/' + str(path.relative_to(root)), 'backup': str(i) if before is not None else None,
                    'sha256': hashlib.sha256(before).hexdigest() if before is not None else None})
(backup / 'files.json').write_text(json.dumps(records, indent=2) + '\n')
for path, before, after, mode in plan:
    exists = path.exists() or path.is_symlink()
    if (before is None and exists) or (before is not None and (not exists or read(path)[0] != before)):
        raise SystemExit(f'APT configuration changed during repair; backups: {backup}')
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(after)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(mode)
    os.replace(temporary, path)
print(f'Edge key repaired with repository-scoped Signed-By. Backups: {backup}')
PY_EDGE_REPAIR
}

if ! apt-get "${APT_OPTIONS[@]}" update 2>&1 | tee "$TEMP_DIR/apt-update.log"; then
    if python3 - "$TEMP_DIR/apt-update.log" <<'PY_EDGE_ERROR'
from pathlib import Path
import re
import sys
text = Path(sys.argv[1]).read_text(errors='replace')
raise SystemExit(0 if re.search(r'(?:GPG error|OpenPGP signature verification failed): https://packages\.microsoft\.com/repos/edge/? stable InRelease:', text) else 1)
PY_EDGE_ERROR
    then
        repair_edge_signing_key || fail 'Microsoft Edge key repair failed; signature checks remain enabled'
        apt-get "${APT_OPTIONS[@]}" update || fail 'APT still reports repository errors after Edge key repair'
    else
        fail 'APT repository update failed; repair the repository errors above and retry'
    fi
fi

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

# APT's locked pre-install hook admits only the physical Sphere replacement.
# Ordinary installs continue to forbid every package removal.
APT_REMOVAL_OPTIONS=(--no-remove)
if [[ "$(dpkg-query -W -f='${db:Status-Status}' sphere 2>/dev/null || true)" == installed ]]; then
    APT_REMOVAL_OPTIONS=()
fi
cat >"$TEMP_DIR/verify-removal" <<'PY_REMOVAL'
#!/usr/bin/python3
import re
import sys

payload = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
if len(payload) > 8 * 1024 * 1024:
    raise SystemExit("APT removal policy input is too large")
try:
    lines = payload.decode("utf-8").splitlines()
except UnicodeError:
    raise SystemExit("APT removal policy input is not UTF-8")
if not lines or lines.pop(0) != "VERSION 2" or "" not in lines:
    raise SystemExit("APT removal policy requires protocol version 2")
actions = lines[lines.index("") + 1:]
for line in actions:
    fields = line.split()
    if len(fields) != 5 or fields[2] not in {"<", ">", "="}:
        raise SystemExit("APT removal policy received an invalid action")
    name, old, direction, new, action = fields
    if action == "**REMOVE**":
        if name != "sphere" or old == "-" or new != "-":
            raise SystemExit("APT removal outside the sphere-to-sphered migration is forbidden")
    elif action != "**CONFIGURE**" and not action.endswith(".deb"):
        raise SystemExit("APT removal policy received an unknown action")
PY_REMOVAL
chmod 0700 "$TEMP_DIR/verify-removal"
APT_OPTIONS+=(
    -o "DPkg::Pre-Install-Pkgs::=$TEMP_DIR/verify-removal"
    -o "DPkg::Tools::Options::$TEMP_DIR/verify-removal::Version=2"
    -o "DPkg::Tools::Options::$TEMP_DIR/verify-removal::InfoFD=0"
)

# Reinstall forces verification even when an identical version is installed.
# Every actual dpkg transaction checks removal actions under the APT lock.
apt-get "${APT_OPTIONS[@]}" "${APT_REMOVAL_OPTIONS[@]}" --allow-downgrades --reinstall \
    --print-uris -y install "${PACKAGE_ARGS[@]}" >"$TEMP_DIR/apt-install-plan" ||
    fail "cannot resolve the pinned Sphere APT transaction"
verify_apt_artifacts plan
apt-get "${APT_OPTIONS[@]}" "${APT_REMOVAL_OPTIONS[@]}" --allow-downgrades --reinstall \
    --download-only -y install "${PACKAGE_ARGS[@]}"
verify_apt_artifacts staged

# Preserve the caller's creation mask for package maintainer scripts.
umask "$ORIGINAL_UMASK"
# This is the only package mutation. No new download may bypass verification.
apt-get "${APT_OPTIONS[@]}" "${APT_REMOVAL_OPTIONS[@]}" --allow-downgrades --reinstall \
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
printf '%s\n' \
    'Reader setup: start mlink.service and moted.service, then run mlink.' \
    'Choose Y to use a reader or N to disable it. Keys are blocked only while ready.' \
    'First-use commands and advanced setup: https://github.com/motebus/download#terminal-setup-and-chat'
