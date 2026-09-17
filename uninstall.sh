#!/usr/bin/env bash
set -euo pipefail
# Remove the reviewed native AGPC package set without purging data or configuration.
# Historical signed uninstall assets remain immutable under legacy/.
mode=interactive
if [[ $# -gt 1 ]]; then echo 'Usage: uninstall.sh [--plan|--yes]' >&2; exit 1; fi
if [[ $# == 1 ]]; then
    case "$1" in
        --plan|--yes) mode=$1 ;;
        --help|-h) echo 'Usage: sudo bash uninstall.sh [--plan|--yes]'; exit 0 ;;
        *) echo 'Unknown uninstall option.' >&2; exit 1 ;;
    esac
fi
[[ $(id -u) == 0 ]] || { echo 'Run with sudo or as root.' >&2; exit 1; }
. /etc/os-release
case "$ID:$VERSION_ID:$(dpkg --print-architecture)" in
    ubuntu:24.04:amd64|ubuntu:26.04:amd64) ;;
    *) echo 'Ubuntu 24.04 or 26.04 amd64 is required.' >&2; exit 1 ;;
esac
export LC_ALL=C
for tool in python3 curl gpg gpgv apt-get dpkg-query dpkg-divert mktemp; do command -v "$tool" >/dev/null; done
stage=$(mktemp -d /tmp/agpc-uninstall.XXXXXXXX)
cleanup() {
    python3 - "$stage" <<'PY_CLEANUP'
import os,shutil,sys
from pathlib import Path
p=Path(sys.argv[1])
if p.parent != Path('/tmp') or not p.name.startswith('agpc-uninstall.') or p.is_symlink() or p.stat().st_uid != os.geteuid():
    raise SystemExit('Unexpected uninstall temporary directory.')
shutil.rmtree(p)
PY_CLEANUP
}
trap cleanup EXIT
export GNUPGHOME="$stage/gnupg"
mkdir -m 0700 "$GNUPGHOME"
base=https://motebus.github.io/download
for name in medge-archive-keyring.gpg agent-computer-apt-overlay.json agent-computer-apt-overlay.json.asc; do
    curl -fsSL --retry 3 --connect-timeout 20 --max-time 180 "$base/$name" -o "$stage/$name"
done
fingerprint=$(gpg --batch --show-keys --with-colons "$stage/medge-archive-keyring.gpg" | awk -F: '$1=="pub" {count++} $1=="fpr" && fingerprint=="" {fingerprint=$10} END {if (count!=1 || fingerprint=="") exit 1; print fingerprint}')
[[ $fingerprint == AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0 ]] || { echo 'Archive fingerprint mismatch.' >&2; exit 1; }
gpgv --keyring "$stage/medge-archive-keyring.gpg" "$stage/agent-computer-apt-overlay.json.asc" "$stage/agent-computer-apt-overlay.json"
cat >"$stage/engine.py" <<'PY_UNINSTALL_PREFLIGHT'
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

