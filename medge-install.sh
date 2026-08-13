#!/bin/sh
set -eu
BASE_URL="https://motebus.github.io/medge-release"
TEMP_INSTALLER="$(mktemp /tmp/medge-bootstrap.XXXXXX)"
trap 'rm -f "$TEMP_INSTALLER"' EXIT HUP INT TERM
curl --proto '=https' --tlsv1.2 -fsSLo "$TEMP_INSTALLER" "$BASE_URL/install.sh"
MEDGE_INSTALL_PROFILE=medge exec sh "$TEMP_INSTALLER"
