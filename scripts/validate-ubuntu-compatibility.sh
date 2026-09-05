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

            # Reproduce the clean v2 migration from the retired package and
            # managed Codex server identity before installing the full bundle.
            install -d -m0755 /tmp/motemcp-legacy/DEBIAN /etc/codex
            printf "%s\n" \
                "Package: motemcp" \
                "Version: 1.1.0-2" \
                "Architecture: all" \
                "Maintainer: Compatibility Test <test@example.invalid>" \
                "Description: retired migration fixture" \
                > /tmp/motemcp-legacy/DEBIAN/control
            dpkg-deb -b /tmp/motemcp-legacy /tmp/motemcp_1.1.0-2_all.deb
            dpkg -i /tmp/motemcp_1.1.0-2_all.deb
            printf "%s\n" \
                "# BEGIN motemcp managed Codex MCP server" \
                "[mcp_servers.motemcp]" \
                "command = \"/usr/bin/mote\"" \
                "args = [\"mcp\", \"serve\"]" \
                "enabled = true" \
                "# END motemcp managed Codex MCP server" \
                > /etc/codex/config.toml
            test "$(dpkg-query -W -f="\${Version}" motemcp)" = 1.1.0-2

            # Exercise the physical Sphere rename using complete package defaults
            # plus an owner marker. The old conffile must survive byte-for-byte.
            install -d /tmp/sphere-legacy/DEBIAN /tmp/sphere-legacy/etc/mote/sphere
            dpkg-deb -x /bundle/sphered_*.deb /tmp/sphered-seed
            cp /tmp/sphered-seed/etc/mote/sphered/sphered-deb.env \
                /tmp/sphere-legacy/etc/mote/sphere/sphere-deb.env
            printf "\n# owner migration fixture\n" >> /tmp/sphere-legacy/etc/mote/sphere/sphere-deb.env
            chmod 0640 /tmp/sphere-legacy/etc/mote/sphere/sphere-deb.env
            printf "%s\n" "Package: sphere" "Version: 4.0.0-2" \
                "Architecture: all" "Maintainer: Test <test@example.invalid>" \
                "Description: physical rename fixture" >/tmp/sphere-legacy/DEBIAN/control
            printf "%s\n" /etc/mote/sphere/sphere-deb.env >/tmp/sphere-legacy/DEBIAN/conffiles
            dpkg-deb -b /tmp/sphere-legacy /tmp/sphere_4.0.0-2_all.deb
            dpkg -i /tmp/sphere_4.0.0-2_all.deb
            cp /etc/mote/sphere/sphere-deb.env /tmp/owner-sphere.env

            # Establish the complete dependency-safe host baseline. The new
            # package must replace, not provide or coexist with, the old name.
            apt-get install -y --allow-downgrades --no-install-recommends \
                /bundle/*.deb
            apt-get check
            cmp /tmp/owner-sphere.env /etc/mote/sphere/sphere-deb.env
            cmp /tmp/owner-sphere.env /etc/mote/sphered/sphered-deb.env
            test -f /var/lib/mote/sphered/sphere-migration.json
            test "$(dpkg-query -W -f="\${db:Status-Status}" sphere)" = config-files
            ! dpkg-query -W motemcp >/dev/null 2>&1
            expected_mcp_version="$(dpkg-deb -f /bundle/mote-bridge-mcp_*.deb Version)"
            test "$(dpkg-query -W -f="\${Version}" mote-bridge-mcp)" \
                = "$expected_mcp_version"
            grep -Fq "[mcp_servers.mote-bridge-mcp]" /etc/codex/config.toml
            ! grep -Fq "[mcp_servers.motemcp]" /etc/codex/config.toml

            printf "\n# owner edit after migration\n" >> /etc/mote/sphered/sphered-deb.env
            cp /etc/mote/sphered/sphered-deb.env /tmp/owner-sphered.env
            apt-get install -y --reinstall --allow-downgrades --no-install-recommends \
                /bundle/*.deb
            apt-get check
            cmp /tmp/owner-sphered.env /etc/mote/sphered/sphered-deb.env
            cmp /tmp/owner-sphere.env /etc/mote/sphere/sphere-deb.env

            for package_name in $EXPECTED_PACKAGE_NAMES; do
                dpkg-query -W -f="\${db:Status-Status} \${binary:Package} \${Version}\n" \
                    "$package_name"
            done
            test "$(dpkg-query -W -f="\${Version}" mote-bridge-mcp)" \
                = "$expected_mcp_version"

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
