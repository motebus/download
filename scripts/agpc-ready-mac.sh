#!/bin/bash
# AGPC Ready for Apple Silicon: Sphere on Linux amd64, B-channel proxy on macOS.
set -euo pipefail
umask 077
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

version=0.1.0-preview.21
archive="agpc-mac-arm64-${version}.tar.gz"
release_url="https://github.com/motebus/download/releases/download/agpc-native-v${version}"
pages_url=https://motebus.github.io/download
ready_url=https://github.com/motebus/download/releases/download/agpc-ready-mac-v0.1.0-preview.1
proxy_archive=agpc-ready-mac-proxy-arm64.tar.gz
proxy_sha=d968c36fc47b368330274050f4d38eb774146cf2029e5030f7e005116b72a3c2
guest_sha=bcff70935c90327da754afb740e46c314e4610f55b2b21ae09d18c9b3615f916
ready_sums_sha=4d7d043189702ee71b89e1c1caaac398d195fbaa726d78c39e1756e871345358
utm_url=https://github.com/utmapp/UTM/releases/download/v5.0.8/UTM.dmg
utm_sha=7b2d7b2e2a02b3de1757ef19a8f36573e6d9cceae8c8cca0abcbcaa4a852019a
ubuntu_url=https://cloud-images.ubuntu.com/releases/26.04/release-20261016/ubuntu-26.04-server-cloudimg-amd64.img
ubuntu_sha=5645d0318ad21f643ebb1ac4567514620e9893380b07b0201fda163baa5b7eb5
archive_sha=c9dfa15e6a23279596bd55b04cd2ec3b86f951e04926bc108dc84e0493460cdc
controller_sha=6ab5b3bcbd5f6e5df695d6885c4b971624e12171c8274ed14d794d6f63c01320
keyring_sha=756fc2632c307509b8e5ece665ced7f4d1a58636ac935aefc1e017f7dcfcbfbd
proxy_prefix=/Library/AGPC/mote-proxy
proxy_plist="$proxy_prefix/com.agpc.mote-proxy.b.plist"
proxy_label=com.agpc.mote-proxy
login_label=com.agpc.sphere-utm

usage() {
    cat <<'EOF'
Usage: bash agpc-ready-mac.sh [--plan | --verify | --help]
       bash agpc-ready-mac.sh --install --upstreams 'HOST1;HOST2'
       bash agpc-ready-mac.sh --install --utm-app /path/to/UTM.app --vm-id UUID
       bash agpc-ready-mac.sh --install --utm-app /path/to/UTM.app --vm-id UUID \
           --guest-ssh-dir DIRECTORY --upstreams 'HOST1;HOST2'
  --plan       Print requirements. Default.
  --verify     Verify the controller and signed native proxy and guest installer.
  --install    Configure the Linux amd64 Sphere guest to start at login and
               install the native B-channel proxy to start at system boot.

Without --vm-id, the installer provisions a new Ubuntu amd64 VM in UTM
and installs the pinned UTM release if needed. Supply your deployment's
upstream hosts. With --vm-id, you can use an existing guest. For an existing
guest without mbStack and DC, use --guest-ssh-dir and --upstreams. The directory holds
guest-ssh-key and guest-known-hosts for agpcbuild@127.0.0.1:22242.
The guest needs Node.js 22 and must forward TCP 6262 to Mac loopback.
See README.md in the release for requirements and setup.
EOF
}

fail() {
    printf 'agpc-ready-mac: %s\n' "$*" >&2
    exit 1
}

verify_sha() {
    local actual
    actual=$(/usr/bin/shasum -a 256 "$1") || fail "Could not hash $1."
    [[ ${actual%% *} == "$2" ]] || fail "SHA-256 mismatch for $3."
}

fetch() {
    /usr/bin/curl --fail --silent --show-error --location --proto '=https' \
        --proto-redir '=https' --connect-timeout 15 --max-time 600 --retry 2 \
        --output "$2" "$1" || fail "Could not download $1."
}

