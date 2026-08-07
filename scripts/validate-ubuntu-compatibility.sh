#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    printf 'usage: %s RELEASE_BUNDLE_DIRECTORY\n' "$0" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
command -v docker >/dev/null 2>&1 || {
    printf 'docker is required for Ubuntu compatibility validation\n' >&2
    exit 1
}

BUNDLE_DIR="$(realpath "$1")"
[[ -d "$BUNDLE_DIR" ]] || {
    printf 'release bundle directory does not exist: %s\n' "$BUNDLE_DIR" >&2
    exit 1
}

EXPECTED_PACKAGES=(
    sphered
    mgate
    ss-webos
    moted
    agos
    qbix
    qbix-func
    mote
    desk
    medge
)

for package_name in "${EXPECTED_PACKAGES[@]}"; do
    mapfile -t matches < <(
        find "$BUNDLE_DIR" -maxdepth 1 -type f \
            -name "${package_name}_*.deb" -print
    )
    [[ ${#matches[@]} -eq 1 ]] || {
        printf 'expected exactly one %s DEB in %s\n' \
            "$package_name" "$BUNDLE_DIR" >&2
        exit 1
    }
done

run_target() {
    local release="$1"
    local image_ref="$2"

    docker run --rm --pull=always --platform linux/amd64 --log-driver none \
        -e "EXPECTED_UBUNTU_RELEASE=$release" \
        -v "$BUNDLE_DIR:/bundle:ro" \
        "$image_ref" \
        bash -ceu '
            . /etc/os-release
            test "$ID" = ubuntu
            test "$VERSION_ID" = "$EXPECTED_UBUNTU_RELEASE"
            test "$(dpkg --print-architecture)" = amd64

            printf "#!/bin/sh\nexit 101\n" >/usr/sbin/policy-rc.d
            chmod 0755 /usr/sbin/policy-rc.d
            export DEBIAN_FRONTEND=noninteractive
            apt-get update
            apt-get install -y --no-install-recommends /bundle/*.deb
            apt-get check

            for package_name in \
                sphered mgate ss-webos moted agos qbix qbix-func mote desk medge
            do
                dpkg-query -W -f="\${db:Status-Status} \${binary:Package} \${Version}\n" \
                    "$package_name"
            done
        '
    printf 'Ubuntu %s amd64 MEdge package compatibility passed\n' "$release"
}

run_target 24.04 \
    docker.io/library/ubuntu@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea
run_target 26.04 \
    docker.io/library/ubuntu@sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03
