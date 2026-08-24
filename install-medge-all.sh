#!/usr/bin/env bash
set -Eeuo pipefail

release_tag="deb-v2026.08.24-4"
release_base="https://github.com/motebus/medge-release/releases/download/${release_tag}"

if (( EUID != 0 )); then
  echo "Run this installer as root, for example: curl -fsSL <url> | sudo bash" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:24.04|ubuntu:26.04) ;;
  *)
    echo "Ubuntu 24.04 or 26.04 is required; found ${ID:-unknown} ${VERSION_ID:-unknown}." >&2
    exit 1
    ;;
esac

if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
  echo "amd64 is required." >&2
  exit 1
fi

for command_name in curl dpkg dpkg-query grep sha256sum apt-get; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Required command is missing: $command_name" >&2
    exit 1
  }
done

package_dir="$(mktemp -d /var/tmp/medge-all.XXXXXX)"
chmod 0755 "$package_dir"
trap 'find "$package_dir" -depth -delete' EXIT

packages=(
  sphere_4.0.0-1_amd64.deb
  moted_3.0.0-2_amd64.deb
  medge_1.0.0-3_all.deb
  mote-proxy_1.0.0-2_all.deb
  motemcp_1.0.0-2_all.deb
  medge-core_1.0.0-3_all.deb
  mdesk_2.1.0-9_amd64.deb
  ss-webos_2.0.0-8_amd64.deb
  cx-node_0.3.1-2_amd64.deb
  medge-all_1.0.0-3_all.deb
)

package_paths=()
for package_name in "${packages[@]}"; do
  package_path="${package_dir}/${package_name}"
  curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
    --output "$package_path" "${release_base}/${package_name}"
  chmod 0644 "$package_path"
  package_paths+=("$package_path")
done

curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
  --output "${package_dir}/SHA256SUMS" "${release_base}/SHA256SUMS"
chmod 0644 "${package_dir}/SHA256SUMS"

(
  cd "$package_dir"
  sha256sum --ignore-missing --check SHA256SUMS
)

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  "${package_paths[@]}"

dpkg-query -W -f='${Package}\t${Version}\t${Status}\n' \
  medge medge-core medge-all moted mote-proxy motemcp mdesk ss-webos cx-node

echo "MEdge All installation completed from ${release_tag}."
