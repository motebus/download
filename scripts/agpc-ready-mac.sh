#!/bin/bash
# Apple Silicon controller and startup setup for an existing Sphere UTM guest.
set -euo pipefail
umask 077

version=0.1.0-preview.21
archive="agpc-mac-arm64-${version}.tar.gz"
release_url="https://github.com/motebus/download/releases/download/agpc-native-v${version}"
pages_url=https://motebus.github.io/download
archive_sha=c9dfa15e6a23279596bd55b04cd2ec3b86f951e04926bc108dc84e0493460cdc
controller_sha=6ab5b3bcbd5f6e5df695d6885c4b971624e12171c8274ed14d794d6f63c01320
keyring_sha=756fc2632c307509b8e5ece665ced7f4d1a58636ac935aefc1e017f7dcfcbfbd
proxy_prefix=/Library/AGPC/mote-proxy
proxy_plist="$proxy_prefix/com.agpc.mote-proxy.b.plist"
proxy_label=com.agpc.mote-proxy
login_label=com.agpc.sphere-utm

usage() {
    cat <<'EOF'
Usage: bash agpc-ready-mac.sh [--plan | --verify | --install | --help]
       bash agpc-ready-mac.sh --install --utm-app /path/to/UTM.app --vm-id UUID
       sudo bash agpc-ready-mac.sh --install-proxy-startup
  --plan                   Show controller and startup prerequisites. Default.
  --verify                 Verify the pinned controller with gpgv.
  --install                Install the controller and configure Sphere startup
                           in your macOS login session. Specify the existing
                           UTM app and the UUID of the provisioned Sphere VM.
  --install-proxy-startup  Enable the installed B-channel proxy at system boot.
The VM must already contain enabled mbStack and DC services. The Mac must
already have the verified native B-channel proxy binaries and service account.
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
    /bin/rmdir "$work" || printf 'Temporary files remain in %s\n' "$work" >&2
}

mode=${1:---plan}
if [[ $# -gt 0 ]]; then shift; fi
utm_app=
vm_id=
if [[ "$mode" == --install ]]; then
    while [[ $# -gt 0 ]]; do
        [[ $# -ge 2 ]] || fail "Missing value for $1."
        case "$1" in
            --utm-app) utm_app=$2 ;;
            --vm-id) vm_id=$2 ;;
            *) fail "Unknown argument $1." ;;
        esac
        shift 2
    done
fi
[[ $# -eq 0 ]] || { usage >&2; exit 2; }
case "$mode" in
    --help|-h) usage; exit 0 ;;
    --plan)
        printf 'Apple Silicon controller %s\nSource: %s/%s\nDestination: ~/.local/bin/agpc\n' \
            "$version" "$release_url" "$archive"
        printf '%s\n' 'Startup: an existing Sphere UTM guest at login and the installed B-channel proxy at boot.'
        exit 0
        ;;
    --verify|--install|--install-proxy-startup) ;;
    *) usage >&2; exit 2 ;;
esac

[[ $(/usr/bin/uname -s) == Darwin && $(/usr/bin/uname -m) == arm64 ]] ||
    fail 'A native Apple Silicon macOS shell is required.'

verify_proxy() {
    local path
    /usr/bin/id mote-proxy >/dev/null 2>&1 || fail 'The mote-proxy service account is missing.'
    for path in /Library/AGPC "$proxy_prefix" "$proxy_prefix/bin"; do
        [[ -d "$path" && ! -L "$path" && $(/usr/bin/stat -f '%Su:%Sg:%OLp' "$path") == root:wheel:755 ]] ||
            fail "Untrusted proxy directory: $path"
    done
    [[ -f "$proxy_plist" && ! -L "$proxy_plist" && $(/usr/bin/stat -f '%Su:%Sg:%OLp' "$proxy_plist") == root:wheel:644 ]] ||
        fail 'The root-owned B-channel proxy plist is missing.'
    for path in mote-proxy-b mote-ssh ssh-proxy; do
        local binary="$proxy_prefix/bin/$path"
        [[ -f "$binary" && ! -L "$binary" && $(/usr/bin/stat -f '%Su:%Sg:%OLp' "$binary") == root:wheel:755 ]] ||
            fail "Missing or untrusted proxy executable: $path"
    done
    verify_sha "$proxy_plist" ed16eb66c8963b5e95d40a21f987a6bcbf16ac40b396d2bb487db0b8c0d15804 "$proxy_label B-channel plist"
    verify_sha "$proxy_prefix/bin/mote-proxy-b" 566392f312163ae3eeb2d1e4962c62c11a1b889b0db40a2305666bf9bf7e3ccb mote-proxy-b
    verify_sha "$proxy_prefix/bin/mote-ssh" 68b91d861bb5f3be815f483f1b81668008d443afe99faaa0825d180994aded46 mote-ssh
    verify_sha "$proxy_prefix/bin/ssh-proxy" e691439dfa5b8bdc46c7ad5d0cb1fc188c5569e12e7cda46a014a4fec1f08b3c ssh-proxy
}

if [[ "$mode" == --install-proxy-startup ]]; then
    [[ $EUID -eq 0 ]] || fail 'Administrator authentication is required for the proxy LaunchDaemon.'
    verify_proxy
    daemon=/Library/LaunchDaemons/$proxy_label.plist
    system_stage=$(/usr/bin/mktemp -d /Library/LaunchDaemons/.agpc.XXXXXXXX)
    trap '/bin/rm -f -- "$system_stage/$proxy_label.plist"; /bin/rmdir "$system_stage"' EXIT
    /usr/bin/install -o root -g wheel -m 0644 "$proxy_plist" "$system_stage/$proxy_label.plist"
    /usr/bin/plutil -insert KeepAlive -bool YES "$system_stage/$proxy_label.plist"
    /usr/bin/plutil -insert ThrottleInterval -integer 15 "$system_stage/$proxy_label.plist"
    /usr/bin/plutil -lint "$system_stage/$proxy_label.plist"
    if [[ -e "$daemon" || -L "$daemon" ]]; then
        [[ -f "$daemon" && ! -L "$daemon" ]] &&
            /usr/bin/cmp -s "$system_stage/$proxy_label.plist" "$daemon" ||
            fail "Existing LaunchDaemon requires review: $daemon"
    else
        /bin/mv "$system_stage/$proxy_label.plist" "$daemon"
    fi
    /bin/launchctl enable "system/$proxy_label"
    if loaded=$(/bin/launchctl print "system/$proxy_label" 2>/dev/null); then
        if [[ "$loaded" != *"path = $daemon"* ]]; then
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
    verify_proxy
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
printf 'Enable system startup for the installed B-channel proxy with sudo bash "%s" --install-proxy-startup\n' "$0"
