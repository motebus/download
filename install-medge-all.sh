#!/usr/bin/env bash
set -euo pipefail
INSTALLER_URL="https://raw.githubusercontent.com/motebus/medge-release/main/medge-install.sh"
TEMP_INSTALLER="$(mktemp /tmp/medge-all-bootstrap.XXXXXX)"
trap 'rm -f "$TEMP_INSTALLER"' EXIT HUP INT TERM
curl --proto '=https' --tlsv1.2 -fsSLo "$TEMP_INSTALLER" "$INSTALLER_URL"
bash "$TEMP_INSTALLER"
