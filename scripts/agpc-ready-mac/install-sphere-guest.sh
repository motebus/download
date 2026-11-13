#!/bin/bash
# Install the pinned Sphere components inside a dedicated Linux amd64 UTM guest.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

fail() { printf 'Sphere guest: %s\n' "$*" >&2; exit 1; }
mode=${1:---verify}
case "$mode" in
    --verify) [[ $# -le 1 ]] || fail 'Usage: install-sphere-guest.sh --verify' ;;
    --install) [[ $# == 2 && $2 =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?(\;[a-zA-Z0-9][a-zA-Z0-9.-]*(:[0-9]+)?)*$ ]] ||
        fail 'Usage: install-sphere-guest.sh --install UPSTREAMS (semicolon-separated hosts).' ;;
    *) fail 'Choose --verify or --install.' ;;
esac
[[ $(uname -s) == Linux && $(dpkg --print-architecture) == amd64 ]] ||
    fail 'Use the Linux amd64 Sphere guest.'
if [[ "$mode" == --install ]]; then
    [[ $EUID == 0 ]] || fail 'Run guest installation with administrator privileges.'
    /usr/sbin/ip -4 -o addr show | grep -q ' 10\.0\.2\.15/' ||
        fail 'The guest does not have the expected UTM gateway address.'
    [[ $(/usr/bin/node --version) == v22.* ]] || fail 'Install Node.js 22 from the guest OS first.'
fi

work=$(mktemp -d)
dc_stage=
cleanup() {
    rm -r -- "$work"
    if [[ -n "$dc_stage" ]]; then rm -r -- "$dc_stage"; fi
}
trap cleanup EXIT
fetch() {
    local name=$1 url=$2 sha=$3
    curl --fail --silent --show-error --location --proto '=https' \
        --proto-redir '=https' --connect-timeout 15 --max-time 120 --output "$work/$name" "$url"
    printf '%s  %s\n' "$sha" "$work/$name" | sha256sum --check --status ||
        fail "SHA-256 mismatch for $name."
}

fetch libssl.deb https://snapshot.debian.org/file/65ba06d39628536d27e45867f4c937c5df361309 \
    dcc68a543de6cb955a57077b66dcdb15f61d1e31e072f2c6cc4082c37da1b00d
fetch mbstack.deb https://github.com/motebus/download/releases/download/agpc-mac-deb-v2.6.7-1-preview1/agpc-mac_2.6.7-1.preview1_amd64.deb \
    f5f46b5814f82b988e204ca30f99884f2b2a061ae3aeb034229bb764b7a7f5af
fetch sphered.deb https://github.com/motebus/download/releases/download/agent-computer-v0.3.0-87/sphered_4.1.0-2_amd64.deb \
    38667a250b2108a9d93f0743a81892875043ec32b09a61206e33deabe9deeb9a

dpkg-deb --extract "$work/mbstack.deb" "$work/mbstack"
printf '%s  %s\n' 9f51844843430586759e0b43e0a7c8b39c3a312eb106b38b13f24b6937ff9815 \
    "$work/mbstack/usr/lib/agpc-mac/mbStack" | sha256sum --check --status ||
    fail 'mbStack executable does not match its source pin.'
dpkg-deb --extract "$work/sphered.deb" "$work/sphered"
dc_source="$work/sphered/usr/lib/sphered/dc"
[[ -f "$dc_source/bin/dc" && -f "$dc_source/conf/config.json" && -f "$dc_source/node_modules/motebus/index.js" ]] ||
    fail 'The verified package is missing its standalone DC payload.'
printf '%s\n' 'Verified Linux amd64 mbStack, libssl1.1, and DC packages.'
[[ "$mode" == --install ]] || exit 0

exec 9>/run/lock/agpc-sphere-guest.lock
flock -x 9
dc_root=/opt/agpc-sphere-dc-3.0.2
profile=/var/lib/agpc-sphere/mbstack
account=agpc-sphere
if [[ -e "$dc_root" || -L "$dc_root" ]]; then
    [[ -d "$dc_root" && ! -L "$dc_root" ]] && diff -qr "$dc_source" "$dc_root" >/dev/null ||
        fail "Existing DC payload requires review: $dc_root"
fi

cat > "$work/agpc-sphere-mbstack.service" <<UNIT
[Unit]
Description=AGPC Sphere mbStack
Wants=network-online.target
After=network-online.target

[Service]
User=$account
Group=$account
WorkingDirectory=$profile
ExecStart=/usr/lib/agpc-mac/mbStack -m 0 -g1 off -g2 10.0.2.15:6262 -d $profile -w 0 -i off -x off -u "$2"
UMask=0077
NoNewPrivileges=yes
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
UNIT
cat > "$work/agpc-sphere-dc.service" <<UNIT
[Unit]
Description=AGPC Sphere DC
Requires=agpc-sphere-mbstack.service
After=agpc-sphere-mbstack.service
PartOf=agpc-sphere-mbstack.service

[Service]
User=$account
Group=$account
WorkingDirectory=$dc_root
Environment=DCAPP_MBGWIP=127.0.0.1:6262
Environment=DCAPP_IOC=ioc
Environment=DCAPP_WATCHLEVEL=0
ExecStartPre=/usr/bin/timeout 30s /bin/bash -c 'until (: >/dev/tcp/127.0.0.1/6262) 2>/dev/null; do /bin/sleep 1; done'
ExecStart=/usr/bin/node $dc_root/bin/dc
UMask=0077
NoNewPrivileges=yes
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
UNIT

for name in agpc-sphere-mbstack agpc-sphere-dc; do
    target="/etc/systemd/system/$name.service"
    if [[ -e "$target" || -L "$target" ]]; then
        [[ -f "$target" && ! -L "$target" ]] && cmp -s "$work/$name.service" "$target" ||
            fail "Existing service requires review: $target"
    fi
done

existing=$(dpkg-query -W -f='${Version}' agpc-mac 2>/dev/null || true)
[[ -z "$existing" || "$existing" == '2.6.7-1~preview1' ]] ||
    fail 'The guest already has a different agpc-mac package.'
if ! dpkg-query -W -f='${db:Status-Status}\n' libssl1.1:amd64 2>/dev/null | grep -qx installed; then
    dpkg -i "$work/libssl.deb"
fi
if ! dpkg-query -W -f='${db:Status-Status}\n' agpc-mac 2>/dev/null | grep -qx installed; then
    dpkg -i "$work/mbstack.deb"
fi
cmp -s "$work/mbstack/usr/lib/agpc-mac/mbStack" /usr/lib/agpc-mac/mbStack ||
    fail 'Installed mbStack differs from the verified package.'
if ! id "$account" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/agpc-sphere --shell /usr/sbin/nologin "$account"
fi
[[ $(getent passwd "$account" | cut -d: -f6-7) == '/var/lib/agpc-sphere:/usr/sbin/nologin' &&
    $(id -gn "$account") == "$account" ]] || fail 'The existing Sphere service account differs.'
install -d -m 0755 -o root -g root /var/lib/agpc-sphere
install -d -m 0700 -o "$account" -g "$account" "$profile"
if [[ ! -d "$dc_root" ]]; then
    dc_stage=$(mktemp -d /opt/.agpc-sphere-dc.XXXXXXXX)
    cp -a -- "$dc_source" "$dc_stage/dc"
    mv -T -- "$dc_stage/dc" "$dc_root"
fi
for name in agpc-sphere-mbstack agpc-sphere-dc; do
    install -m 0644 -o root -g root "$work/$name.service" "/etc/systemd/system/$name.service"
done
systemctl daemon-reload
systemctl enable --now agpc-sphere-mbstack.service agpc-sphere-dc.service
for name in agpc-sphere-mbstack agpc-sphere-dc; do
    systemctl is-active "$name.service"
done