bootstrap_gpgv() (
# Stage a pinned, relocatable OpenPGP verifier for a stock Apple Silicon Mac.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077
[[ $# == 1 ]]
work=$1
base=https://conda.anaconda.org/conda-forge/osx-arm64
fetch() {
    local name=$1 sha=$2 actual
    curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 120 \
        -o "$work/$name" "$base/$name"
    actual=$(shasum -a 256 "$work/$name")
    [[ ${actual%% *} == "$sha" ]] || { printf 'SHA-256 mismatch for %s\n' "$name" >&2; exit 1; }
}
fetch micromamba-2.10.0-0.tar.bz2 acef4eaab19ec2174ad5a449e5aad981ca326270db819502ff096a92fc31caa6
mkdir -p "$work/verifier/bin" "$work/verifier/lib"
tar -xOf "$work/micromamba-2.10.0-0.tar.bz2" bin/micromamba > "$work/micromamba"
chmod 0700 "$work/micromamba"
while read -r name sha member; do
    fetch "$name" "$sha"
    "$work/micromamba" package extract --no-env --no-rc "$work/$name" "$work/package" >&2
    cp -L "$work/package/$member" "$work/verifier/$member"
    rm -r -- "$work/package"
done <<'PACKAGES'
gnupg-2.5.24-h1775f82_0.conda 3e1b9115df3d4213b19b1fe10022b0584cbf3134348e60335346c7ee5359438d bin/gpgv
bzip2-1.0.8-h4e30115_10.conda 8ec22f0ba25cbfc2e64d70cf29459eccd7ffdf6436f6a6ff15bbfef799f7d4f6 lib/libbz2.dylib
libassuan-3.0.2-h286801f_0.conda 0d8ec81850417d106df2cd4d4cb21e1597c8ce9a930bc86857ea504eb8e08dd4 lib/libassuan.9.dylib
libgcrypt-lib-1.12.2-hb001647_2.conda 45b1b91ff0b7dcfb2d31ffcdc156be2cb93998d80764f9a1f4bbd6a51e5a318a lib/libgcrypt.20.dylib
libgpg-error-1.61-hdca3b7d_2.conda 75e64458efad17d0315b8aefc30f734eabd7ad97bb3ebf75e14026ccfbd31fb2 lib/libgpg-error.0.dylib
libiconv-1.18-he4c29f2_3.conda 689a14968267f2f97c07112fca5636e7d756036b9aee969911267c20bd3eea1f lib/libiconv.2.dylib
libintl-1.0-hae62183_1.conda 50cd23514846dd057c5d3d4f38e29a7948909e51b3b53b99fe4b8a541971edb0 lib/libintl.8.dylib
libzlib-1.3.2-h8088a28_3.conda a18fa5d5bac452401459f966cf0d872224e8080c4ff93c77e168d43ab42ef9d7 lib/libz.1.dylib
npth-1.8-h286801f_0.conda e6f12cee635860a2f70dc40ad28d20d80cdabf566dfab2db1ca0489b1fb891a9 lib/libnpth.0.dylib
PACKAGES
chmod 0700 "$work/verifier/bin/gpgv"
"$work/verifier/bin/gpgv" --version >&2
printf '%s\n' "$work/verifier/bin/gpgv"
)

create_sphere_utm() (
# Create a dedicated, locally provisioned UTM guest from verified inputs.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077

fail() { printf 'Sphere UTM: %s\n' "$*" >&2; exit 1; }
[[ $# == 5 ]] || fail 'Expected UTM app, state directory, cloud image, guest installer and upstreams.'
utm=$1
state=$2
image=$3
guest_installer=$4
upstreams=$5
[[ "$upstreams" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?(\;[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?)*$ ]] ||
    fail 'Supply the deployment upstreams as a semicolon-separated list.'

# Keep the UUID, guest trust files, and seed inputs together on retries.
[[ ! -L "$state" ]] || fail 'Unexpected symlink at the Sphere state directory.'
mkdir -p "$state"
[[ -O "$state" && $(stat -f '%OLp' "$state") == 700 ]] || fail 'Sphere state directory must be private.'
if ! mkdir "$state/install.lock" 2>/dev/null; then
    fail "Another Sphere provisioning process is active or left $state/install.lock."
fi
scratch=$(mktemp -d "$state/.provision.XXXXXXXX")
cleanup() { rm -r -- "$scratch"; rmdir "$state/install.lock"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ ! -f "$state/vm-id" ]]; then
    uuidgen > "$scratch/vm-id"
    mv "$scratch/vm-id" "$state/vm-id"
fi
vm_id=$(cat "$state/vm-id")
[[ "$vm_id" =~ ^[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}$ ]] || fail 'Invalid saved Sphere UUID.'
if [[ -f "$state/upstreams" ]]; then
    [[ $(cat "$state/upstreams") == "$upstreams" ]] || fail 'Saved Sphere VM uses different upstreams.'
else
    printf '%s\n' "$upstreams" > "$scratch/upstreams"
    mv "$scratch/upstreams" "$state/upstreams"
fi
for key in guest-host guest-client; do
    if [[ ! -f "$state/$key" ]]; then
        ssh-keygen -q -t ed25519 -N '' -C '' -f "$scratch/$key"
        mv "$scratch/$key" "$state/$key"
    fi
    ssh-keygen -y -f "$state/$key" > "$scratch/$key.pub"
done
printf '[127.0.0.1]:22242 %s\n' "$(cat "$scratch/guest-host.pub")" > "$scratch/known-hosts"

open -a "$utm"
# The AppleScript import expects a package, and UTM copies it to its library.
vm="$scratch/AGPC Sphere.utm"
mkdir -p "$vm/Data" "$scratch/seed"
cat > "$vm/config.plist" <<'PLIST'
{
  "Backend": "QEMU",
  "ConfigurationVersion": 4,
  "Display": [{"DownscalingFilter": "Linear", "DynamicResolution": false, "Hardware": "virtio-gpu-pci", "NativeResolution": false, "UpscalingFilter": "Linear"}],
  "Drive": [
    {"Identifier": "00000000-0000-4000-8000-000000000001", "ImageName": "sphere.qcow2", "ImageType": "Disk", "Interface": "IDE", "InterfaceVersion": 1, "ReadOnly": false},
    {"Identifier": "00000000-0000-4000-8000-000000000002", "ImageName": "seed.iso", "ImageType": "CD", "Interface": "IDE", "InterfaceVersion": 1, "ReadOnly": true}
  ],
  "Information": {"Icon": "linux", "IconCustom": false, "Name": "AGPC Sphere", "UUID": "00000000-0000-4000-8000-000000000000"},
  "Input": {"MaximumUsbShare": 3, "UsbBusSupport": "3.0", "UsbSharing": false},
  "Network": [{"Hardware": "e1000", "IsolateFromHost": false, "MacAddress": "02:00:00:00:00:00", "Mode": "Emulated",
    "PortForward": [
      {"GuestAddress": "10.0.2.15", "GuestPort": 22, "HostAddress": "127.0.0.1", "HostPort": 22242, "Protocol": "TCP"},
      {"GuestAddress": "10.0.2.15", "GuestPort": 6262, "HostAddress": "127.0.0.1", "HostPort": 6262, "Protocol": "TCP"}
    ]
  }],
  "QEMU": {"AdditionalArguments": [], "BalloonDevice": false, "DebugLog": false, "Hypervisor": false, "PS2Controller": false, "RNGDevice": true, "RTCLocalTime": false, "TPMDevice": false, "TSO": false, "UEFIBoot": true},
  "Serial": [],
  "Sharing": {"ClipboardSharing": false, "DirectoryShareMode": "None", "DirectoryShareReadOnly": true},
  "Sound": [],
  "System": {"Architecture": "x86_64", "CPU": "default", "CPUCount": 4, "CPUFlagsAdd": [], "CPUFlagsRemove": [], "ForceMulticore": false, "JITCacheSize": 0, "MemorySize": 4096, "Target": "q35"}
}
PLIST
plutil -convert xml1 "$vm/config.plist"
mac_tail=$(printf '%s' "$vm_id" | tr -d '-' | cut -c1-10 | sed 's/../&:/g;s/:$//')
plutil -replace Information.UUID -string "$vm_id" "$vm/config.plist"
plutil -replace Drive.0.Identifier -string "$(uuidgen)" "$vm/config.plist"
plutil -replace Drive.1.Identifier -string "$(uuidgen)" "$vm/config.plist"
plutil -replace Network.0.MacAddress -string "02:$mac_tail" "$vm/config.plist"
plutil -lint "$vm/config.plist" >&2
printf 'instance-id: %s\nlocal-hostname: agpc-sphere\n' "$vm_id" > "$scratch/seed/meta-data"
cat > "$scratch/seed/network-config" <<NETWORK
version: 2
ethernets:
  sphere:
    match:
      macaddress: "02:$mac_tail"
    dhcp4: false
    dhcp6: false
    addresses: [10.0.2.15/24]
    routes:
      - to: default
        via: 10.0.2.2
    nameservers:
      addresses: [10.0.2.3]
NETWORK
{
    cat <<CLOUD
#cloud-config
hostname: agpc-sphere
ssh_pwauth: false
disable_root: true
ssh_deletekeys: true
ssh_genkeytypes: []
ssh_keys:
  ed25519_public: $(cat "$scratch/guest-host.pub")
  ed25519_private: |
CLOUD
    sed 's/^/    /' "$state/guest-host"
    cat <<CLOUD
users:
  - name: agpc-check
    shell: /bin/sh
    lock_passwd: true
    ssh_authorized_keys:
      - $(cat "$scratch/guest-client.pub")
write_files:
  - path: /var/lib/agpc-bootstrap/install-sphere-guest.sh
    owner: root:root
    permissions: '0700'
    content: |
CLOUD
    sed 's/^/      /' "$guest_installer"
    cat <<'CLOUD'
  - path: /var/lib/agpc-bootstrap/firstboot.sh
    owner: root:root
    permissions: '0700'
    content: |
CLOUD
    sed 's/^/      /' <<'GUEST'
#!/bin/bash
set -euo pipefail
installer=/var/lib/agpc-bootstrap/install-sphere-guest.sh
printf '%s  %s\n' bcff70935c90327da754afb740e46c314e4610f55b2b21ae09d18c9b3615f916 "$installer" | sha256sum -c -
if ! command -v curl >/dev/null; then
    apt-get -q update
    DEBIAN_FRONTEND=noninteractive apt-get install -qy --no-install-recommends curl ca-certificates
fi
stage=$(mktemp -d)
trap 'rm -r -- "$stage"' EXIT
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 15 --max-time 300 --retry 2 --output "$stage/node.tar.xz" \
    https://nodejs.org/dist/v22.22.1/node-v22.22.1-linux-x64.tar.xz
printf '%s  %s\n' 9a6bc82f9b491279147219f6a18add1e18424dce90d41d2a5fcd69d4924ba3aa "$stage/node.tar.xz" | sha256sum -c -
tar -xOf "$stage/node.tar.xz" node-v22.22.1-linux-x64/bin/node > "$stage/node"
install -m 0755 "$stage/node" /usr/bin/node
/bin/bash "$installer" --install "$1"
GUEST
    cat <<CLOUD
runcmd:
  - [ /bin/bash, /var/lib/agpc-bootstrap/firstboot.sh, '$upstreams' ]
CLOUD
} > "$scratch/seed/user-data"

if ! "$utm/Contents/MacOS/utmctl" list | awk -v id="$vm_id" '$1 == id {found=1} END {exit !found}'; then
    if nc -G 1 -z 127.0.0.1 6262 || nc -G 1 -z 127.0.0.1 22242; then
        fail 'TCP 6262 or 22242 on loopback is in use. Stop the existing VM or select it with --vm-id.'
    fi
    hdiutil makehybrid -quiet -iso -joliet -iso-volume-name CIDATA -joliet-volume-name CIDATA \
        -o "$vm/Data/seed.iso" "$scratch/seed" >&2
    cp "$image" "$vm/Data/sphere.qcow2"
    # The .utm package contains this Mac's generated SSH host key.
    chmod 0700 "$vm" "$vm/Data"
    chmod 0600 "$vm/Data/seed.iso"
    osascript - "$vm" "$vm_id" >&2 <<'APPLE'
on run argv
    set packageFile to POSIX file (item 1 of argv)
    set expectedId to item 2 of argv
    with timeout of 120 seconds
        tell application id "com.utmapp.UTM"
            set guest to import new virtual machine from packageFile
            if id of guest is not expectedId then error "Imported Sphere VM UUID differs."
        end tell
    end timeout
end run
APPLE
fi
mv "$scratch/known-hosts" "$state/known-hosts"
printf '%s\n' "$vm_id"
)

cleanup() {
    if [[ -n "$utm_mount" ]]; then /usr/bin/hdiutil detach "$utm_mount" >/dev/null || true; fi
    if [[ -n "$utm_stage" && -d "$utm_stage" ]]; then /bin/rm -r -- "$utm_stage"; fi
    if [[ -n "$install_stage" ]]; then
        if [[ -f "$install_stage/agpc" ]]; then /bin/rm -- "$install_stage/agpc"; fi
        /bin/rmdir "$install_stage"
    fi
    /bin/rm -r -- "$work"
}

mode=${1:---plan}
if [[ $# -gt 0 ]]; then shift; fi
utm_app=
vm_id=
guest_ssh_dir=
upstreams=
payload_input=
if [[ "$mode" == --install ]]; then
    while [[ $# -gt 0 ]]; do
        [[ $# -ge 2 ]] || fail "Missing value for $1."
        case "$1" in
            --utm-app) utm_app=$2 ;;
            --vm-id) vm_id=$2 ;;
            --guest-ssh-dir) guest_ssh_dir=$2 ;;
            --upstreams) upstreams=$2 ;;
            *) fail "Unknown argument $1." ;;
        esac
        shift 2
    done
elif [[ "$mode" == --install-proxy-startup && $# -eq 1 ]]; then
    payload_input=$1
    shift
fi
[[ $# -eq 0 ]] || { usage >&2; exit 2; }
case "$mode" in
    --help|-h) usage; exit 0 ;;
    --plan)
        printf 'Apple Silicon controller %s\nSource: %s/%s\nDestination: ~/.local/bin/agpc\n' \
            "$version" "$release_url" "$archive"
        printf '%s\n' 'Startup: Linux amd64 mbStack and DC in UTM at Mac login; native B-channel proxy at system boot.'
        exit 0
        ;;
    --verify|--install|--install-proxy-startup) ;;
    *) usage >&2; exit 2 ;;
esac

[[ $(/usr/bin/uname -s) == Darwin && $(/usr/bin/uname -m) == arm64 ]] ||
    fail 'A native Apple Silicon macOS shell is required.'

proxy_member_hash() {
    case "$1" in
        com.agpc.mote-proxy.b.plist) printf '%s' ed16eb66c8963b5e95d40a21f987a6bcbf16ac40b396d2bb487db0b8c0d15804 ;;
        mote-proxy-b) printf '%s' f7978df775ef7e595163166903672551fba50689ef7619d08a43eb6a57831ccd ;;
        mote-ssh) printf '%s' 3f82bab32d5fe28957dc7cd002119a9404f29fabe9fbf33ced132780a70bcd18 ;;
        ssh-proxy) printf '%s' 4981870f1e02fc99cfa6ebf8c423e97579b74ae68cc7a63818d00ce4703af540 ;;
        *) fail "Unknown proxy member: $1" ;;
    esac
}

