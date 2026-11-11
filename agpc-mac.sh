#!/bin/bash
# Local candidate for the Apple Silicon controller preview installer.
set -euo pipefail
umask 077

version=0.1.0-preview.21
archive="agpc-mac-arm64-${version}.tar.gz"
release_url="https://github.com/motebus/download/releases/download/agpc-native-v${version}"
pages_url=https://motebus.github.io/download
archive_sha=c9dfa15e6a23279596bd55b04cd2ec3b86f951e04926bc108dc84e0493460cdc
controller_sha=6ab5b3bcbd5f6e5df695d6885c4b971624e12171c8274ed14d794d6f63c01320
keyring_sha=756fc2632c307509b8e5ece665ced7f4d1a58636ac935aefc1e017f7dcfcbfbd

usage() {
    cat <<'EOF'
Usage: bash agpc-mac.sh [--plan | --verify | --install | --help]
Apple Silicon controller preview. Run as your Mac login user.
  --plan     Show the download and destination. Default.
  --verify   Check the release archive, executable and archive signature.
  --install  Verify and install the controller in ~/.local/bin.
  --help     Show usage.
Verification and installation require gpgv.
EOF
}

fail() {
    printf 'agpc-mac: %s\n' "$*" >&2
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
    for file in "$work/$archive" "$work/agpc" "$work/agpc.asc" "$work/keyring.gpg"; do
        if [[ -f "$file" ]]; then /bin/rm -- "$file"; fi
    done
    /bin/rmdir "$work"
}

[[ $# -le 1 ]] || { usage >&2; exit 2; }
mode=${1:---plan}
case "$mode" in
    --help|-h) usage; exit 0 ;;
    --plan)
        printf 'Apple Silicon controller %s\nSource: %s/%s\nDestination: ~/.local/bin/agpc\n' \
            "$version" "$release_url" "$archive"
        exit 0
        ;;
    --verify|--install) ;;
    *) usage >&2; exit 2 ;;
esac

[[ $(/usr/bin/uname -s) == Darwin && $(/usr/bin/uname -m) == arm64 ]] ||
    fail 'A native Apple Silicon macOS shell is required.'
[[ $(/usr/bin/id -u) -ne 0 ]] || fail 'Run without sudo.'
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
    exit 0
fi

install_stage=$(/usr/bin/mktemp -d "$destination/.agpc.XXXXXXXX")
/usr/bin/install -m 0755 "$work/agpc" "$install_stage/agpc"
# Create the destination only if the name is still available.
/bin/ln -h "$install_stage/agpc" "$destination/" || fail "Could not create $target."
printf 'Installed controller preview at %s\n' "$target"
