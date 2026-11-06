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

POLICY = {'agpc-view': {'version': '0.1.0-1', 'architecture': 'amd64', 'sha256': 'f80b65a3823e7fa32ae8395df61ab113b4ac964d91615ae2a0e64035407da4d8', 'hooks': {'prerm': None, 'postrm': None}, 'units': [], 'retained_payloads': []}, 'uchat-bridge': {'version': '0.1.0-1',
                  'architecture': 'amd64',
                  'sha256': '02315da161be76d793079da092f50c00a9fd6ed98298d964f047592e77f22717',
                  'hooks': {'prerm': None, 'postrm': None},
                  'units': [],
                  'retained_payloads': []},
 'agent-sphere': {'version': '0.3.0-43',
                  'architecture': 'all',
                  'sha256': '71ec12758777e6c178d6b8a606b538e4a234e2f922de4b79d618a5e754d22487',
                  'hooks': {'prerm': '1bd6bdbedefa3da7e7d776d186f2a6905f65d622e6d79d2d4822cb25aedca79d',
                            'postrm': '1bb6bcd08933a82ea83ece4395fa4e144418bd78395d6e84073918d7d28ea370'},
                  'units': ['agentsphere.target'],
                  'retained_payloads': []},
 'agpc-ultra': {'version': '0.1.0-1',
                'architecture': 'all',
                'sha256': 'ae6b118367c038b6607cd9c954d7f1e839ed3584d41d84a5b1ec6b8cf31dddb7',
                'hooks': {'prerm': 'b69eba2defbcaf3a94dd6d5e769a16a7029dd66ac1bb0e94045c0544f2543167',
                          'postrm': 'c88fd25ee684fefa483e660a9210d2a262421f4c363c31f8ae0810baba99fce5'},
                'units': ['agentsphere-local.target'],
                'retained_payloads': []},
 'agpc-manager': {'version': '4.4.0-2',
                  'architecture': 'all',
                  'sha256': '2e2b6f0ee79c1d5c5b9d300fcefba9e21da05acacbfa6fc8093c71c8a6f1e091',
                  'hooks': {'prerm': None, 'postrm': None},
                  'units': [],
                  'retained_payloads': []},
 'agpc-cdp': {'version': '0.2.0-2',
              'architecture': 'amd64',
              'sha256': 'beb24f87f55deb502da6f0f22b247126b779f7ba776983c70b067fba4ceba201',
              'hooks': {'prerm': None,
                        'postrm': '6c398f2f092d80b7b8fcdb5781970774b1b26b0126d63700c8c74481bc3fc7ea'},
              'units': [],
              'retained_payloads': []},
 'agpc-run': {'version': '0.2.0-4',
              'architecture': 'all',
              'sha256': 'f7d7edc68fa4546ec79936afdb8df8d86e6b30e9d2b7b451f917d605e7b319af',
              'hooks': {'prerm': None, 'postrm': None},
              'units': [],
              'retained_payloads': []},
 'agpc-apps': {'version': '0.3.0-2',
               'architecture': 'all',
               'sha256': '93d38d4fa7e0f11b8add9de0b18b781f722af2eac5a1602f397bf08a3ec9eabc',
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
 'moted': {'version': '3.6.5-1',
           'architecture': 'amd64',
           'sha256': 'b3c2615b3964725fbb9a2e7e2f28574e69557eb92b9e985698b25be2377afa97',
           'hooks': {'prerm': '5910ac29327cfa4cd255883d5394e501a53ff7603411168f5a1ac6f2f28ae7e8',
                     'postrm': '1028da06b1599f1e356f16380aa40366f1a796e941ac0a16c4b4228562878713'},
           'units': ['moted-ssh-relay.service', 'moted.service'],
           'retained_payloads': ['/usr/share/moted/bootstrap/moted-mchat.env']},
 'mote-proxy': {'version': '2.0.8-1',
                'architecture': 'amd64',
                'sha256': '53a9e1f553348c8207a56e96de461bcb42d4721422a3f54080e954befd19e19b',
                'hooks': {'prerm': '7ec71031f7aa11b1f81ebc68749f90e5248885c327120d92f49cdeebae223b41',
                          'postrm': '25f852aff95d40686108eb003563c60f33281542ec23f9e7a570155b2fe86488'},
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
 'mote-secd': {'version': '1.3.0-3',
               'architecture': 'amd64',
               'sha256': 'd68d36693f1a269aec33c2a7315f858105b7718db3a2d617eed0ffb6356b0169',
               'hooks': {'prerm': 'cc136d120aae527212bac5e320742ccab3d22e9e31562de85d828a55f86e8228',
                         'postrm': 'dc15a1a139e064851d218eab0eece1159ca4920d525b5275d67b09a8cc7fc609'},
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
 'cx-loop': {'version': '0.1.0-5',
             'architecture': 'amd64',
             'sha256': '088fc7a912ffcc9e70b53e68a8eddcd8073dfcdc943ce6c9eb051cb81eff9a05',
             'hooks': {'prerm': '908d0beb77fe0a2f48232f44191985448a2416d7bb45e15a21d3b794360251b9',
                       'postrm': '0937292654dbd9689b3fe473673228b184097321ccd8a40fc0132e226ac32a53'},
             'units': ['cx-loopd.service'],
             'retained_payloads': []},
 'contextd': {'version': '0.1.0-27',
              'architecture': 'amd64',
              'sha256': '259c92ea9b7a34f557d77f91d3fc2060108dcb454405883419acc6ecaaffcbc7',
              'hooks': {'prerm': 'a51652f275ce6ea6d3fbb711d651b2eac4c649c319fa3305e9dc060f44f4e52d',
                        'postrm': 'd46466ffc8214c29f7311066fbf60b74d49701447987288a7c09fd6bb6579a9b'},
              'units': ['contextd.service'],
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
 'medge': {'version': '3.3.0-2',
           'architecture': 'amd64',
           'sha256': '0877a5568f677b6ec8e2209d11d21219009cc0733fbec30ab25d5021fcbee4c7',
           'hooks': {'prerm': 'e815dfde51a84290f65a6b973077f9db6f355919136320183c54fddf51c1f155',
                     'postrm': '11a438ace1ede904a632872956a4d4b45ed98665b1ea7ef8ab36af1e7e023091'},
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
 'uchat': {'version': '3.2.0-13',
           'architecture': 'amd64',
           'sha256': '45726cb4fc91545e1ab7c1ebbe511ea5b3c88d035763af6f92777bc3231e480d',
           'hooks': {'prerm': None, 'postrm': None},
           'units': [],
           'retained_payloads': []},
 'uchatd': {'version': '0.6.0-5',
            'architecture': 'amd64',
            'sha256': 'bfc6ab242d8eba3d2d470aa9016ca260afb9d88f7161dfaa98ded49a422a1cff',
            'hooks': {'prerm': 'f9d27d4b8899cc1bea51c5336475bc4f028d0fe46c9fd30fb6956a73d856f954',
                      'postrm': '42f9f2bf262a7fedb7c17f7f4e5e840e30317ab2296c34362f669a67f3db6e96'},
            'units': ['uchatd-redis.service', 'uchatd.service'],
            'retained_payloads': []},
 'mote-chatd': {'version': '2.0.0-9',
                'architecture': 'all',
                'sha256': '5b1a3c8cba45ea321d9c3ee70962b78f5e203133f7413ae33873a9006ea5b8b7',
                'hooks': {'prerm': '59d2c559a7261ddeb4664e2790b89e56a599c83ce8b76849b1e0420edd6f2e87',
                          'postrm': '977b560177c7afd78adb5277026a9dbb5dc4ebdad5afdc53f4b1e23dc490511d'},
                'units': [],
                'retained_payloads': []},
 'agent-apps': {'version': '0.3.0-2',
                'architecture': 'all',
                'sha256': '8279b8dd7aeeded12d5533c1bd0a94d5e7fa42a64d219690b82e409f143d8ce4',
                'hooks': {'prerm': None, 'postrm': None},
                'units': [],
                'retained_payloads': []},
 'agpc-mesh': {'version': '3.0.0-3',
               'architecture': 'amd64',
               'sha256': 'b55c657884ef073c4b12827edce4a99318e20e0b7fd61de24edecf8a41a97db6',
               'hooks': {'prerm': 'db9b7c708ccaed873ad396513ba59fe419fe3207e2c7436e026f45571b97cf99',
                         'postrm': '3ae0a4ac4cb885926360a88a16155697dae7aa38a0618e26eaef56b83918bb67'},
               'units': ['agpc-mesh.service'],
               'retained_payloads': ['/usr/share/agpc-mesh/bootstrap/agpc-mesh-mchat.env']}}
ALTERNATE_POLICY = {'agent-ultra': [{'version': '0.1.0-1',
                  'architecture': 'all',
                  'sha256': 'a84502dc1730f066269a9f75acbaa7ba5fd20e25d8e9f4d0c85535f98ee9e60d',
                  'hooks': {'prerm': 'b69eba2defbcaf3a94dd6d5e769a16a7029dd66ac1bb0e94045c0544f2543167',
                            'postrm': 'c88fd25ee684fefa483e660a9210d2a262421f4c363c31f8ae0810baba99fce5'},
                  'units': ['agentsphere-local.target'],
                  'retained_payloads': []},
                 {'version': '0.1.0-2',
                  'architecture': 'all',
                  'sha256': '9ba04834cce54e1461955ca85d9c89d67d3394a885c3be59a4915ca40f7fc0e9',
                  'hooks': {'prerm': 'b69eba2defbcaf3a94dd6d5e769a16a7029dd66ac1bb0e94045c0544f2543167',
                            'postrm': 'c88fd25ee684fefa483e660a9210d2a262421f4c363c31f8ae0810baba99fce5'},
                  'units': ['agentsphere-local.target'],
                  'retained_payloads': []},
                 {'version': '0.1.0-3',
                  'architecture': 'all',
                  'sha256': 'b6bb91387331263bdf0fea49bc0e69d17afd28460e2e91067c1cc7d433334436',
                  'hooks': {'prerm': 'b69eba2defbcaf3a94dd6d5e769a16a7029dd66ac1bb0e94045c0544f2543167',
                            'postrm': 'c88fd25ee684fefa483e660a9210d2a262421f4c363c31f8ae0810baba99fce5'},
                  'units': ['agentsphere-local.target'],
                  'retained_payloads': []}],
 'agpc-cdp': [{'version': '0.2.0-1',
               'architecture': 'amd64',
               'sha256': '6a988f66dea5dd5f55febd4fc9effdd41afa44f2b5ca2f406d6e33ad990f6301',
               'hooks': {'prerm': None,
                         'postrm': '6c398f2f092d80b7b8fcdb5781970774b1b26b0126d63700c8c74481bc3fc7ea'},
               'units': [],
               'retained_payloads': []}],
 'agpc-run': [{'version': '0.2.0-1',
               'architecture': 'all',
               'sha256': 'e1acfd2628b4fb314f21268be557cb947736619b224903dbff34475887a10fd6',
               'hooks': {'prerm': None, 'postrm': None},
               'units': [],
               'retained_payloads': []},
              {'version': '0.2.0-2',
               'architecture': 'all',
               'sha256': '313982436a47417d3b0e3dfef47cad2811a293c1bb88784b61f535406196f4f4',
               'hooks': {'prerm': None, 'postrm': None},
               'units': [],
               'retained_payloads': []},
              {'version': '0.2.0-3',
               'architecture': 'all',
               'sha256': '84b70d24def46ba52393a6987f5d4f72be3e472802b25b7ad4483dd384f2c6c2',
               'hooks': {'prerm': None, 'postrm': None},
               'units': [],
               'retained_payloads': []}],
 'moted': [{'version': '3.6.2-1',
            'architecture': 'amd64',
            'sha256': 'c559e504f25d5ddacd66e5a02d3c69040e038e157ed8788a1f8e03ef613bff18',
            'hooks': {'prerm': '06417d4752bdad767de25177e4c4e79a4dd2cd2c1e880e33b4a9bd468f650e04',
                      'postrm': '7dc2190bba29dbb3b3a1a84c620df4c9bf672c1c170c395968f01ce98c34fad7'},
            'units': ['moted-ssh-relay.service', 'moted.service'],
            'retained_payloads': ['/usr/share/moted/bootstrap/moted-mchat.env']},
           {'version': '3.6.0-7',
            'architecture': 'amd64',
            'sha256': '8ad88a3f0e295d7694c99fe4c927291256b8c02f850e1aeb837abd101760d6e8',
            'hooks': {'prerm': '45fbbe30c7f441f99a039779eed7df31da7418ebbd190e42ff0ff4b1fcc8a1ff',
                      'postrm': '7bc5b7c3b6e6b104842925bb2ecbd190101a06d9ca7baa39b2c39890b558ac1c'},
            'units': ['moted-ssh-relay.service', 'moted.service'],
            'retained_payloads': ['/usr/share/moted/bootstrap/moted-mchat.env']},
           {'version': '3.6.4-1',
            'architecture': 'amd64',
            'sha256': 'f7577bcd8ca87a9299d2c675310e9bc87c1cd9d6510f86771db43b31f121677d',
            'hooks': {'prerm': '5910ac29327cfa4cd255883d5394e501a53ff7603411168f5a1ac6f2f28ae7e8',
                      'postrm': '1028da06b1599f1e356f16380aa40366f1a796e941ac0a16c4b4228562878713'},
            'units': ['moted-ssh-relay.service', 'moted.service'],
            'retained_payloads': ['/usr/share/moted/bootstrap/moted-mchat.env']},
           {'version': '3.6.4-2',
            'architecture': 'amd64',
            'sha256': '47d7d74971512715e8831c3a48d5017a3144ff416fbca2123edcf02f71a2c067',
            'hooks': {'prerm': '5910ac29327cfa4cd255883d5394e501a53ff7603411168f5a1ac6f2f28ae7e8',
                      'postrm': '1028da06b1599f1e356f16380aa40366f1a796e941ac0a16c4b4228562878713'},
            'units': ['moted-ssh-relay.service', 'moted.service'],
            'retained_payloads': ['/usr/share/moted/bootstrap/moted-mchat.env']}],
 'mote-proxy': [{'version': '2.0.2-1',
                 'architecture': 'amd64',
                 'sha256': 'ec646e93f13ca25bc100631e7a0843e5b2fcf6696ca1e46859e0e6db61c3d023',
                 'hooks': {'prerm': '41c68e5fadb7cdc90b9e97d080c3291d4be10ab072079ba62e406c365b571d1c',
                           'postrm': 'cc16f50e01db6295410191a0b8b933093c15079acdad5f5e6f7dd2886da18a63'},
                 'units': ['mote-proxy.service'],
                 'retained_payloads': ['/usr/share/mote-proxy/mote-proxy-mchat.env']},
                {'version': '2.0.0-9',
                 'architecture': 'amd64',
                 'sha256': '776684423763f0f48e02eba0fff5f47b3f9ccd1ff26b2fb1aae03e65f1b7087f',
                 'hooks': {'prerm': '851cb809efd185366e817cb6b78ec0046e1b2a9d42d2cc1b9e1999591d723662',
                           'postrm': 'b3b7514a956bdb48bd6a9b030bd218c533a063accd0121da738824bb7208b4a7'},
                 'units': ['mote-proxy.service'],
                 'retained_payloads': ['/usr/share/mote-proxy/mote-proxy-mchat.env']},
                {'version': '2.0.6-1',
                 'architecture': 'amd64',
                 'sha256': 'be3238f2bf7ef0f7bdbf391f6a4808c602f9f736c4b7ac506d665c0c7a7d06b7',
                 'hooks': {'prerm': '7ec71031f7aa11b1f81ebc68749f90e5248885c327120d92f49cdeebae223b41',
                           'postrm': '25f852aff95d40686108eb003563c60f33281542ec23f9e7a570155b2fe86488'},
                 'units': ['mote-proxy.service'],
                 'retained_payloads': ['/usr/share/mote-proxy/mote-proxy-mchat.env']},
                {'version': '2.0.7-1',
                 'architecture': 'amd64',
                 'sha256': '14e354a5c12282b198173b568627bcd8a66fb1dc50d3cd3ba22f20e931452e36',
                 'hooks': {'prerm': '7ec71031f7aa11b1f81ebc68749f90e5248885c327120d92f49cdeebae223b41',
                           'postrm': '25f852aff95d40686108eb003563c60f33281542ec23f9e7a570155b2fe86488'},
                 'units': ['mote-proxy.service'],
                 'retained_payloads': ['/usr/share/mote-proxy/mote-proxy-mchat.env']}],
 'mote-mcp-ultra': [{'version': '0.3.0-1',
                     'architecture': 'amd64',
                     'sha256': 'afb043986d3b153cce378a2a0ba2772d420b06d132579f385c26b98e6ca20d47',
                     'hooks': {'prerm': None, 'postrm': None},
                     'units': [],
                     'retained_payloads': []}],
 'cx-mesh': [{'version': '2.0.0-1',
              'architecture': 'amd64',
              'sha256': '7e7e9e36f79c3a406bfb987bc18b2055ec8306cd5c3508fd88614f1d0ae2e89e',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '1d01229f94d330318179b7ab73c092daf8b776d31082fe4a8ea03d6e19610238'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
             {'version': '2.0.0-2',
              'architecture': 'amd64',
              'sha256': '39a4474dcbea13728af06e322bce862110db0dcc662b3e2b04cad30bacc5b1a4',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '4932afd86c8916e16152aa75e0ed0bc4d8ffc0bdc9e8d6bcc541875b4b849cf5'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
             {'version': '2.0.1-1',
              'architecture': 'amd64',
              'sha256': '11e546b24ae406859fb6634e9eaa5bf9427a84b3a78fa3adb64f4713822769fb',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '4932afd86c8916e16152aa75e0ed0bc4d8ffc0bdc9e8d6bcc541875b4b849cf5'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
             {'version': '2.1.0-1',
              'architecture': 'amd64',
              'sha256': 'f57a1ac2ef683553f79869f1c44bad1f13684a11f09fc2ca88cd5be9b5e8a5a0',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '4932afd86c8916e16152aa75e0ed0bc4d8ffc0bdc9e8d6bcc541875b4b849cf5'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
             {'version': '2.1.0-2',
              'architecture': 'amd64',
              'sha256': 'e5fc7a5c8526e5072dd7e87c4423c88de371ed51dc875c95f71dc45245f11da9',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '4932afd86c8916e16152aa75e0ed0bc4d8ffc0bdc9e8d6bcc541875b4b849cf5'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
             {'version': '2.1.0-3',
              'architecture': 'amd64',
              'sha256': '5f267e39488d40fa4702386cbf4e3fdea9d230d66c2f1556a5a12faff4a3ae11',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '4932afd86c8916e16152aa75e0ed0bc4d8ffc0bdc9e8d6bcc541875b4b849cf5'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
             {'version': '2.1.1-1',
              'architecture': 'amd64',
              'sha256': 'eae5b1d61c439191cf8d9e109595f2c3311089f34333e36d1581a3c7750a8927',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '4932afd86c8916e16152aa75e0ed0bc4d8ffc0bdc9e8d6bcc541875b4b849cf5'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']},
             {'version': '2.2.0-1',
              'architecture': 'amd64',
              'sha256': 'bf431936374418792147a7d19b12292b5652653b732e71c279489a726d95686d',
              'hooks': {'prerm': 'dcbc3d89b484ef2548c496cdaf532a1a69bcba8c2aa1de74dd4debcb7a3005d7',
                        'postrm': '4932afd86c8916e16152aa75e0ed0bc4d8ffc0bdc9e8d6bcc541875b4b849cf5'},
              'units': ['cx-mesh.service'],
              'retained_payloads': ['/usr/share/cx-mesh/bootstrap/cx-mesh-mchat.env']}],
 'ss-webos': [{'version': '2.0.0-15',
               'architecture': 'amd64',
               'sha256': '7e19b4720e278f76a57196db042874f70422a70cd8cdabd4aefdcb64c0eb5300',
               'hooks': {'prerm': None,
                         'postrm': '02871c8153d49689646e983371234cf65d957a25daeada99c0d5c9809fc7745b'},
               'units': ['ss-webosd.service'],
               'retained_payloads': []}],
 'uchat': [{'version': '3.2.0-10',
            'architecture': 'amd64',
            'sha256': '7731fec83b3e1b0533d45a90a8d8e1dd15fe772579959275cbf66bc66ca78530',
            'hooks': {'prerm': None, 'postrm': None},
            'units': [],
            'retained_payloads': []},
           {'version': '3.2.0-11',
            'architecture': 'amd64',
            'sha256': '1acf4f2cf7658cbf5165b02ff1d92b22d072c3b4b8825d89a2f3314a385c0eba',
            'hooks': {'prerm': None, 'postrm': None},
            'units': [],
            'retained_payloads': []},
           {'version': '3.2.0-12',
            'architecture': 'amd64',
            'sha256': '79c21485532335357d868bf126a8713cdd7a80840da5b7377976ec2995dad32d',
            'hooks': {'prerm': None, 'postrm': None},
            'units': [],
            'retained_payloads': []}],
 'uchatd': [{'version': '0.6.0-1',
             'architecture': 'amd64',
             'sha256': '0b6a9b4680ecb50a7a700829cf7df95e845694a258dd20053a8d6738fd358650',
             'hooks': {'prerm': 'eb582f507d648232596d767acd6f4f458035adcd916ff2eeb55a2afab226789e',
                       'postrm': 'e006abe353626c60662d2ba8293803adbba4673291e96ef5d03aca8e60b7de2f'},
             'units': ['uchatd-redis.service', 'uchatd.service'],
             'retained_payloads': []},
            {'version': '0.6.0-2',
             'architecture': 'amd64',
             'sha256': 'c2d2c2cc9b32182c25329c7166d02b2d207ab95468e5ae5d0a80e70a86d5c258',
             'hooks': {'prerm': 'eb582f507d648232596d767acd6f4f458035adcd916ff2eeb55a2afab226789e',
                       'postrm': 'e006abe353626c60662d2ba8293803adbba4673291e96ef5d03aca8e60b7de2f'},
             'units': ['uchatd-redis.service', 'uchatd.service'],
             'retained_payloads': []},
            {'version': '0.6.0-3',
             'architecture': 'amd64',
             'sha256': '338b7781afa34830a5627f70825cc90f2a58ede18dea4fcb85e210514573bff8',
             'hooks': {'prerm': 'eb582f507d648232596d767acd6f4f458035adcd916ff2eeb55a2afab226789e',
                       'postrm': 'e006abe353626c60662d2ba8293803adbba4673291e96ef5d03aca8e60b7de2f'},
             'units': ['uchatd-redis.service', 'uchatd.service'],
             'retained_payloads': []},
            {'version': '0.6.0-4',
             'architecture': 'amd64',
             'sha256': '9ca33c362b788b2c50057148ae4b356352f31bd570f07aa2afc800f7e8384bd8',
             'hooks': {'prerm': 'f9d27d4b8899cc1bea51c5336475bc4f028d0fe46c9fd30fb6956a73d856f954',
                       'postrm': '42f9f2bf262a7fedb7c17f7f4e5e840e30317ab2296c34362f669a67f3db6e96'},
             'units': ['uchatd-redis.service', 'uchatd.service'],
             'retained_payloads': []}],
 'agpc-manager': [{'version': '4.3.0-1',
                   'architecture': 'all',
                   'sha256': '3cff6088e449be9c31e5f56b2ab18596e8fc5f981f832bac3100ba68998ef05b',
                   'hooks': {'prerm': None, 'postrm': None},
                   'units': [],
                   'retained_payloads': []},
                  {'version': '3.3.0-1',
                   'architecture': 'amd64',
                   'sha256': '044e4f7431a6b0bf7e905658ddc82e9232ad3127dea1c295c030b788eb4077b0',
                   'hooks': {'prerm': None, 'postrm': None},
                   'units': [],
                   'retained_payloads': []},
                  {'version': '4.0.0-1',
                   'architecture': 'all',
                   'sha256': 'bf18a1b7790e1511125b3bb36ec8833c696d7f8a72ad4fc25f6ddac4490d5fe0',
                   'hooks': {'prerm': None, 'postrm': None},
                   'units': [],
                   'retained_payloads': []},
                  {'version': '4.1.0-1',
                   'architecture': 'all',
                   'sha256': 'd307ace6988b5bb2e8be1d94c1af3540047ddc6f2fae71977a1ce35d365a3bac',
                   'hooks': {'prerm': None, 'postrm': None},
                   'units': [],
                   'retained_payloads': []},
                  {'version': '4.2.0-1',
                   'architecture': 'all',
                   'sha256': 'ca6d6e4f5437518d74a11fbb50ed8607416ed28ecd1632ac9772bbabd3190f04',
                   'hooks': {'prerm': None, 'postrm': None},
                   'units': [],
                   'retained_payloads': []},
                  {'version': '4.4.0-1',
                   'architecture': 'all',
                   'sha256': '74dcb4d43c1b8b0c6dbc014b31e5de1dc8d2bde99c9043f4f065eeb02ed8f443',
                   'hooks': {'prerm': None, 'postrm': None},
                   'units': [],
                   'retained_payloads': []}],
 'agent-sphere': [{'version': '0.3.0-42',
                   'architecture': 'all',
                   'sha256': 'f2bdede52944e88aaf7efb38ff290cc11e902b887c062d58ccbbf9747d95c07e',
                   'hooks': {'prerm': '1bd6bdbedefa3da7e7d776d186f2a6905f65d622e6d79d2d4822cb25aedca79d',
                             'postrm': '1bb6bcd08933a82ea83ece4395fa4e144418bd78395d6e84073918d7d28ea370'},
                   'units': ['agentsphere.target'],
                   'retained_payloads': []}],
 'medge': [{'version': '3.3.0-1',
            'architecture': 'amd64',
            'sha256': 'dc62f1028c6b88f3420083eafe92821c77ee0d798cee26b02bc5113e514b2407',
            'hooks': {'prerm': 'd24014c5242944ca5a85cf1b7190c9330738a1262646fd8b6352c91c02947252',
                      'postrm': '538ade8600af975b4ba3e2710856b1a352b46c4f7788210c101e0b1cdb666dfb'},
            'units': ['medge-scheduler.service',
                      'medge.service',
                      'medged.service'],
            'retained_payloads': ['/usr/share/medge/bootstrap/medge-mchat.env']}],
 'cx-loop': [{'version': '0.1.0-4',
              'architecture': 'amd64',
              'sha256': '2a2a96c074dcd7b398ecb4cc9ababcf859a91b26375276fe17ee4368aa1de474',
              'hooks': {'prerm': '908d0beb77fe0a2f48232f44191985448a2416d7bb45e15a21d3b794360251b9',
                        'postrm': '0937292654dbd9689b3fe473673228b184097321ccd8a40fc0132e226ac32a53'},
              'units': ['cx-loopd.service'],
              'retained_payloads': []}],
 'agpc-mesh': [{'version': '3.0.0-1',
                'architecture': 'amd64',
                'sha256': 'a209214d53418c8a167b6fcbb06363f2853d463c569630befb4c21fb1faf6a4b',
                'hooks': {'prerm': 'db9b7c708ccaed873ad396513ba59fe419fe3207e2c7436e026f45571b97cf99',
                          'postrm': '3ae0a4ac4cb885926360a88a16155697dae7aa38a0618e26eaef56b83918bb67'},
                'units': ['agpc-mesh.service'],
                'retained_payloads': ['/usr/share/agpc-mesh/bootstrap/agpc-mesh-mchat.env']},
               {'version': '3.0.0-2',
                'architecture': 'amd64',
                'sha256': '161f823d86ef81795e7b279b6ccabec8aa474cea084babae457aa2510492b0a9',
                'hooks': {'prerm': 'db9b7c708ccaed873ad396513ba59fe419fe3207e2c7436e026f45571b97cf99',
                          'postrm': '3ae0a4ac4cb885926360a88a16155697dae7aa38a0618e26eaef56b83918bb67'},
                'units': ['agpc-mesh.service'],
                'retained_payloads': ['/usr/share/agpc-mesh/bootstrap/agpc-mesh-mchat.env']}],
 'mote-secd': [{'version': '1.0.0-2',
                'architecture': 'amd64',
                'sha256': '043fd2fe86dfe83d17f9ab6e7e82ca96d1423e0697c3b4a0549cbd7f6e4998c2',
                'hooks': {'prerm': 'baef7ed74ecd1335ed05319e20deb09acb7848e6e9eca5990a1a94ba15fe8679',
                          'postrm': '8aecd5e33641ebd39963791a35efb155efe4e48430c13fa3d5874c7cfa1c37a9'},
                'units': ['mote-secd.service'],
                'retained_payloads': []}]}
ALTERNATE_POLICY['agent-apps'] = [POLICY.pop('agent-apps')]
RELEASE_TAG = 'agent-computer-v0.3.0-85'

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

def reviewed_policy(name, version, architecture, policy):
    variants = [policy[name]] if name in policy else []
    if policy is POLICY:
        variants.extend(ALTERNATE_POLICY.get(name, []))
    matches = [item for item in variants
               if (item['version'], item['architecture']) == (version, architecture)]
    if len(matches) != 1:
        fail('Unreviewed package version; no packages changed: ' + name)
    return matches[0]

def inspect(policy=POLICY, info=Path('/var/lib/dpkg/info')):
    candidates = {}
    retained = {}
    diversions = []
    names = list(policy)
    if policy is POLICY:
        names.extend(name for name in ALTERNATE_POLICY if name not in policy)
    for name in names:
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
        expected = reviewed_policy(name, version, architecture, policy)
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
    if catalog.get('schema') != 'agent-computer-apt-overlay/v12' or release.get('repository') != 'motebus/download' or release.get('tag') != RELEASE_TAG:
        fail('Signed catalog does not match this reviewed uninstaller.')
    records = [*release.get('packages', []), *release.get('retention_packages', [])]
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
        units = sorted({unit for name, record in state['packages'].items()
                        for unit in reviewed_policy(name, record['version'], record['architecture'], POLICY)['units']})
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