proxy_members=(mote-proxy-b mote-ssh ssh-proxy com.agpc.mote-proxy.b.plist)
proxy_runtime=/private/var/db/agpc-mote-proxy

check_entry() {
    local path=$1 ownership=$2 kind=$3
    [[ ! -L "$path" ]] || fail "Unexpected symlink: $path"
    if [[ -e "$path" ]]; then
        if [[ "$kind" == directory ]]; then
            [[ -d "$path" ]] || fail "Expected directory: $path"
        else
            [[ -f "$path" ]] || fail "Expected regular file: $path"
        fi
        [[ $(/usr/bin/stat -f '%Su:%Sg:%OLp' "$path") == "$ownership" ]] ||
            fail "Unexpected ownership or mode: $path"
    fi
}

if [[ "$mode" == --install-proxy-startup ]]; then
    [[ $EUID -eq 0 && -n "${SUDO_USER:-}" && "$SUDO_USER" != root && "$payload_input" == /* && -f "$payload_input" ]] ||
        fail 'Use --install from your macOS login account.'
    export PATH=/usr/bin:/bin:/usr/sbin:/sbin
    proxy_stage=$(/usr/bin/mktemp -d /private/tmp/agpc-proxy.XXXXXXXX)
    system_stage=
    cleanup_proxy() {
        /bin/rm -rf -- "$proxy_stage"
        if [[ -n "$system_stage" ]]; then /bin/rm -rf -- "$system_stage"; fi
    }
    trap cleanup_proxy EXIT
    /bin/cp "$payload_input" "$proxy_stage/$proxy_archive"
    verify_sha "$proxy_stage/$proxy_archive" "$proxy_sha" 'native proxy bundle'
    for name in "${proxy_members[@]}"; do
        /usr/bin/tar -xOf "$proxy_stage/$proxy_archive" "$name" > "$proxy_stage/$name"
        verify_sha "$proxy_stage/$name" "$(proxy_member_hash "$name")" "$name"
        case "$name" in
            *.plist) /usr/bin/plutil -lint "$proxy_stage/$name" ;;
            *) /usr/bin/codesign --verify --strict "$proxy_stage/$name" ;;
        esac
    done
    for dir in /Library /Library/AGPC "$proxy_prefix" "$proxy_prefix/bin" /private/var/db "$proxy_runtime" /Library/LaunchDaemons; do
        check_entry "$dir" root:wheel:755 directory
    done
    check_entry "$proxy_runtime/run" mote-proxy:mote-proxy:755 directory
    for name in "${proxy_members[@]}"; do
        if [[ "$name" == *.plist ]]; then target="$proxy_plist"; perms=644
        else target="$proxy_prefix/bin/$name"; perms=755
        fi
        check_entry "$target" "root:wheel:$perms" file
        if [[ -e "$target" ]]; then
            actual=$(/usr/bin/shasum -a 256 "$target")
            case "$name:${actual%% *}" in
                mote-proxy-b:566392f312163ae3eeb2d1e4962c62c11a1b889b0db40a2305666bf9bf7e3ccb|mote-ssh:68b91d861bb5f3be815f483f1b81668008d443afe99faaa0825d180994aded46|ssh-proxy:e691439dfa5b8bdc46c7ad5d0cb1fc188c5569e12e7cda46a014a4fec1f08b3c)
                    # Preserve the corresponding reboot-tested M4 preview build.
                    /usr/bin/codesign --verify --strict "$target"
                    ;;
                *) verify_sha "$target" "$(proxy_member_hash "$name")" "$target" ;;
            esac
        fi
    done

    account=mote-proxy
    if /usr/bin/dscl . -read "/Users/$account" >/dev/null 2>&1 &&
       ! /usr/bin/dscl . -read "/Groups/$account" >/dev/null 2>&1; then
        fail 'Existing mote-proxy account has no corresponding local group.'
    fi
    if /usr/bin/dscl . -read "/Groups/$account" >/dev/null 2>&1; then
        gid=$(/usr/bin/dscl . -read "/Groups/$account" PrimaryGroupID)
        gid=${gid#PrimaryGroupID: }
        [[ "$gid" =~ ^[0-9]+$ && "$gid" -ge 400 && "$gid" -lt 500 ]] ||
            fail 'Unexpected mote-proxy group ID.'
    else
        for gid in $(/usr/bin/jot 99 499 401); do
            matches=$(/usr/bin/dscl . -search /Groups PrimaryGroupID "$gid")
            users=$(/usr/bin/dscl . -search /Users UniqueID "$gid")
            if [[ -z "$matches" && -z "$users" ]]; then break; fi
        done
        [[ "$gid" -gt 401 ]] || fail 'No free service account ID.'
        /usr/sbin/dseditgroup -o create -i "$gid" "$account"
    fi
    if ! /usr/bin/dscl . -read "/Users/$account" >/dev/null 2>&1; then
        [[ -z $(/usr/bin/dscl . -search /Users UniqueID "$gid") ]] ||
            fail 'The mote-proxy user ID is already in use.'
        /usr/bin/dscl . -create "/Users/$account" UniqueID "$gid"
        /usr/bin/dscl . -create "/Users/$account" PrimaryGroupID "$gid"
        /usr/bin/dscl . -create "/Users/$account" RealName 'AGPC Mote Proxy'
        /usr/bin/dscl . -create "/Users/$account" NFSHomeDirectory /var/empty
        /usr/bin/dscl . -create "/Users/$account" UserShell /usr/bin/false
        /usr/bin/dscl . -create "/Users/$account" IsHidden 1
        /usr/bin/dscl . -create "/Users/$account" Password '*'
    fi
    for entry in "UniqueID: $gid" "PrimaryGroupID: $gid" 'NFSHomeDirectory: /var/empty' 'UserShell: /usr/bin/false'; do
        [[ $(/usr/bin/dscl . -read "/Users/$account" "${entry%%:*}") == "$entry" ]] ||
            fail "Unexpected mote-proxy service account attribute: $entry"
    done
    [[ $(/usr/bin/dscl . -read "/Users/$account" Password) == 'Password: *' ]] ||
        fail 'The mote-proxy service account must have a disabled password.'
    /usr/sbin/dseditgroup -o edit -a "$SUDO_USER" -t user "$account"
    for dir in /Library/AGPC "$proxy_prefix" "$proxy_prefix/bin" "$proxy_runtime"; do
        /usr/bin/install -d -o root -g wheel -m 0755 "$dir"
    done
    /usr/bin/install -d -o "$account" -g "$account" -m 0755 "$proxy_runtime/run"
    for name in "${proxy_members[@]}"; do
        if [[ "$name" == *.plist ]]; then target="$proxy_plist"; perms=644
        else target="$proxy_prefix/bin/$name"; perms=755
        fi
        if [[ ! -e "$target" ]]; then
            /usr/bin/install -o root -g wheel -m "$perms" "$proxy_stage/$name" "$target"
        fi
    done
    daemon=/Library/LaunchDaemons/$proxy_label.plist
    system_stage=$(/usr/bin/mktemp -d /Library/LaunchDaemons/.agpc.XXXXXXXX)
    /usr/bin/install -o root -g wheel -m 0644 "$proxy_plist" "$system_stage/$proxy_label.plist"
    /usr/bin/plutil -insert KeepAlive -bool YES "$system_stage/$proxy_label.plist"
    /usr/bin/plutil -insert ThrottleInterval -integer 15 "$system_stage/$proxy_label.plist"
    /usr/bin/plutil -lint "$system_stage/$proxy_label.plist"
    check_entry "$daemon" root:wheel:644 file
    if [[ -e "$daemon" ]]; then
        /usr/bin/cmp -s "$system_stage/$proxy_label.plist" "$daemon" ||
            fail "Existing LaunchDaemon requires review: $daemon"
    else
        /bin/mv "$system_stage/$proxy_label.plist" "$daemon"
    fi
    /bin/launchctl enable "system/$proxy_label"
    if loaded=$(/bin/launchctl print "system/$proxy_label" 2>/dev/null); then
        if [[ "$loaded" != *"path = $daemon"* ]]; then
            [[ "$loaded" == *"path = $proxy_plist"* ]] ||
                fail "Existing loaded job requires review: $proxy_label"
            /bin/launchctl bootout "system/$proxy_label"
            if ! /bin/launchctl bootstrap system "$daemon"; then
                /bin/launchctl bootstrap system "$proxy_plist"
                fail "Could not load the persistent LaunchDaemon: $daemon"
            fi
        fi
    else
        /bin/launchctl bootstrap system "$daemon"
    fi
    /bin/launchctl print "system/$proxy_label" >/dev/null
    printf 'Enabled %s at macOS system boot.\n' "$proxy_label"
    exit 0
fi

[[ $(/usr/bin/id -u) -ne 0 ]] || fail 'Run without sudo.'
if [[ "$mode" == --install ]]; then
    [[ ${HOME:-} == /* ]] || fail 'A Mac login home is required.'
    if [[ -n "$utm_app" ]]; then
        [[ "$utm_app" == /* && -d "$utm_app" ]] || fail 'Specify an installed UTM.app by absolute path.'
    fi
    if [[ -z "$vm_id" ]]; then
        [[ -z "$guest_ssh_dir" && -n "$upstreams" ]] ||
            fail 'Provide --upstreams to create a new Sphere VM.'
    elif [[ ! "$vm_id" =~ ^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$ ]]; then
        fail 'Specify the existing Sphere VM UUID with --vm-id.'
    elif [[ -n "$guest_ssh_dir" || -n "$upstreams" ]]; then
        [[ "$guest_ssh_dir" == /* && -f "$guest_ssh_dir/guest-ssh-key" &&
           -f "$guest_ssh_dir/guest-known-hosts" && -n "$upstreams" ]] ||
            fail 'Provide a pinned guest SSH directory and semicolon-separated upstream hosts.'
    fi
    if [[ -n "$upstreams" ]]; then
        [[ "$upstreams" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?(\;[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?)*$ ]] ||
            fail 'Invalid upstream list.'
    fi
fi

work=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/agpc-mac.XXXXXXXX")
install_stage=
utm_mount=
utm_stage=
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

installer=$0
[[ "$installer" == /* ]] || installer="$PWD/$installer"
gpgv=$(command -v gpgv || true)
if [[ -z "$gpgv" ]]; then
    gpgv=$(bootstrap_gpgv "$work")
fi

fetch "$release_url/$archive" "$work/$archive"
verify_sha "$work/$archive" "$archive_sha" 'release archive'
/usr/bin/tar -xOf "$work/$archive" agpc > "$work/agpc"
verify_sha "$work/agpc" "$controller_sha" 'controller'
fetch "$pages_url/medge-archive-keyring.gpg" "$work/keyring.gpg"
verify_sha "$work/keyring.gpg" "$keyring_sha" 'archive keyring'
# Detached signature for the exact preview.21 controller above.
# Freeze these bytes so Pages can promote another controller independently.
/bin/cat > "$work/agpc.asc" <<'PREVIEW_21_SIGNATURE'
-----BEGIN PGP SIGNATURE-----

iQIzBAABCAAdFiEErsqh3NrxnHt/6vDAgqDhgO2up6AFAmrt5/sACgkQgqDhgO2u
p6CHQxAAt3q9Nvp9q6qIqLfcPU+QVgcwKjPXfZLdnuLvhgho6VInXGxxpsAzrYWN
zR0f4+XAoZQCvT/EdikhQoA64YGY8oNyMVSv3zaye7Jm7UCE6oynB45XtQFKXMOh
qi/g0vz+lvARhd8Cfbqyp0tE0x+6aaJX/eT7HH6/1Poss5NcZpTpGi2csf9fR4kL
6Vl7MYSRQyKKkDkCTq3GWZTf1aLopyppk/D6YanlU9WgrhWfwfRYF4/cFhu3z8fh
WY6IC5y3LIZZDkvElGxATJKH6lt8yHr6IhKzioPdpsrg6Y4SERV6CoCFsQNRrafV
2Hpf0F03/zcWygsXN0urfvOogevh5leT7tynZAPqLQ/KFOkq9V5OvhUVz1/6/bzf
skfzgA3tuUwhB5ubsEMdUL+tLGrjfYMcHeL1GZUPZ0ynvRV0AWn6FR+c+Y4DO4tJ
q0MhnyviXR13Qoo4gUUT8K0Enrx3diDBBNRuN4XbtPJHfTae2lso/p3j/0o+a2z0
/dGm/bP/faiMOwsJX6gvzJZPszAc7/tDYx9GJq9y8oqDbWnKucqzK/SstlakdOts
JzV4jLihxjZMdYlQLrI5DYs1DMmshC9q95i97ljXJFOeZk/22ia0F2TFQAhdNkuC
4MK4YVi+VOarNSlkRPlYK9dRIDYRCaFTiPzgrH7itLTZbfuORHM=
=fhXu
-----END PGP SIGNATURE-----
PREVIEW_21_SIGNATURE
"$gpgv" --homedir "$work" --keyring "$work/keyring.gpg" "$work/agpc.asc" "$work/agpc" ||
    fail "Controller signature verification failed for $version."
printf 'Verified Apple Silicon controller %s.\n' "$version"
if [[ "$mode" == --verify && -n "${AGPC_READY_VERIFY_DIR:-}" ]]; then
    /bin/cp "$AGPC_READY_VERIFY_DIR/$proxy_archive" "$work/$proxy_archive"
    /bin/cp "$AGPC_READY_VERIFY_DIR/install-sphere-guest.sh" "$work/install-sphere-guest.sh"
else
    fetch "$ready_url/$proxy_archive" "$work/$proxy_archive"
    fetch "$ready_url/install-sphere-guest.sh" "$work/install-sphere-guest.sh"
fi
verify_sha "$work/$proxy_archive" "$proxy_sha" 'native proxy bundle'
verify_sha "$work/install-sphere-guest.sh" "$guest_sha" 'Sphere guest installer'
fetch "$ready_url/SHA256SUMS" "$work/ready-sums"
fetch "$ready_url/SHA256SUMS.asc" "$work/ready-sums.asc"
verify_sha "$work/ready-sums" "$ready_sums_sha" 'Mac Ready release checksums'
"$gpgv" --homedir "$work" --keyring "$work/keyring.gpg" "$work/ready-sums.asc" "$work/ready-sums" ||
    fail 'Mac Ready release signature verification failed.'
/usr/bin/grep -Fxq "$proxy_sha  $proxy_archive" "$work/ready-sums" ||
    fail 'The signed Mac Ready record lacks the pinned proxy bundle.'
/usr/bin/grep -Fxq "$guest_sha  install-sphere-guest.sh" "$work/ready-sums" ||
    fail 'The signed Mac Ready record lacks the pinned guest installer.'
for name in "${proxy_members[@]}"; do
    /usr/bin/tar -xOf "$work/$proxy_archive" "$name" > "$work/verify-member"
    verify_sha "$work/verify-member" "$(proxy_member_hash "$name")" "$name"
done
/bin/rm "$work/verify-member"
printf 'Verified B-channel proxy bundle and Sphere guest installer.\n'
[[ "$mode" == --install ]] || exit 0

verify_utm() {
    /usr/bin/codesign --verify --strict \
        -R='anchor apple generic and identifier "com.utmapp.UTM" and certificate leaf[subject.OU] = "WDNLXAD4W8"' \
        "$1" || fail 'UTM signature verification failed.'
}
if [[ -z "$utm_app" ]]; then
    if [[ -d /Applications/UTM.app ]]; then utm_app=/Applications/UTM.app
    else utm_app="$HOME/Applications/UTM.app"
    fi
fi
if [[ ! -d "$utm_app" ]]; then
    fetch "$utm_url" "$work/UTM.dmg"
    verify_sha "$work/UTM.dmg" "$utm_sha" 'UTM disk image'
    /bin/mkdir "$work/utm-mount"
    /usr/bin/hdiutil attach -readonly -nobrowse -mountpoint "$work/utm-mount" "$work/UTM.dmg" >/dev/null
    utm_mount="$work/utm-mount"
    verify_utm "$utm_mount/UTM.app"
    /bin/mkdir -p "$HOME/Applications"
    utm_stage=$(/usr/bin/mktemp -d "$HOME/Applications/.agpc-utm.XXXXXXXX")
    /usr/bin/ditto "$utm_mount/UTM.app" "$utm_stage/UTM.app"
    [[ ! -e "$utm_app" && ! -L "$utm_app" ]] || fail 'UTM appeared during installation.'
    /bin/mv "$utm_stage/UTM.app" "$utm_app"
fi
verify_utm "$utm_app"

managed_guest=
if [[ -z "$vm_id" ]]; then
    managed_guest="$HOME/Library/Application Support/AGPC/Sphere"
    # The SHA-256 pin comes from Canonical's signed release manifest.
    fetch "$ubuntu_url" "$work/ubuntu.img"
    verify_sha "$work/ubuntu.img" "$ubuntu_sha" 'Canonical Ubuntu amd64 image'
    vm_id=$(create_sphere_utm "$utm_app" "$managed_guest" "$work/ubuntu.img" \
        "$work/install-sphere-guest.sh" "$upstreams")
fi

[[ ${HOME:-} == /* ]] || fail 'A Mac login home is required.'
destination="$HOME/.local/bin"
target="$destination/agpc"
/bin/mkdir -p "$destination"
if [[ -e "$target" || -L "$target" ]]; then
    [[ -f "$target" && ! -L "$target" && -x "$target" ]] ||
        fail "Existing installation requires manual review: $target"
    verify_sha "$target" "$controller_sha" 'existing controller'
    printf 'Controller is already installed at %s\n' "$target"
else
    install_stage=$(/usr/bin/mktemp -d "$destination/.agpc.XXXXXXXX")
    /usr/bin/install -m 0755 "$work/agpc" "$install_stage/agpc"
    # Create the destination only if the name is still available.
    /bin/ln -h "$install_stage/agpc" "$destination/" || fail "Could not create $target."
    printf 'Installed controller preview at %s\n' "$target"
fi
printf 'To use agpc from any new zsh terminal, add %s to your PATH in ~/.zprofile.\n' "$destination"

login_directory="$HOME/Library/LaunchAgents"
support="$HOME/Library/Application Support/AGPC"
login_plist="$login_directory/$login_label.plist"
launcher="$support/start-sphere-utm"
domain="gui/$(/usr/bin/id -u)"
/bin/launchctl print "$domain" >/dev/null || fail 'Log in to the Mac desktop before installing startup.'
for directory in "$login_directory" "$support"; do
    /bin/mkdir -p "$directory"
    [[ ! -L "$directory" && -O "$directory" ]] || fail "Untrusted directory: $directory"
done

/bin/cat > "$work/start-sphere-utm" <<'START_SPHERE'
#!/bin/bash
set -euo pipefail

# UTM 5.0.8 needs its main window to initialize AppleScript after login.
# Open the window for startup and hide UTM once the guest is running.
utm_app=$1
/usr/bin/open -a "$utm_app"
/usr/bin/osascript -l JavaScript <<'WAIT_FOR_UTM'
ObjC.import("AppKit");
for (let i = 0; i < 30; i++) {
    const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier("com.utmapp.UTM");
    if (apps.count > 0 && apps.objectAtIndex(0).finishedLaunching) break;
    if (i === 29) throw Error("UTM did not finish launching.");
    delay(1);
}
WAIT_FOR_UTM
/usr/bin/osascript - "$2" "$utm_app" <<'APPLESCRIPT'
on run argv
    set sphereID to item 1 of argv
    set utmApp to item 2 of argv
    repeat with attempt from 1 to 4
        try
            with timeout of 30 seconds
                tell application id "com.utmapp.UTM"
                    set sphereVM to virtual machine id sphereID
                    set currentState to status of sphereVM
                    if currentState is stopped or currentState is paused then
                        start sphereVM
                        set currentState to status of sphereVM
                    end if
                    if currentState is started or currentState is starting or currentState is resuming then return
                    error "Sphere VM did not start: " & (currentState as text)
                end tell
            end timeout
        on error messageText number errorCode
            if attempt is 4 or errorCode is not in {-600, -609, -1712} then
                error messageText number errorCode
            end if
            do shell script "/usr/bin/open -a " & quoted form of utmApp
            delay 2
        end try
    end repeat
end run
APPLESCRIPT
/usr/bin/osascript -l JavaScript <<'JAVASCRIPT'
ObjC.import("AppKit");
const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier("com.utmapp.UTM");
if (apps.count > 0) {
    const app = apps.objectAtIndex(0);
    if (!app.hidden) app.hide;
}
JAVASCRIPT
START_SPHERE

staged_plist="$work/$login_label.plist"
/usr/bin/plutil -create xml1 "$staged_plist"
/usr/bin/plutil -insert Label -string "$login_label" "$staged_plist"
/usr/bin/plutil -insert ProgramArguments -array "$staged_plist"
/usr/bin/plutil -insert ProgramArguments.0 -string "$launcher" "$staged_plist"
/usr/bin/plutil -insert ProgramArguments.1 -string "$utm_app" "$staged_plist"
/usr/bin/plutil -insert ProgramArguments.2 -string "$vm_id" "$staged_plist"
/usr/bin/plutil -insert RunAtLoad -bool YES "$staged_plist"
/usr/bin/plutil -insert StandardErrorPath -string "$support/sphere-utm-error.log" "$staged_plist"
/usr/bin/plutil -lint "$staged_plist"

install_login_file() {
    local source=$1 destination=$2 permissions=$3
    if [[ -e "$destination" || -L "$destination" ]]; then
        [[ -f "$destination" && ! -L "$destination" && -O "$destination" ]] &&
            /usr/bin/cmp -s "$source" "$destination" ||
            fail "Existing startup file requires review: $destination"
    else
        /usr/bin/install -m "$permissions" "$source" "$destination"
    fi
}
if [[ -f "$launcher" && ! -L "$launcher" && -O "$launcher" ]]; then
    installed_launcher_sha=$(/usr/bin/shasum -a 256 "$launcher")
    case ${installed_launcher_sha%% *} in
        ff30934cc253b80f0644337d040b326b503f77cc1c0076d0ad74f7bc4d48923a|459ab95246f795c670723a287dbf7fad2730fc88fa5f82eb1c7f91424a909f3d)
            # Replace only launchers shipped by earlier installers.
            launcher_stage=$(/usr/bin/mktemp "$support/.start-sphere-utm.XXXXXXXX")
            /usr/bin/install -m 0755 "$work/start-sphere-utm" "$launcher_stage"
            /bin/mv -f "$launcher_stage" "$launcher"
            ;;
    esac
fi
install_login_file "$work/start-sphere-utm" "$launcher" 0755
install_login_file "$staged_plist" "$login_plist" 0644

if ! /bin/launchctl print "$domain/$login_label" >/dev/null 2>&1; then
    /bin/launchctl bootstrap "$domain" "$login_plist"
fi
printf 'Configured %s to start Sphere at macOS login.\n' "$login_label"
if [[ -n "$guest_ssh_dir" ]]; then
    # A pinned host key is required before sending the root guest installer.
    # OpenSSH splits UserKnownHostsFile on whitespace, so use a private copy.
    /bin/cp "$guest_ssh_dir/guest-known-hosts" "$work/guest-known-hosts"
    ssh_guest=(/usr/bin/ssh -F /dev/null -p 22242 -i "$guest_ssh_dir/guest-ssh-key"
        -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes
        -o "UserKnownHostsFile=\"$work/guest-known-hosts\""
        -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=5 agpcbuild@127.0.0.1)
    guest_deadline=$((SECONDS+120))
    while ((SECONDS<guest_deadline)); do
        if "${ssh_guest[@]}" true 2>"$work/guest-ssh-error"; then break; fi
        /bin/sleep 2
    done
    if ((SECONDS>=guest_deadline)); then /bin/cat "$work/guest-ssh-error" >&2; fi
    ((SECONDS<guest_deadline)) || fail 'The pinned UTM guest did not become reachable.'
    "${ssh_guest[@]}" "sudo -n /bin/bash -s -- --install '$upstreams'" < "$work/install-sphere-guest.sh"
fi

if [[ -n "$managed_guest" ]]; then
    /bin/cp "$managed_guest/known-hosts" "$work/guest-known-hosts"
    ssh_guest=(/usr/bin/ssh -F /dev/null -p 22242 -i "$managed_guest/guest-client"
        -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes
        -o "UserKnownHostsFile=\"$work/guest-known-hosts\""
        -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=5 agpc-check@127.0.0.1)
    guest_deadline=$((SECONDS+420))
    until "${ssh_guest[@]}" 'test "$(hostname)" = agpc-sphere && systemctl is-active --quiet agpc-sphere-mbstack.service && systemctl is-active --quiet agpc-sphere-dc.service' 2>"$work/guest-ssh-error"; do
        if ((SECONDS>=guest_deadline)); then
            /bin/cat "$work/guest-ssh-error" >&2
            fail 'The verified Sphere guest did not finish provisioning. Inspect cloud-init in UTM.'
        fi
        /bin/sleep 3
    done
    printf '%s\n' 'Sphere mbStack and DC are active in the verified guest.'
fi
/usr/bin/sudo /bin/bash "$installer" --install-proxy-startup "$work/$proxy_archive"
for ((i=0; i<90; i++)); do
    if [[ -S "$proxy_runtime/run/ssh.sock" ]] &&
       /bin/launchctl print "system/$proxy_label" | /usr/bin/grep -q '^[[:space:]]*state = running$'; then
        printf 'B-channel SSH proxy is running. Open a new login session if your group membership was just added.\n'
        exit 0
    fi
    /bin/sleep 2
done
fail "Startup is configured, but B-channel SSH did not become ready. Check the UTM guest services and $support/sphere-utm-error.log."
