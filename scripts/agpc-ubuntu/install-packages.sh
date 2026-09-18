#!/bin/bash
set -euo pipefail
. /etc/os-release
[[ "$ID:$VERSION_ID:$(dpkg --print-architecture)" == ubuntu:26.04:amd64 ]]
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
# Build-time package installation only; no host services start in image layers.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 0755 /usr/sbin/policy-rc.d
apt-get update
apt-get install -y --no-install-recommends ca-certificates gnupg python3 systemd systemd-sysv
printf '%s\n' '756fc2632c307509b8e5ece665ced7f4d1a58636ac935aefc1e017f7dcfcbfbd  /usr/share/keyrings/medge-archive-keyring.gpg' | sha256sum -c -
sed 's@/etc/apt/keyrings/medge-archive-keyring.gpg@/usr/share/keyrings/medge-archive-keyring.gpg@' \
    /etc/apt/sources.list.d/medge.sources.pending > /etc/apt/sources.list.d/medge.sources
python3 - <<'PY'
import json,pathlib
lock=json.loads(pathlib.Path('/usr/share/agpc-build/package-lock.json').read_text())
packages=lock['release']['packages']
preferences=[]
for item in packages:
    preferences.append(f"Package: {item['name']}\nPin: version {item['version']}\nPin-Priority: 1001\n")
pathlib.Path('/etc/apt/preferences.d/agpc').write_text('\n'.join(preferences))
PY
apt-get update
# Headless core already depends on Sphere, Mote, CX-Mesh and AGOS. No UI bundle
# or non-redistributable Obsidian payload is incorporated into the public image.
apt-get install -y --no-remove --no-install-recommends agent-sphere=0.2.0-15 agpc-manager=3.3.0-1
test -z "$(dpkg --audit)"
python3 - <<'PY'
import json,pathlib,subprocess
root=pathlib.Path('/usr/share/agpc-build')
lock=json.loads((root/'package-lock.json').read_text())
installed={}
for item in lock['release']['packages']:
    result=subprocess.run(['dpkg-query','-W','-f=${Status}\t${Version}',item['name']],capture_output=True,text=True)
    if result.returncode == 0 and result.stdout.startswith('install ok installed\t'):
        version=result.stdout.split('\t')[1]
        assert version==item['version'],item['name']+' version differs from release lock'
        installed[item['name']]=version
required={'agent-sphere','agpc-manager','sphered','moted','mote-proxy','mote-transportd','cx-mesh','agos','cx-loop','mote-mcpd'}
assert required <= set(installed), 'required core package missing'
(root/'installed.json').write_text(json.dumps({'os':'ubuntu','version':'26.04','arch':'amd64','packages':installed,'runtime_ready':False,'mac_ssh_bridge':'not-configured'},indent=2)+'\n')
PY
rm -f /usr/sbin/policy-rc.d /etc/apt/sources.list.d/medge.sources.pending
apt-get clean
# Image clones must not inherit build-time OS/SSH identities. Runtime bootstrap
# still has to generate identities and wire Mac SSH before admission.
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub
