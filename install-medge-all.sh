#!/usr/bin/env bash
set -Eeuo pipefail

release_tag="deb-v2026.08.25-1"
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

for command_name in awk cat curl dpkg dpkg-deb dpkg-query grep sha256sum apt-get; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Required command is missing: $command_name" >&2
    exit 1
  }
done

desk_topology=/etc/mote/desk/desk-mchat.env
if [[ -e "$desk_topology" ]]; then
  if [[ ! -f "$desk_topology" || -L "$desk_topology" ]]; then
    echo "MDesk locked topology is not a regular non-symlink file: $desk_topology" >&2
    exit 1
  fi
  desk_appname="$(awk -F= '$1 == "MCHAT_APPNAME" { print substr($0, index($0, "=") + 1) }' "$desk_topology")"
  if [[ "$desk_appname" != mdesk-app ]]; then
    echo "MDesk cannot be installed: locked topology uses MCHAT_APPNAME=${desk_appname:-missing}, but mdesk 2.1.0-9 requires mdesk-app." >&2
    echo "The installer will not alter the locked file. Remove any half-configured mdesk and medge-all packages; do not rerun this bundle until the desktop migration is released." >&2
    exit 1
  fi
fi

package_dir="$(mktemp -d /var/tmp/medge-all.XXXXXX)"
chmod 0755 "$package_dir"
packagekit_stopped=0

cleanup() {
  local command_status=$?

  find "$package_dir" -depth -delete
  if (( packagekit_stopped == 1 )); then
    echo "Restoring packagekit.service." >&2
    systemctl start packagekit.service ||
      echo "Warning: packagekit.service could not be restarted." >&2
  fi

  trap - EXIT
  exit "$command_status"
}
trap cleanup EXIT

apt_with_lock_retry() {
  local attempt=1
  local command_status
  local error_log="${package_dir}/apt-error.log"

  while true; do
    : >"$error_log"
    if "$@" 2>"$error_log"; then
      if [[ -s "$error_log" ]]; then
        cat "$error_log" >&2
      fi
      return 0
    else
      command_status=$?
    fi

    cat "$error_log" >&2
    if ! grep -Eq 'Could not get lock|Unable to (acquire|lock)' "$error_log"; then
      return "$command_status"
    fi
    if (( packagekit_stopped == 0 )) &&
      grep -Eq 'held by process [0-9]+ \(packagekitd\)' "$error_log" &&
      command -v systemctl >/dev/null 2>&1; then
      echo "APT is locked by packagekitd; temporarily stopping packagekit.service." >&2
      if systemctl stop packagekit.service; then
        packagekit_stopped=1
        sleep 2
        continue
      fi
      echo "packagekit.service could not be stopped; continuing bounded retries." >&2
    fi
    if (( attempt >= 60 )); then
      echo "APT remained locked after five minutes; no lock file was removed." >&2
      return "$command_status"
    fi

    echo "APT is busy; waiting five seconds before retry ${attempt}/60." >&2
    ((attempt += 1))
    sleep 5
  done
}

packages=(
  sphere_4.0.0-1_amd64.deb
  moted_3.0.0-2_amd64.deb
  medge_1.0.0-3_all.deb
  mote-proxy_1.0.0-2_all.deb
  motemcp_1.0.0-2_all.deb
  medge-core_1.0.0-3_all.deb
  mdesk_2.1.0-9_amd64.deb
  ss-webos_2.0.0-8_amd64.deb
  cx-node_0.3.1-4_amd64.deb
  medge-all_1.0.0-3_all.deb
)

package_paths=()
for package_name in "${packages[@]}"; do
  package_path="${package_dir}/${package_name}"
  curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
    --output "$package_path" "${release_base}/${package_name}"
  chmod 0644 "$package_path"
  package_id="$(dpkg-deb -f "$package_path" Package)"
  candidate_version="$(dpkg-deb -f "$package_path" Version)"
  installed_status="$(dpkg-query -W -f='${Status}' "$package_id" 2>/dev/null || true)"
  installed_version="$(dpkg-query -W -f='${Version}' "$package_id" 2>/dev/null || true)"
  if [[ "$installed_status" == "install ok installed" ]] &&
    dpkg --compare-versions "$installed_version" gt "$candidate_version"; then
    echo "Keeping newer installed ${package_id} ${installed_version}; bundled version is ${candidate_version}." >&2
  else
    package_paths+=("$package_path")
  fi
done

curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
  --output "${package_dir}/SHA256SUMS" "${release_base}/SHA256SUMS"
chmod 0644 "${package_dir}/SHA256SUMS"

(
  cd "$package_dir"
  sha256sum --ignore-missing --check SHA256SUMS
)

apt_with_lock_retry apt-get update
DEBIAN_FRONTEND=noninteractive apt_with_lock_retry \
  apt-get install -y --no-install-recommends \
  "${package_paths[@]}"

dpkg-query -W -f='${Package}\t${Version}\t${Status}\n' \
  medge medge-core medge-all moted mote-proxy motemcp mdesk ss-webos cx-node

echo "MEdge All installation completed from ${release_tag}."