POLICY = {'agent-sphere': {'version': '0.2.0-13',
                  'architecture': 'all',
                  'sha256': 'fefc1d6010a297d1712e66519bf52d2c7a2165e159e6aee6ab7e07cef72dcb95',
                  'hooks': {'prerm': '1bd6bdbedefa3da7e7d776d186f2a6905f65d622e6d79d2d4822cb25aedca79d',
                            'postrm': '1bb6bcd08933a82ea83ece4395fa4e144418bd78395d6e84073918d7d28ea370'},
                  'units': ['agentsphere.target'],
                  'retained_payloads': []},
 'agent-ultra': {'version': '0.1.0-1',
                 'architecture': 'all',
                 'sha256': 'a84502dc1730f066269a9f75acbaa7ba5fd20e25d8e9f4d0c85535f98ee9e60d',
                 'hooks': {'prerm': 'b69eba2defbcaf3a94dd6d5e769a16a7029dd66ac1bb0e94045c0544f2543167',
                           'postrm': 'c88fd25ee684fefa483e660a9210d2a262421f4c363c31f8ae0810baba99fce5'},
                 'units': ['agentsphere-local.target'],
                 'retained_payloads': []},
 'agpc-manager': {'version': '3.3.0-1',
                  'architecture': 'amd64',
                  'sha256': '044e4f7431a6b0bf7e905658ddc82e9232ad3127dea1c295c030b788eb4077b0',
                  'hooks': {'prerm': None, 'postrm': None},
                  'units': [],
                  'retained_payloads': []},
 'agent-apps': {'version': '0.2.0-3',
                'architecture': 'all',
                'sha256': '79c245e88939c39e8936b096c81d9c59a76533d7d25583d8aa4a3145f242b777',
                'hooks': {'prerm': None, 'postrm': None},
                'units': [],
                'retained_payloads': []},
 'sphered': {'version': '4.1.0-2',
             'architecture': 'amd64',
             'sha256': '38667a250b2108a9d93f0743a81892875043ec32b09a61206e33deabe9deeb9a',
             'hooks': {'prerm': 'd56e35fe5b3738e7e385e7e50e3729aedd9857ccd5214fe61b21c4ac55a47e9f',
                       'postrm': '5f24b1d80445debec0e1fcf4f692ce0029d4494bfbdd8077edd15d8cec138ca3'},
             'units': ['sphered-dc.service',
                       'sphered-motebus.service',
                       'sphered.service'],
             'retained_payloads': []},
 'moted': {'version': '3.6.0-2',
           'architecture': 'amd64',
           'sha256': 'dd5aae37ecda299b1e0dcd85c96af4f5ba7f7a83e08bf8ee75f2dc7d54602c55',
           'hooks': {'prerm': '06417d4752bdad767de25177e4c4e79a4dd2cd2c1e880e33b4a9bd468f650e04',
                     'postrm': '7dc2190bba29dbb3b3a1a84c620df4c9bf672c1c170c395968f01ce98c34fad7'},
           'units': ['moted-ssh-relay.service', 'moted.service'],
           'retained_payloads': ['/usr/share/moted/bootstrap/moted-mchat.env']},
 'mote-proxy': {'version': '2.0.0-5',
                'architecture': 'amd64',
                'sha256': '469f8a794a975b704f3886bf0d149cf81289b4c56145c9f45a781bbf4d8a3548',
                'hooks': {'prerm': '41c68e5fadb7cdc90b9e97d080c3291d4be10ab072079ba62e406c365b571d1c',
                          'postrm': 'cc16f50e01db6295410191a0b8b933093c15079acdad5f5e6f7dd2886da18a63'},
                'units': ['mote-proxy.service'],
                'retained_payloads': ['/usr/share/mote-proxy/mote-proxy-mchat.env']},
 'mote-transportd': {'version': '2.0.0-6',
                     'architecture': 'amd64',
                     'sha256': '9c56cade3f014f75876cce126d2ef8c9d5c27a60709ff592ac0e9af9788dd23f',
                     'hooks': {'prerm': '9c95bf7700ef883cc4b1c72f08acc3157c5b0c985b26b886f5ef75f1a326f971',
                               'postrm': 'cf73683ae90ccb2baf53958611792b38d892e817acc0b07cfc17f570d1e859bd'},
                     'units': ['mote-transportd.service'],
                     'retained_payloads': ['/usr/share/mote-chatd/bootstrap/mote-chatd-mchat.env']},
 'mlink': {'version': '2.1.0-1',
           'architecture': 'amd64',
           'sha256': '3b0e996d4971b21813fb78806d54e6fd127094987e04d73e842804ea3712cb5d',
           'hooks': {'prerm': 'd571937ab51ce7ce9e4e359f9e117353dfdf006cca418c33a83b898782a43058',
                     'postrm': '7cca6100c3c2f7fe0232f3a31f7a515c024a06182c764ad874c88232f40dbdb6'},
           'units': ['mlink.service'],
           'retained_payloads': []},
 'mote-secd': {'version': '1.0.0-2',
               'architecture': 'amd64',
               'sha256': '043fd2fe86dfe83d17f9ab6e7e82ca96d1423e0697c3b4a0549cbd7f6e4998c2',
               'hooks': {'prerm': 'baef7ed74ecd1335ed05319e20deb09acb7848e6e9eca5990a1a94ba15fe8679',
                         'postrm': '8aecd5e33641ebd39963791a35efb155efe4e48430c13fa3d5874c7cfa1c37a9'},
               'units': ['mote-secd.service'],
               'retained_payloads': []},
 'agos': {'version': '2.1.0-1',
          'architecture': 'amd64',
          'sha256': 'd844937d8d11579b9c3a7cfa18dbdcd08b19c40c93ec22947fafb58d43c6db8e',
          'hooks': {'prerm': 'd44755ce320a5ee73833fe3014107640c3ea282ab168f56a602aeec458ad103f',
                    'postrm': 'c2a302d2e51db5e3337a64a27e3d5511b9c7f670372f208ad4597f0372ea2921'},
          'units': ['agosd.service'],
          'retained_payloads': []},
 'model-router': {'version': '0.1.0-1',
                  'architecture': 'amd64',
                  'sha256': 'fd07180fc952a6333e085c4b666683caa7185cd0f1b37da7c07ce694b3ad3b39',
                  'hooks': {'prerm': '89ae9a62899ba5db825139432183ddc83bdbbd443965d000f0601683176dc215',
                            'postrm': '9d2006b8d2a661b29a440b1228d71809c75bdd584d3324ee9a52425dd397e3e4'},
                  'units': ['model-router.service'],
                  'retained_payloads': []},
 'model-llm': {'version': '0.1.0-3',
               'architecture': 'amd64',
               'sha256': '8f044d0b23325a213b372087c9ef35daf9e9058df4bb7a783a0edc6945bc32ef',
               'hooks': {'prerm': 'cb5bbab156a108e8ced29ff633b31dadcdf2a4f84202c2043ad6cf86b39b2084',
                         'postrm': '22251966a82cf64bd97a2f9bad5931a4780395bd596239facecc1184e2e19850'},
               'units': ['model-llm.service'],
               'retained_payloads': []},
 'mote-mcpd': {'version': '3.1.0-1',
               'architecture': 'amd64',
               'sha256': 'fae185fc735571c73adee70fb3095851541fce3a7b13b468c41cae32bec44a60',
               'hooks': {'prerm': '80f037914c383c42138d20efcf079f443ae029677d129f6c7a9c4b44cf8c6821',
                         'postrm': None},
               'units': [],
               'retained_payloads': ['/usr/share/mote-bridge-mcp/bootstrap/mote-bridge-mcp-mchat.env']},
 'mote-mcp-ultra': {'version': '0.1.0-1',
                    'architecture': 'amd64',
                    'sha256': 'ac9dcda941181da26d16a32bc26053f851011213322e5c7af24bc5e13c392c9e',
                    'hooks': {'prerm': None, 'postrm': None},
                    'units': [],
                    'retained_payloads': []},
 'cx-mesh': {'version': '2.0.0-1',
             'architecture': 'amd64',
             'sha256': '7e7e9e36f79c3a406bfb987bc18b2055ec8306cd5c3508fd88614f1d0ae2e89e',
             'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                       'postrm': '1d01229f94d330318179b7ab73c092daf8b776d31082fe4a8ea03d6e19610238'},
             'units': ['cx-mesh.service'],
             'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
 'cx-loop': {'version': '0.1.0-4',
             'architecture': 'amd64',
             'sha256': '2a2a96c074dcd7b398ecb4cc9ababcf859a91b26375276fe17ee4368aa1de474',
             'hooks': {'prerm': '908d0beb77fe0a2f48232f44191985448a2416d7bb45e15a21d3b794360251b9',
                       'postrm': '0937292654dbd9689b3fe473673228b184097321ccd8a40fc0132e226ac32a53'},
             'units': ['cx-loopd.service'],
             'retained_payloads': []},
 'redixs': {'version': '4.1.0-1',
            'architecture': 'amd64',
            'sha256': '61d1b98c77ff65ad18829a09215bf75357d1acd4b9a9efa79c6ad1b6dd9c28c7',
            'hooks': {'prerm': '34c7a16b18097f5046caaee88fb263a6c72630353d862067969bf2de153c1e90',
                      'postrm': 'd4d4642da6ef80f3fd7eb428be065a074cc75544858bf2fa5e87943c30e0967b'},
            'units': ['redixs.service'],
            'retained_payloads': []},
 'comm': {'version': '1.0.0-1',
          'architecture': 'amd64',
          'sha256': 'ac590c9f4a860768cba2e43f6c4972566beec160991234c4a9d9fdbb6394054e',
          'hooks': {'prerm': '3c2df82bacb6533260425fc53b1e8a7413cc187c4f7002f2a7482cafbeb27e34',
                    'postrm': '001cd2f02b0b0a10959061017bf472116104ca718c3e43b72f71b1e67c465bf8'},
          'units': ['comm.service'],
          'retained_payloads': []},
 'mote-vault-sync': {'version': '1.1.0-3',
                     'architecture': 'amd64',
                     'sha256': 'df5bc6409921ce288f64b9dee53c7188c5901ff82179d5ffaf21fc98974f19cf',
                     'hooks': {'prerm': None, 'postrm': None},
                     'units': [],
                     'retained_payloads': []},
 'mote-vault-syncd': {'version': '1.1.0-3',
                      'architecture': 'amd64',
                      'sha256': '7377e28aff888f166fff165641a51843476561b1caa305bc50c9ae1ce1d71753',
                      'hooks': {'prerm': None,
                                'postrm': 'd519c5c2c39705baa13f3951990d64acc442608c61fa5ba290da6b838e005656'},
                      'units': [],
                      'retained_payloads': []},
 'medge': {'version': '3.3.0-1',
           'architecture': 'amd64',
           'sha256': 'dc62f1028c6b88f3420083eafe92821c77ee0d798cee26b02bc5113e514b2407',
           'hooks': {'prerm': 'd24014c5242944ca5a85cf1b7190c9330738a1262646fd8b6352c91c02947252',
                     'postrm': '538ade8600af975b4ba3e2710856b1a352b46c4f7788210c101e0b1cdb666dfb'},
           'units': ['medge-scheduler.service',
                     'medge.service',
                     'medged.service'],
           'retained_payloads': ['/usr/share/medge/bootstrap/medge-mchat.env']},
 'jujue': {'version': '0.2.0-1',
           'architecture': 'all',
           'sha256': '0f348a78527a2929a512375bfc31ad5a92b75cdd7d702e338598df0552eebea7',
           'hooks': {'prerm': None, 'postrm': None},
           'units': [],
           'retained_payloads': []},
 'iagent': {'version': '1.0.0-1',
            'architecture': 'amd64',
            'sha256': 'b2d4ada088860d0b08c1efec8739721f3f6704f9e2cdb5d17b2d1ecd933b28db',
            'hooks': {'prerm': 'f955369f5022b3946fee2f9958d0879853351a49aaeb1abe31b53c6bf7cc7882',
                      'postrm': 'f2667a182facda0a1dc45c8209fa7d82ed73a56f787a8d95dbade17b12868a3f'},
            'units': ['iagent.service'],
            'retained_payloads': []},
 'ss-webos': {'version': '2.0.0-12',
              'architecture': 'amd64',
              'sha256': '42f11638be9f8c8070edf52495f2c666f2967a12da955d72c9c4197fad623aa7',
              'hooks': {'prerm': None,
                        'postrm': '02871c8153d49689646e983371234cf65d957a25daeada99c0d5c9809fc7745b'},
              'units': ['ss-webosd.service'],
              'retained_payloads': []},
 'mdesk': {'version': '3.0.0-6',
           'architecture': 'amd64',
           'sha256': 'a72309fc0d593d5426ca7f3184c45611b397fc51037aa5df48c209c98a683724',
           'hooks': {'prerm': None,
                     'postrm': 'bfe629b242deb41d30e833a8e8800edb231ff83f0064d7baf0952e3f3cee1e86'},
           'units': ['mdesk-device.service', 'mdesk.service'],
           'retained_payloads': ['/usr/share/mdesk/mdesk-mchat.env']},
 'uchat': {'version': '3.2.0-2',
           'architecture': 'amd64',
           'sha256': '4a15e1949f8e32488883ac49a040802089f17cae4f0480e157d58b4c6f05a9a9',
           'hooks': {'prerm': None, 'postrm': None},
           'units': [],
           'retained_payloads': []},
 'uchatd': {'version': '0.4.0-1',
            'architecture': 'amd64',
            'sha256': 'eda5d17a0733e2a71cf7163f031ad827346d88abb78d60d2ff41fabe745f23a1',
            'hooks': {'prerm': 'b0525c9fd53c1282941231f0ab9991ddbb339bf8271a0a58d29e8f28e620032e',
                      'postrm': '70cffb5d79933daff701a544c4e992bcea528a684fe879e5004e16620d247343'},
            'units': ['uchatd-redis.service', 'uchatd.service'],
            'retained_payloads': []}}
RELEASE_TAG = 'agent-computer-v0.2.0-13'

def fail(message):
    raise RuntimeError(message)

def run(args, **kwargs):
    return subprocess.run(args, text=True, check=True, **kwargs)

def query(name, field):
    result = subprocess.run(['dpkg-query', '-W', '-f=' + field, name],
                            text=True, capture_output=True)
    if result.returncode == 1 and not result.stdout.strip():
        return ''
    if result.returncode:
        fail('Cannot inspect DPKG for ' + name)
    return result.stdout

def digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        fail('Expected a regular file: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

def retained_file(path):
    path = Path(path)
    if path.is_symlink():
        return {'link': os.readlink(path)}
    if path.is_file():
        return {'sha256': digest(path)}
    if path.exists():
        fail('Unsupported configuration file type: ' + str(path))
    return None

def inspect(policy=POLICY, info=Path('/var/lib/dpkg/info')):
    candidates = {}
    retained = {}
    diversions = []
    for name, expected in policy.items():
        raw = query(name, '$' + '{db:Status-Status}|' + '$' + '{Version}|' + '$' + '{Architecture}')
        if not raw:
            continue
        fields = raw.split('|')
        if len(fields) != 3:
            fail('Invalid DPKG record: ' + name)
        state, version, architecture = fields
        if state in ('not-installed', 'config-files'):
            continue
        if state != 'installed':
            fail('Incomplete package state; repair DPKG before removal: ' + name)
        if (version, architecture) != (expected['version'], expected['architecture']):
            fail('Unreviewed package version; no packages changed: ' + name)
        conffiles = {}
        for line in query(name, '$' + '{Conffiles}').splitlines():
            parts = line.split()
            if len(parts) >= 2:
                conffiles[parts[0]] = parts[1:]
        legacy = '/etc/mote/mote-chatd/mote-chatd-mchat.env'
        if name == 'mote-transportd' and legacy in conffiles:
            fail('Locked legacy topology ownership needs owner migration before removal.')
        for suffix, checksum in expected['hooks'].items():
            path = info / (name + '.' + suffix)
            if checksum is None:
                if path.exists() or path.is_symlink():
                    fail('Unexpected removal hook: ' + str(path))
            elif digest(path) != checksum:
                fail('Removal hook differs from reviewed package: ' + name + '.' + suffix)
        listing = run(['dpkg-query', '-L', name], capture_output=True).stdout.splitlines()
        for filename in listing:
            if filename.endswith('-mchat.env') and filename not in conffiles:
                if filename not in expected.get('retained_payloads', []):
                    fail('Locked topology is an unreviewed package payload: ' + filename)
                destination = filename + '.agpc-uninstall-retained'
                if Path(destination).exists() or Path(destination).is_symlink():
                    fail('Retained payload diversion destination already exists: ' + destination)
                if diversion(['--truename', filename]).stdout.strip() != filename:
                    fail('Existing package diversion needs owner review: ' + filename)
                value = retained_file(filename)
                if value is not None:
                    retained[filename] = value
                diversions.append({'path': filename, 'destination': destination})
        for filename in conffiles:
            value = retained_file(filename)
            if value is not None:
                retained[filename] = value
        candidates[name] = {'version': version, 'architecture': architecture}
    return {'packages': candidates, 'retained': retained, 'diversions': diversions}

def validate_catalog(catalog):
    release = catalog.get('release') or {}
    if catalog.get('schema') != 'agent-computer-apt-overlay/v6' or release.get('repository') != 'motebus/download' or release.get('tag') != RELEASE_TAG:
        fail('Signed catalog does not match this reviewed uninstaller.')
    records = release.get('packages', [])
    if not isinstance(records, list) or len(records) != len(POLICY):
        fail('Signed package catalog is incomplete.')
    if {p.get('name') for p in records} != set(POLICY):
        fail('Signed package identities differ from reviewed removal policy.')
    for record in records:
        expected = POLICY[record['name']]
        if any(record.get(field) != expected[field] for field in ('version', 'architecture', 'sha256')):
            fail('Signed package pin differs from reviewed removal policy: ' + record['name'])

def validate_plan(text, packages):
    removed = set()
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] in ('Inst', 'Purg', 'Conf'):
            fail('Removal plan would install, purge or configure a package.')
        if fields[0] == 'Remv':
            if len(fields) < 3:
                fail('Malformed removal plan.')
            name = fields[1].split(':')[0]
            if name not in packages or name in removed or fields[2] != '[' + packages[name]['version'] + ']':
                fail('Removal plan would remove packages outside the reviewed AGPC set.')
            removed.add(name)
    if removed != set(packages):
        fail('Removal plan does not exactly match the selected AGPC packages.')

def validate_protocol(text, packages):
    lines = text.splitlines()
    if not lines or lines[0] != 'VERSION 3':
        fail('APT action protocol version 3 is required.')
    try:
        separator = lines.index('', 1)
    except ValueError:
        fail('Incomplete APT action protocol.')
    if any('=' not in line for line in lines[1:separator]):
        fail('Malformed APT configuration record.')
    removed = set()
    for line in lines[separator + 1:]:
        fields = line.split()
        if len(fields) != 9:
            fail('Malformed APT removal action.')
        name, old, architecture, _, direction, new, _, _, action = fields
        if name not in packages or name in removed or action != '**REMOVE**' or new != '-' or direction != '>':
            fail('APT would execute an action outside the reviewed removal plan.')
        if (old, architecture) != (packages[name]['version'], packages[name]['architecture']):
            fail('APT package identity changed before removal.')
        removed.add(name)
    if removed != set(packages):
        fail('APT actions do not exactly match the admitted removal plan.')

def diversion(args):
    # --no-rename alters only DPKG ownership metadata, never the locked file.
    return run(['dpkg-divert', '--admindir=' + str(Path('/var/lib/dpkg')), *args], capture_output=True)

def restore_diversions(state):
    for item in reversed(state['diversions']):
        if diversion(['--truename', item['path']]).stdout.strip() == item['destination']:
            diversion(['--remove', '--local', '--no-rename', '--divert', item['destination'], item['path']])

def guard(stage):
    if os.environ.get('APT_HOOK_INFO_FD') != '0':
        fail('APT action protocol is unavailable.')
    state = json.loads((stage / 'state.json').read_text())
    validate_protocol(sys.stdin.read(), state['packages'])
    if inspect() != state:
        fail('Installed packages or retained configuration changed after preflight.')
    for item in state['diversions']:
        diversion(['--add', '--local', '--no-rename', '--divert', item['destination'], item['path']])
    if Path('/run/systemd/system').is_dir():
        units = sorted({unit for name in state['packages'] for unit in POLICY[name]['units']})
        if units:
            run(['systemctl', 'stop', *units])
    (stage / 'guard-ran').write_text('validated\n')

def main():
    mode, stage_name = sys.argv[1:3]
    stage = Path(stage_name)
    if mode == 'guard':
        guard(stage)
        return
    validate_catalog(json.loads((stage / 'agent-computer-apt-overlay.json').read_text()))
    state = inspect()
    packages = state['packages']
    print('AGPC packages selected for removal: ' + (', '.join(packages) or '(none)'), flush=True)
    print('Ubuntu, user data, Vaults, models, configuration, Obsidian and OS dependencies are retained.', flush=True)
    if not packages:
        print('No installed packages in the reviewed AGPC set.')
        return
    options = ['-o', 'APT::Get::AutomaticRemove=false', '-o', 'APT::Get::Purge=false']
    run(['apt-get', 'check'])
    plan = run(['apt-get', *options, '--simulate', 'remove', *packages], capture_output=True).stdout
    validate_plan(plan, packages)
    print(plan, flush=True)
    if mode == '--plan':
        print('Plan only: no packages or services were changed.')
        return
    if mode != '--yes':
        with open('/dev/tty', 'r+') as terminal:
            terminal.write('Remove the listed AGPC packages while retaining data? Type REMOVE: ')
            terminal.flush()
            if terminal.readline().strip() != 'REMOVE':
                fail('Removal cancelled; no packages or services were changed.')
    if inspect() != state:
        fail('Package state changed while waiting for confirmation.')
    (stage / 'state.json').write_text(json.dumps(state))
    hook = stage / 'guard'
    # stage is generated by mktemp below, never a caller-supplied shell fragment.
    hook.write_text('#!/bin/sh\nexec python3 "' + str(stage / 'engine.py') + '" guard "' + str(stage) + '"\n')
    hook.chmod(0o700)
    env = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
    try:
        run(['apt-get', *options, '--no-download', '-y',
             '-o', 'DPkg::Pre-Install-Pkgs::=' + str(hook),
             '-o', 'DPkg::Tools::Options::' + str(hook) + '::Version=3',
             '-o', 'DPkg::Tools::Options::' + str(hook) + '::InfoFD=0',
             'remove', *packages], env=env)
    finally:
        restore_diversions(state)
    if not (stage / 'guard-ran').is_file():
        fail('APT did not run the removal action verification hook.')
    for name in packages:
        state_name = query(name, '$' + '{db:Status-Status}').strip()
        if state_name not in ('', 'not-installed', 'config-files'):
            fail('Package removal is incomplete: ' + name)
    for filename, before in state['retained'].items():
        if retained_file(filename) != before:
            fail('Retained configuration verification failed: ' + filename)
    run(['apt-get', 'check'])
    print('AGPC package removal verified. Owner data and configuration were retained.')

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError) as error:
        print('AGPC uninstall failed: ' + str(error), file=sys.stderr)
        sys.exit(1)

PY_UNINSTALL_PREFLIGHT
python3 "$stage/engine.py" "$mode" "$stage"
