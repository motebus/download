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

mapfile -t EXPECTED_PACKAGES < <(
    python3 - "$BUNDLE_DIR/release-manifest.json" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for package in manifest.get("packages", []):
    name = package.get("name")
    if not isinstance(name, str) or not name:
        raise SystemExit("release manifest contains an invalid package name")
    print(name)
PY
)
[[ ${#EXPECTED_PACKAGES[@]} -gt 0 ]] || {
    printf 'release manifest contains no packages: %s\n' "$BUNDLE_DIR" >&2
    exit 1
}

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
        -e "EXPECTED_PACKAGE_NAMES=${EXPECTED_PACKAGES[*]}" \
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

            # Establish the complete dependency-safe host baseline first.
            apt-get install -y --no-install-recommends /bundle/*.deb
            apt-get check

            # Reproduce the admitted corrective case: L2 can contain a newer,
            # unadmitted local motemcp build. The signed bundle must replace it
            # with the exact lower manifest version in the same package set.
            dpkg-deb -R /bundle/motemcp_1.1.0-2_all.deb /tmp/motemcp-higher
            sed -i "s/^Version: .*/Version: 1.1.0-3/" \
                /tmp/motemcp-higher/DEBIAN/control
            dpkg-deb -b /tmp/motemcp-higher /tmp/motemcp_1.1.0-3_all.deb
            dpkg -i /tmp/motemcp_1.1.0-3_all.deb
            test "$(dpkg-query -W -f="\${Version}" motemcp)" = 1.1.0-3

            apt-get install -y --allow-downgrades --no-install-recommends \
                /bundle/*.deb
            apt-get check

            for package_name in $EXPECTED_PACKAGE_NAMES; do
                dpkg-query -W -f="\${db:Status-Status} \${binary:Package} \${Version}\n" \
                    "$package_name"
            done
            test "$(dpkg-query -W -f="\${Version}" motemcp)" = 1.1.0-2

            test "$(stat -c "%U:%G:%a" /etc/ssh/ssh_config.d/50-mote-proxy.conf)" \
                = root:root:644
            test "$(stat -c "%U:%G:%a" /usr/libexec/mote-proxy/ssh-proxy)" \
                = root:root:755
            resolved_proxy_command="$(
                /usr/bin/ssh -G -F /etc/ssh/ssh_config \
                    sphere-installer-proxy-check.mote 2>/dev/null |
                    awk '\''
                        $1 == "proxycommand" {
                            proxy_commands += 1
                            $1 = ""
                            sub(/^[[:space:]]+/, "")
                            command = $0
                        }
                        END {
                            if (proxy_commands != 1 || command == "") exit 1
                            print command
                        }
                    '\''
            )"
            test "$resolved_proxy_command" \
                = "/usr/libexec/mote-proxy/ssh-proxy %h %p"
        '
    printf 'Ubuntu %s amd64 MEdge package compatibility passed\n' "$release"
}

run_target 24.04 \
    docker.io/library/ubuntu@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea
run_target 26.04 \
    docker.io/library/ubuntu@sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03
