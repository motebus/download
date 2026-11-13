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
       bash agpc-ready-mac.sh --install --utm-app /path/to/UTM.app --vm-id UUID
       bash agpc-ready-mac.sh --install --utm-app /path/to/UTM.app --vm-id UUID \
           --guest-ssh-dir DIRECTORY --upstreams 'HOST1;HOST2'
  --plan       Print requirements. Default.
  --verify     Verify the controller and pinned Mac and Linux installer assets.
  --install    Configure the Linux amd64 Sphere guest to start at login and
               install the native B-channel proxy to start at system boot.

Use an existing UTM app and dedicated Linux amd64 VM. For a guest without
mbStack and DC, use --guest-ssh-dir and --upstreams. The directory holds
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
        --proto-redir '=https' --connect-timeout 15 --max-time 120 \
        --output "$2" "$1" || fail "Could not download $1."
}

cleanup() {
    local file
    if [[ -n "$install_stage" ]]; then
        if [[ -f "$install_stage/agpc" ]]; then /bin/rm -- "$install_stage/agpc"; fi
        /bin/rmdir "$install_stage"
    fi
    for file in "$work/$archive" "$work/agpc" "$work/agpc.asc" "$work/keyring.gpg" \
        "$work/start-sphere-utm" "$work/$login_label.plist"; do
        if [[ -f "$file" ]]; then /bin/rm -- "$file"; fi
    done
    for file in "$work/$proxy_archive" "$work/install-sphere-guest.sh" "$work/guest-ssh-error" "$work/guest-known-hosts" "$work/verify-member"; do
        if [[ -f "$file" ]]; then /bin/rm -- "$file"; fi
    done
    /bin/rmdir "$work" || printf 'Temporary files remain in %s\n' "$work" >&2
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
    [[ "$utm_app" == /* && -d "$utm_app" && "$vm_id" =~ ^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$ ]] ||
        fail 'Specify --utm-app with an absolute path and --vm-id with the Sphere VM UUID.'
    [[ ${HOME:-} == /* ]] || fail 'A Mac login home is required.'
    /usr/bin/codesign --verify --strict \
        -R='anchor apple generic and identifier "com.utmapp.UTM" and certificate leaf[subject.OU] = "WDNLXAD4W8"' \
        "$utm_app" || fail 'UTM signature verification failed.'
    if [[ -n "$guest_ssh_dir" || -n "$upstreams" ]]; then
        [[ "$guest_ssh_dir" == /* && -f "$guest_ssh_dir/guest-ssh-key" &&
           -f "$guest_ssh_dir/guest-known-hosts" &&
           "$upstreams" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?(\;[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?)*$ ]] ||
            fail 'Provide a pinned guest SSH directory and semicolon-separated upstream hosts.'
    fi
fi
command -v gpgv >/dev/null 2>&1 || fail 'gpgv is required for archive signature verification.'

work=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/agpc-mac.XXXXXXXX")
install_stage=
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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
gpgv --homedir "$work" --keyring "$work/keyring.gpg" "$work/agpc.asc" "$work/agpc" ||
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
for name in "${proxy_members[@]}"; do
    /usr/bin/tar -xOf "$work/$proxy_archive" "$name" > "$work/verify-member"
    verify_sha "$work/verify-member" "$(proxy_member_hash "$name")" "$name"
done
/bin/rm "$work/verify-member"
printf 'Verified B-channel proxy bundle and Sphere guest installer.\n'
[[ "$mode" == --install ]] || exit 0

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

installer=$0
[[ "$installer" == /* ]] || installer="$PWD/$installer"
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
