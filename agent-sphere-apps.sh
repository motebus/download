#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf '%s\n' \
        'Usage: agpc.sh [--yes] [--help]' \
        'Install agent-sphere, agent-ultra, agpc-manager and agent-apps using the signed MoteBus APT repository.' \
        'Supports Ubuntu 24.04 and 26.04 amd64; creates only missing reviewed APT key/source files.' \
        'Downloads the pinned official Obsidian DEB for the same APT transaction.' \
        'Run as root. APT asks for confirmation unless --yes is supplied.'
}
fail() { printf '%s\n' "$*" >&2; exit 1; }
confirmation=()
for arg in "$@"; do
    case "$arg" in
        --yes) confirmation=(--yes) ;;
        --help) usage; exit 0 ;;
        *) printf 'Unsupported argument: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done
[[ $(id -u) == 0 ]] || fail 'Run this installer as root (for example, with sudo).'
for command in apt-get curl sha256sum dpkg dpkg-deb dpkg-query mktemp chmod realpath stat python3; do
    command -v "$command" >/dev/null 2>&1 || fail "$command is required. Package installation was not started."
done
[[ $(dpkg --print-architecture) == amd64 ]] || fail 'This reviewed release requires amd64.'
export LC_ALL=C

# BEGIN SIGNED BOOTSTRAP
# Source after the installer's argument parsing. No action occurs on source.
# Run platform_check before mutations; run apt_bootstrap only AFTER migration guards.
agentsphere_platform_check() {
    [ "${EUID:-$(id -u)}" -eq 0 ] || { printf '%s\n' 'AgentSphere installation requires root.' >&2; return 1; }
    local tool
    for tool in apt-get curl sha256sum dpkg dpkg-deb dpkg-query mktemp chmod realpath stat python3 gpg rm; do
        command -v "$tool" >/dev/null 2>&1 || { printf 'Required command is missing: %s\n' "$tool" >&2; return 1; }
    done
    python3 - <<'PY'
import os,shlex,stat,subprocess,sys
try:
    path='/etc/os-release'
    if os.path.islink(path):
        assert os.path.realpath(path)=='/usr/lib/os-release'
        path='/usr/lib/os-release'
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        m=os.fstat(f.fileno()); assert stat.S_ISREG(m.st_mode) and m.st_uid==0 and not m.st_mode&0o022 and m.st_size<=16384
        raw=f.read(16385); assert len(raw)<=16384
    values={}
    for line in raw.decode().splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        key,sep,value=line.partition('='); assert sep and key not in values
        words=shlex.split(value); assert len(words)==1
        values[key]=words[0]
    assert values.get('ID')=='ubuntu' and values.get('VERSION_ID') in ('24.04','26.04')
    assert subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()=='amd64'
except (AssertionError,OSError,UnicodeError,ValueError,subprocess.SubprocessError):
    sys.exit('Supported platform required: Ubuntu 24.04 or 26.04 amd64, with a readable regular /etc/os-release.')
PY
}

_agentsphere_apt_state() {
    python3 - "$@" <<'PY'
import hashlib,os,pathlib,stat,subprocess,sys,tempfile
P=pathlib.Path
KEY=P('/etc/apt/keyrings/medge-archive-keyring.gpg')
SOURCE=P('/etc/apt/sources.list.d/medge.sources')
SHA='756fc2632c307509b8e5ece665ced7f4d1a58636ac935aefc1e017f7dcfcbfbd'
FPR='AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0'
TEXT=b'Types: deb\nURIs: https://motebus.github.io/download\nSuites: stable\nComponents: main\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/medge-archive-keyring.gpg\n'
def directory(path,missing=False):
    try:m=path.lstat()
    except FileNotFoundError:
        if missing:return False
        raise ValueError('required APT directory is missing')
    if not stat.S_ISDIR(m.st_mode) or m.st_uid!=0 or m.st_mode&0o022:raise ValueError('APT directory is not trusted')
    return True
def read(path):
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    except FileNotFoundError:
        if path.is_symlink():raise ValueError('APT destination is a symlink')
        return None
    with os.fdopen(fd,'rb') as f:
        m=os.fstat(f.fileno())
        if not stat.S_ISREG(m.st_mode) or m.st_uid!=0 or m.st_mode&0o022 or m.st_size>1048576:raise ValueError('APT file is not a bounded trusted regular file')
        b=f.read(1048577)
        if len(b)>1048576:raise ValueError('APT file exceeds bound')
        return b

def inspect():
    directory(P('/etc'));directory(P('/etc/apt'))
    directory(KEY.parent,True);directory(SOURCE.parent,True)
    key=read(KEY);source=read(SOURCE)
    if key is not None and hashlib.sha256(key).hexdigest()!=SHA:raise ValueError('existing MoteBus archive key differs; preserved without replacement')
    if source is not None and source!=TEXT:raise ValueError('existing MoteBus APT source differs; preserved without replacement')
    candidates=[P('/etc/apt/sources.list')]
    if SOURCE.parent.exists():candidates+=list(SOURCE.parent.glob('*.list'))+list(SOURCE.parent.glob('*.sources'))
    for path in candidates:
        if path==SOURCE:continue
        b=read(path)
        if b is not None and any(b'motebus.github.io/download' in line.lower() for line in b.splitlines() if not line.lstrip().startswith(b'#')):
            raise ValueError('another MoteBus APT source is present; ambiguous setup preserved')
    return key,source

def publish(path,data):
    if not directory(path.parent,True):path.parent.mkdir(mode=0o755)
    directory(path.parent)
    fd,name=tempfile.mkstemp(prefix='.agentsphere-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),0o644);f.write(data);f.flush();os.fsync(f.fileno())
        os.link(name,path) # atomic create-only; never overwrite a concurrent file
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:os.unlink(name)
try:
    key,source=inspect()
    if sys.argv[1]=='check':
        print('complete' if key is not None and source is not None else 'source-only' if key is not None else 'key-needed')
    elif sys.argv[1]=='install':
        candidate=P(sys.argv[2]).read_bytes()
        if len(candidate)>131072 or hashlib.sha256(candidate).hexdigest()!=SHA:raise ValueError('downloaded archive key digest mismatch')
        gnupg=P(sys.argv[3])/'gnupg';gnupg.mkdir(mode=0o700)
        result=subprocess.run(['gpg','--batch','--no-options','--no-default-keyring','--homedir',str(gnupg),'--with-colons','--show-keys',sys.argv[2]],capture_output=True,text=True,timeout=15)
        if result.returncode:raise ValueError('archive key fingerprint inspection failed')
        fingerprints=[];pending=False
        for line in result.stdout.splitlines():
            fields=line.split(':')
            if fields[0]=='pub':pending=True
            elif fields[0]=='fpr' and pending:fingerprints.append(fields[9]);pending=False
        if fingerprints!=[FPR]:raise ValueError('archive key fingerprint mismatch')
        key,source=inspect() # detect concurrent changes before any publication
        if key is None:publish(KEY,candidate)
        if source is None:publish(SOURCE,TEXT)
        print('Signed MoteBus APT source configured; existing configuration preserved.')
    else:raise ValueError('invalid internal bootstrap action')
except (OSError,ValueError,subprocess.SubprocessError) as e:
    sys.exit('AgentSphere APT bootstrap refused: '+str(e))
PY
}

agentsphere_apt_bootstrap() (
    agentsphere_platform_check || exit
    local state temp key
    state=$(_agentsphere_apt_state check) || exit
    [ "$state" != complete ] || return 0
    temp=$(mktemp -d /var/tmp/agentsphere-bootstrap.XXXXXXXX) || exit
    chmod 0700 "$temp" || exit
    trap 'rm -rf -- "$temp"' EXIT
    if [ "$state" = source-only ]; then
        key=/etc/apt/keyrings/medge-archive-keyring.gpg
    else
        key=$temp/key.gpg
        curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --max-time 60 --max-filesize 131072 --output "$key" https://motebus.github.io/download/medge-archive-keyring.gpg || exit
    fi
    _agentsphere_apt_state install "$key" "$temp"
)

# END SIGNED BOOTSTRAP

agentsphere_platform_check || fail 'Platform preflight failed. No package or source change was started.'

# One classifier is used before downloads and again under APT's lock.
# It reads package metadata and hook bytes, never topology values.
classify_legacy_chatd() {
    local record query_status state version line path digest flag extra
    local protected=0 normal=0 other=0 identity hook expected actual
    local target=/etc/mote/mote-chatd/mote-chatd-mchat.env
    legacy_error() {
        printf '%s\n' "$1" 'Inspect mote-chatd Status, Version, Architecture and Conffiles with dpkg-query; do not print topology values or force package removal.' >&2
        return 1
    }
    if record=$(dpkg-query -W -f='${db:Status-Status}\n${Version}\n${Conffiles}\n' mote-chatd 2>/dev/null); then
        # DPKG may retain a relationship-only entry for an absent package.
        # Admit only its exact empty Version/Architecture/Conffiles identity.
        if [[ $record == not-installed ]]; then
            identity=$(dpkg-query -W -f='${Architecture}\n${Status}' mote-chatd 2>/dev/null) || return 1
            [[ $identity == $'\nunknown ok not-installed' ]] || { legacy_error 'Unreviewed empty legacy package record.'; return 1; }
            printf 'absent\n'; return 0
        fi
        local -a lines
        mapfile -t lines <<< "$record"
        [[ ${#lines[@]} -ge 2 ]] || { legacy_error 'Cannot classify legacy mote-chatd ownership.'; return 1; }
        state=${lines[0]}; version=${lines[1]}
        case "$state" in installed|config-files) ;; *) legacy_error 'Unsupported legacy mote-chatd DPKG state; repair the incomplete transaction first.'; return 1 ;; esac
        [[ -n $version ]] && dpkg --compare-versions "$version" le 2.0.0-6 \
            || { legacy_error 'Unsupported legacy mote-chatd version.'; return 1; }
        for line in "${lines[@]:2}"; do
            [[ -n ${line//[[:space:]]/} ]] || continue
            read -r path digest flag extra <<< "$line"
            [[ $digest =~ ^[0-9a-f]{32}$ && -z $extra && ( -z $flag || $flag == obsolete ) ]] \
                || { legacy_error 'Malformed legacy mote-chatd conffile record.'; return 1; }
            case "$path" in
                "$target") protected=$((protected + 1)) ;;
                /etc/mote/mote-chatd/mote-chatd-deb.env) normal=$((normal + 1)) ;;
                *) other=$((other + 1)) ;;
            esac
        done
        [[ $(stat -c '%F' -- "$target" 2>/dev/null) == 'regular file' ]] \
            || { legacy_error 'Existing legacy topology is missing or not a regular file; owner repair is required.'; return 1; }
        local target_access target_uid target_mode
        target_access=$(stat -c '%u:%a' -- "$target") || { legacy_error 'Cannot inspect topology access metadata.'; return 1; }
        target_uid=${target_access%%:*}; target_mode=${target_access#*:}
        [[ $target_uid == 0 && $target_mode =~ ^[0-7]{3,4}$ ]] && (( (8#$target_mode & 0022) == 0 )) \
            || { legacy_error 'Existing topology must be root-owned and not writable by group or others.'; return 1; }
        if [[ $protected == 1 ]]; then
            printf 'retention:%s\n' "$state"
            return 0
        fi
        [[ $protected == 0 && $normal == 1 && $other == 0 && $version == 2.0.0-4 ]] \
            || { legacy_error 'Legacy ownership does not match a supported retention or ordinary 2.0.0-4 migration.'; return 1; }
        identity=$(dpkg-query -W -f='${Architecture}\n${Status}' mote-chatd 2>/dev/null) \
            || { legacy_error 'Cannot inspect legacy package identity.'; return 1; }
        case "$identity" in
            $'amd64\ninstall ok installed'|$'amd64\ndeinstall ok config-files') ;;
            *) legacy_error 'Ordinary migration requires the reviewed amd64 package in a complete DPKG state.'; return 1 ;;
        esac
        # The ordinary release never owns the locked file. Its removal hooks
        # are pinned so custom or unknown cleanup logic cannot enter this path.
        for hook in postrm prerm; do
            [[ $hook != prerm || $state == installed ]] || continue
            case "$hook" in
                postrm) expected=cad515185035337dd03da926ff380a1cf5a47fd074b6ff7f8525f7d7d1384196 ;;
                prerm) expected=a583a5e196cab7845800d8bade6cca1b1e86db9d077e2749d24ce7ad3b224085 ;;
            esac
            path=/var/lib/dpkg/info/mote-chatd.$hook
            [[ $(stat -c '%u:%g:%a:%F' -- "$path" 2>/dev/null) == '0:0:755:regular file' ]] \
                || { legacy_error "Legacy $hook has unsupported ownership, mode or file type."; return 1; }
            actual=$(sha256sum "$path") || { legacy_error "Cannot inspect legacy $hook."; return 1; }
            [[ ${actual%% *} == "$expected" ]] \
                || { legacy_error "Legacy $hook differs from the reviewed 2.0.0-4 release."; return 1; }
        done
        printf 'ordinary:%s\n' "$state"
    else
        query_status=$?
        [[ $query_status == 1 && -z $record ]] \
            || { legacy_error 'Cannot inspect legacy mote-chatd ownership.'; return 1; }
        printf 'absent\n'
    fi
}
# The old removal hook deletes its managed Codex entry. Validate its exact
# normal ownership and stock table before downloads, then recheck under lock.
classify_legacy_mcp() {
python3 - <<'MCP_PREFLIGHT'
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tomllib

NORMAL = '/etc/mote/mote-bridge-mcp/mote-bridge-mcp-deb.env'
IDENTITY = '/etc/mote/mote-bridge-mcp/mote-bridge-mcp-mchat.env'
CONFIG = '/etc/codex/config.toml'
INFO = '/var/lib/dpkg/info/mote-bridge-mcp.'
STOCK = {'command': '/usr/bin/mote', 'args': ['mcp', 'serve'],
         'enabled': True, 'default_tools_approval_mode': 'auto'}


def checked(path, digest=None, mode=None, optional=False):
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError('required migration file is missing: ' + path)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or
            metadata.st_mode & 0o022 or
            (mode is not None and metadata.st_gid != 0) or
            (mode is not None and stat.S_IMODE(metadata.st_mode) != mode)):
        raise ValueError('unsafe migration file metadata: ' + path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME)
    try:
        before = os.fstat(fd)
        if metadata != before:
            raise ValueError('migration file changed during inspection: ' + path)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read()
        after = os.fstat(fd)
        if before != after:
            raise ValueError('migration file changed during inspection: ' + path)
    finally:
        os.close(fd)
    sha = hashlib.sha256(data).hexdigest()
    if digest is not None and sha != digest:
        raise ValueError('unreviewed migration file: ' + path)
    identity = (sha, after.st_ino, after.st_mtime_ns, after.st_ctime_ns,
                after.st_mode, after.st_uid, after.st_gid, after.st_nlink)
    return data, identity


def classify():
    result = subprocess.run(['dpkg-query', '-W', '-f=${Version}\n${Architecture}\n${Status}\n${Conffiles}',
                             'mote-bridge-mcp'], capture_output=True, text=True)
    if (result.returncode == 1 and not result.stdout) or (result.returncode == 0 and result.stdout == '\n\nunknown ok not-installed\n'):
        return 'absent'
    if result.returncode:
        raise ValueError('cannot inspect legacy MCP package metadata')
    lines = result.stdout.splitlines()
    if len(lines) != 4 or lines[:2] != ['3.0.0-2', 'amd64']:
        raise ValueError('legacy MCP package version, architecture or conffiles are unreviewed')
    state = {'install ok installed': 'installed', 'deinstall ok config-files': 'config-files'}.get(lines[2])
    if state is None:
        raise ValueError('legacy MCP package needs a completed DPKG state')
    conffile = lines[3].split()
    expected = [NORMAL, '7582d273536ba7102097a3c090f916d0']
    if conffile != expected:
        if state != 'config-files' or conffile != expected + ['obsolete']:
            raise ValueError('legacy MCP conffile ownership differs from the normal release')
        owner = subprocess.run(['dpkg-query', '-S', NORMAL], capture_output=True, text=True)
        successor = subprocess.run(['dpkg-query', '-W', '-f=${Version}|${Architecture}|${Status}',
                                    'mote-mcpd'], capture_output=True, text=True)
        if (owner.returncode or owner.stdout.strip() != 'mote-mcpd: ' + NORMAL or
                successor.returncode or successor.stdout != '3.0.0-3|amd64|install ok installed'):
            raise ValueError('obsolete legacy MCP conffile lacks its exact installed successor owner')
    # No old postrm exists in the reviewed release, including residual records.
    for hook in ('preinst', 'postrm'):
        if os.path.lexists(INFO + hook):
            raise ValueError('unreviewed legacy MCP ' + hook)
    evidence = {}
    for path, sha in (() if state != 'installed' else (
        (INFO + 'prerm', 'ab66dbe928eb706c0275dc1431f6350a24a55c13d77b6e34a3d4d7651f5aecac'),
        ('/usr/libexec/mote/install-codex-mcp', '6147acb2dc6dfebb44f0d4a9c3b9df2b3c8ec079172038a9dd663b3280624f85'))):
        evidence[path] = checked(path, digest=sha, mode=0o755)[1]
    evidence[IDENTITY] = checked(IDENTITY)[1]
    config = checked(CONFIG, optional=True)
    if config is not None:
        try:
            document = tomllib.loads(config[0].decode('utf-8'))
        except (UnicodeError, tomllib.TOMLDecodeError):
            raise ValueError('system Codex configuration is not valid TOML') from None
        servers = document.get('mcp_servers', {})
        if not isinstance(servers, dict):
            raise ValueError('system Codex MCP configuration is malformed')
        for name in ('mote-bridge-mcp', 'mote-mcpd'):
            if name in servers and (not isinstance(servers[name], dict) or servers[name] != STOCK or
                    type(servers[name].get('enabled')) is not bool):
                raise ValueError('customized system MCP entry requires a reviewed migration: ' + name)
        evidence[CONFIG] = config[1]
    else:
        evidence[CONFIG] = None
    return state + ':' + hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


if __name__ == '__main__':
    try:
        print(classify())
    except (OSError, ValueError) as error:
        print('Legacy MCP preflight refused: ' + str(error) +
              '. Inspect package metadata and managed system entry; do not print identity values or force removal.', file=sys.stderr)
        sys.exit(1)
MCP_PREFLIGHT
}

classify_legacy_cx() {
python3 - <<'CX_PREFLIGHT'
import hashlib,json,os,pwd,stat,subprocess,sys,tomllib
from pathlib import Path

REVIEWED = {('cx-agent', '0.3.4-2'): {'prerm': '145f52a16184feb342a77090805af0dabab4230b6e030d8f83349484e9868fdd', 'postrm': '02532aa278b2fc419fb9d0404fd03d59b9577f6471343b80cc763965667464a6'}, ('cx-agent', '0.3.4-3'): {'prerm': '145f52a16184feb342a77090805af0dabab4230b6e030d8f83349484e9868fdd', 'postrm': '02532aa278b2fc419fb9d0404fd03d59b9577f6471343b80cc763965667464a6'}, ('codex-mesh', '1.0.0-1'): {'prerm': None, 'postrm': None}, ('codex-mesh', '1.0.0-2'): {'prerm': None, 'postrm': None}, ('cx-node', '0.3.3-4'): {'prerm': '5a07af360b9e229fad483ba3ada220d81636f0a145ad38550542f9324432dfc3', 'postrm': 'fc2ae1c462331eeb4c7a93eee8b27012120ca620baf6d91dd4b2e714b39c2f99'}, ('cx-node', '0.3.3-6'): {'prerm': '5a07af360b9e229fad483ba3ada220d81636f0a145ad38550542f9324432dfc3', 'postrm': 'fc2ae1c462331eeb4c7a93eee8b27012120ca620baf6d91dd4b2e714b39c2f99'}, ('cx-node', '0.3.4-1~local20260909'): {'prerm': '2721920390b04cef164a34b5347a36a8794c3bb443462224ed83fbd440453cba', 'postrm': 'f6f8be756d1d6b62dd906b7587e55f15cf060073c0e0cbf46d4bb31840640087'}}
MESH_FILES = {'/etc/codex/skills/codex-mesh/SKILL.md':'382087d284fed820b9a96a0ad4c4fd8c',
              '/etc/mote/codex-mesh/config.json':'f60b18dbe124af2bec9eb264cd6598af'}

def checked(path, digest=None, mode=None, optional=False, limit=1048576, uid=0):
    try: before=os.lstat(path)
    except FileNotFoundError:
        if optional:return None
        raise ValueError('required CX migration file missing: '+path)
    if not stat.S_ISREG(before.st_mode) or before.st_uid!=uid or before.st_mode&0o022 or before.st_size>limit:
        raise ValueError('unsafe CX migration file metadata: '+path)
    if mode is not None and (stat.S_IMODE(before.st_mode)!=mode or before.st_gid!=0):
        raise ValueError('unreviewed CX removal hook metadata')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME)
    try:
        if os.fstat(fd)!=before:raise ValueError('CX migration file changed during inspection')
        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(limit+1)
        after=os.fstat(fd)
        if len(data)>limit or before!=after:raise ValueError('CX migration file changed during inspection')
    finally:os.close(fd)
    sha=hashlib.sha256(data).hexdigest()
    if digest is not None and sha!=digest:raise ValueError('unreviewed CX removal hook: '+path)
    return [sha,after.st_ino,after.st_mtime_ns,after.st_ctime_ns,after.st_mode,after.st_uid,after.st_gid,after.st_nlink]

def query(name):
    result=subprocess.run(['dpkg-query','-W','-f=${Version}\n${Architecture}\n${Status}\n${Conffiles}',name],capture_output=True,text=True)
    if (result.returncode==1 and not result.stdout) or (result.returncode==0 and result.stdout=='\n\nunknown ok not-installed\n'):return None
    if result.returncode:raise ValueError('cannot inspect CX predecessor package')
    return result.stdout

def unit_policy():
    found={}
    for base in ('/etc/systemd/system','/run/systemd/system'):
        for unit in ('cx-node.service','cx-agent.service'):
            path=Path(base)/unit
            if os.path.lexists(path):
                meta=path.lstat()
                if not path.is_symlink() or os.readlink(path)!='/dev/null' or meta.st_uid!=0:
                    raise ValueError('custom predecessor unit override requires owner review: '+str(path))
                found[str(path)]=[meta.st_ino,meta.st_mtime_ns,meta.st_ctime_ns,meta.st_mode,meta.st_uid,meta.st_gid]
            drop=Path(str(path)+'.d')
            if os.path.lexists(drop):
                meta=drop.lstat()
                if not stat.S_ISDIR(meta.st_mode) or meta.st_uid!=0 or meta.st_mode&0o022 or any(drop.iterdir()):
                    raise ValueError('custom predecessor unit drop-in requires owner review: '+str(drop))
                found[str(drop)]=[meta.st_ino,meta.st_mtime_ns,meta.st_ctime_ns,meta.st_mode,meta.st_uid,meta.st_gid]
    return found

# Only the genuine native old4 state is newly admitted. The old prerm invokes
# /usr/bin/cx, and DPKG removes its recorded .list, so bind both as well as hooks.
CX4_INSTALLED = {
    '/var/lib/dpkg/info/cx-node.list': ('000ac3041e1c83ad39706c55bf0e54d238ff8884667c45a777324cb7f29501af',0o644),
    '/var/lib/dpkg/info/cx-node.md5sums': ('6801c59d6faad1b6395446d2bc99acc9adfb368162d68fa25cf0f47ed8ebd104',0o644),
    '/var/lib/dpkg/info/cx-node.preinst': ('a23e97567e7055e177696fb8f630227fce9e719fe9b4139c48e31eb134b543b8',0o755),
    '/var/lib/dpkg/info/cx-node.postinst': ('9541131b3d13f23d17877dabcfb04b8cb5671a906180c223c1281cf013bfbd1f',0o755),
    '/usr/bin/cx': ('a1f6b6df70fee6ecc91810c9a16cede69fdc1484f392128a085be08221dc350e',0o755),
}
CX4_RESIDUAL_LIST = '9b1929abc85d2fe7261cc539a6705afdd34214ffddc18e994df2179222d9a30a'

def cx4_state(state, files):
    for suffix in ('conffiles','triggers'):
        if os.path.lexists('/var/lib/dpkg/info/cx-node.'+suffix):
            raise ValueError('unreviewed old4 ownership or triggers')
    if state=='install ok installed':
        checks=CX4_INSTALLED
        expected_owner='cx-node: /usr/bin/cx'
        # This receipt excludes the native recursive legacy-state copy/chown.
        receipt='/var/lib/cx-node/state/runtime-migration.json'
        try: owner_uid=pwd.getpwnam('cx-node').pw_uid
        except KeyError: raise ValueError('old4 service account is missing')
        files[receipt]=checked(receipt,uid=owner_uid)
        if files[receipt][-1]!=1:raise ValueError('unsafe old4 migration receipt link count')
    else:
        successor=query('cx-mesh')
        if successor is None or successor.splitlines()[:3]!=['1.1.0-1','amd64','install ok installed']:
            raise ValueError('old4 residual requires exact installed CX-Mesh successor')
        for suffix in ('preinst','postinst','prerm','md5sums'):
            if os.path.lexists('/var/lib/dpkg/info/cx-node.'+suffix):
                raise ValueError('unexpected old4 residual payload or hook')
        checks={'/var/lib/dpkg/info/cx-node.list':(CX4_RESIDUAL_LIST,0o644)}
        expected_owner='cx-mesh: /usr/bin/cx'
    for path,(digest,mode) in checks.items():
        files[path]=checked(path,digest=digest,mode=mode,limit=2097152 if path=='/usr/bin/cx' else 1048576)
        if files[path][-1]!=1:raise ValueError('unsafe old4 file link count')
    owner=subprocess.run(['dpkg-query','-S','/usr/bin/cx'],capture_output=True,text=True)
    if owner.returncode or owner.stdout.strip()!=expected_owner:
        raise ValueError('old4 drain command lacks sole expected package ownership')
    diverted=subprocess.run(['dpkg-divert','--list','/usr/bin/cx'],capture_output=True,text=True)
    if diverted.returncode or diverted.stdout.strip():raise ValueError('old4 drain command is diverted')

CX6_OBSOLETE_ROW = ['/etc/cx-node/cx-node.toml','d137b03f7f14c9c1369d3e85a9062130','obsolete']
CX6_OBSOLETE_INSTALLED = {
    '/var/lib/dpkg/info/cx-node.list': ('8aa5dbd95406f5ef29cb1cb11c9fe7048d2c4dec84b73d8f118094869ac15e0d',0o644),
    '/var/lib/dpkg/info/cx-node.md5sums': ('4a25baab18944de75e7514c27a4d73bc1ce2216752df3f967b4b541ffa57eb6a',0o644),
    '/var/lib/dpkg/info/cx-node.preinst': ('a23e97567e7055e177696fb8f630227fce9e719fe9b4139c48e31eb134b543b8',0o755),
    '/var/lib/dpkg/info/cx-node.postinst': ('9541131b3d13f23d17877dabcfb04b8cb5671a906180c223c1281cf013bfbd1f',0o755),
    '/usr/bin/cx': ('493c5faa394c13b0641b936c9e3c02f9d39c0e4e52eb1b52f027240e2383fa9d',0o755),
}
CX6_OBSOLETE_RESIDUAL_LIST = 'e6c9f3a963553f457f2e0da73074a433dc673cf0a158020a74b6caf5b12bd154'

def sole_owner(path, expected):
    owner=subprocess.run(['dpkg-query','-S',path],capture_output=True,text=True)
    if owner.returncode or owner.stdout.strip()!=expected+': '+path:
        raise ValueError('obsolete CX migration file lacks sole expected package ownership: '+path)
    diverted=subprocess.run(['dpkg-divert','--list',path],capture_output=True,text=True)
    if diverted.returncode or diverted.stdout.strip():raise ValueError('obsolete CX migration file is diverted: '+path)

def cx6_drain_state(files, owner_uid):
    # The genuine old prerm runs cx drain as root. Only its established state
    # root is admitted; never let owner TOML redirect a privileged file write.
    config=CX6_OBSOLETE_ROW[0]
    fd=os.open(config,os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME)
    try:
        before=os.fstat(fd)
        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(1048577)
        after=os.fstat(fd)
    finally:os.close(fd)
    identity=[hashlib.sha256(data).hexdigest(),after.st_ino,after.st_mtime_ns,after.st_ctime_ns,after.st_mode,after.st_uid,after.st_gid,after.st_nlink]
    if len(data)>1048576 or before!=after or identity!=files[config]:raise ValueError('obsolete CX config changed during state inspection')
    try:document=tomllib.loads(data.decode('utf-8'))
    except (UnicodeError,tomllib.TOMLDecodeError):raise ValueError('obsolete CX configuration is not valid TOML') from None
    if not isinstance(document.get('state'),dict) or document['state'].get('path')!='/var/lib/cx-node':
        raise ValueError('obsolete CX drain requires the reviewed state directory')
    for path in ('/','/var','/var/lib','/var/lib/cx-node','/var/lib/cx-node/state'):
        meta=os.lstat(path)
        allowed=(0,owner_uid) if path.startswith('/var/lib/cx-node') else (0,)
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid not in allowed or meta.st_mode&0o022:
            raise ValueError('unsafe obsolete CX state directory: '+path)
        files[path]=[meta.st_dev,meta.st_ino,meta.st_mtime_ns,meta.st_ctime_ns,meta.st_mode,meta.st_uid,meta.st_gid,meta.st_nlink]
    marker='/var/lib/cx-node/state/draining'
    if os.path.lexists(marker):
        meta=os.lstat(marker)
        if meta.st_uid not in (0,owner_uid):raise ValueError('unsafe obsolete CX drain marker owner')
        files[marker]=checked(marker,uid=meta.st_uid)
        if files[marker][-1]!=1:raise ValueError('unsafe obsolete CX drain marker link count')
    else:files[marker]=None

def cx6_obsolete_state(state, rows, files):
    if rows!=[CX6_OBSOLETE_ROW]:raise ValueError('unreviewed CX predecessor conffile ownership')
    # Actual 0.3.1-4 -> 0.3.3-1 -> 0.3.3-6 DPKG history leaves no
    # .conffiles file. Its obsolete TOML remains in both installed and rc lists.
    for suffix in ('conffiles','triggers'):
        if os.path.lexists('/var/lib/dpkg/info/cx-node.'+suffix):raise ValueError('unexpected obsolete CX ownership or triggers')
    for path in ('/etc','/etc/cx-node'):
        meta=os.lstat(path)
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid!=0 or meta.st_mode&0o022:
            raise ValueError('unsafe obsolete CX configuration directory: '+path)
        files[path]=[meta.st_dev,meta.st_ino,meta.st_mtime_ns,meta.st_ctime_ns,meta.st_mode,meta.st_uid,meta.st_gid,meta.st_nlink]
    for path in (CX6_OBSOLETE_ROW[0],'/etc/cx-node/cx-node-mchat.env'):
        files[path]=checked(path)
        if files[path][-1]!=1:raise ValueError('unsafe obsolete CX owner file link count')
    sole_owner(CX6_OBSOLETE_ROW[0],'cx-node') # Residual predecessor retains the actual conffile ownership.
    if state=='install ok installed':
        checks=CX6_OBSOLETE_INSTALLED
        expected_owner='cx-node'
        try:owner_uid=pwd.getpwnam('cx-node').pw_uid
        except KeyError:raise ValueError('obsolete CX service account is missing')
        cx6_drain_state(files,owner_uid)
        receipt='/var/lib/cx-node/state/runtime-migration.json'
        files[receipt]=checked(receipt,uid=owner_uid)
        if files[receipt][-1]!=1:raise ValueError('unsafe obsolete CX migration receipt link count')
    else:
        successor=query('cx-mesh')
        if successor is None or successor.splitlines()[:3]!=['1.1.0-1','amd64','install ok installed']:
            raise ValueError('obsolete CX residual requires exact installed CX-Mesh successor')
        for suffix in ('preinst','postinst','prerm','md5sums'):
            if os.path.lexists('/var/lib/dpkg/info/cx-node.'+suffix):raise ValueError('unexpected obsolete CX residual payload or hook')
        checks={'/var/lib/dpkg/info/cx-node.list':(CX6_OBSOLETE_RESIDUAL_LIST,0o644)}
        expected_owner='cx-mesh'
    for path,(digest,mode) in checks.items():
        files[path]=checked(path,digest=digest,mode=mode,limit=2097152 if path=='/usr/bin/cx' else 1048576)
        if files[path][-1]!=1:raise ValueError('unsafe obsolete CX migration file link count')
    sole_owner('/usr/bin/cx',expected_owner)

def classify():
    records={name:query(name) for name in ('cx-node','cx-agent','codex-mesh')}
    if all(record is None for record in records.values()):return 'absent'
    files={};installed={name:'-' for name in records}
    for name,record in records.items():
        if record is None:continue
        lines=record.splitlines()
        if len(lines)<3:raise ValueError('malformed CX predecessor record')
        version,arch,state=lines[:3]
        if (name,version) not in REVIEWED or arch!='amd64' or state not in ('install ok installed','deinstall ok config-files'):
            raise ValueError('unsupported CX predecessor version, architecture or DPKG state')
        hooks=REVIEWED[(name,version)]
        rows=[line.split() for line in lines[3:] if line.strip()]
        cx6_obsolete=(name,version)==('cx-node','0.3.3-6') and bool(rows)
        if cx6_obsolete:cx6_obsolete_state(state,rows,files)
        elif name!='codex-mesh' and rows:raise ValueError('unreviewed CX predecessor conffile ownership')
        if (name,version)==('cx-node','0.3.3-4'):cx4_state(state,files)
        if name=='codex-mesh':
            wanted=sorted([[path,digest] for path,digest in MESH_FILES.items()])
            if state=='deinstall ok config-files' and sorted(rows)==[row+['obsolete'] for row in wanted]:
                successor=query('cx-mesh')
                if successor is None or successor.splitlines()[:3]!=['1.1.0-1','amd64','install ok installed']:
                    raise ValueError('residual Mesh conffiles require exact installed successor')
                for path in MESH_FILES:
                    owner=subprocess.run(['dpkg-query','-S',path],capture_output=True,text=True)
                    if owner.returncode or owner.stdout.strip()!='cx-mesh: '+path:raise ValueError('residual Mesh conffile lacks sole successor ownership')
            elif sorted(rows)!=wanted:raise ValueError('unreviewed Mesh conffile ownership')
            for path in MESH_FILES:files[path]=checked(path)
            for hook in ('preinst','postinst','prerm','postrm'):
                if os.path.lexists('/var/lib/dpkg/info/'+name+'.'+hook):raise ValueError('unexpected Mesh cleanup hook')
        else:
            for hook in ('prerm','postrm'):
                if hook=='prerm' and state!='install ok installed':continue
                path='/var/lib/dpkg/info/'+name+'.'+hook
                files[path]=checked(path,digest=hooks[hook],mode=0o755)
                if (version=='0.3.3-4' or cx6_obsolete) and files[path][-1]!=1:raise ValueError('unsafe CX removal hook link count')
        if state=='install ok installed':installed[name]=version
    files.update(unit_policy())
    config='/etc/cx-node/cx-node.toml';identity='/etc/cx-node/cx-node-mchat.env'
    if os.path.lexists(config):
        files[config]=checked(config);files[identity]=checked(identity)
    elif os.path.lexists(identity):files[identity]=checked(identity)
    mesh_identity='/etc/mote/codex-mesh/codex-mesh-mchat.env'
    if os.path.lexists(mesh_identity):files[mesh_identity]=checked(mesh_identity)
    fingerprint=hashlib.sha256(json.dumps({'records':records,'files':files},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return ','.join(name+'='+version for name,version in installed.items())+';sha256:'+fingerprint

if __name__=='__main__':
    try:print(classify())
    except (OSError,ValueError) as error:
        print('CX-Mesh migration preflight refused: '+str(error)+'. Inspect nonsecret package/unit metadata; do not force removal.',file=sys.stderr)
        sys.exit(1)
CX_PREFLIGHT
}

# The released frontend owns no service, configuration or cleanup hooks.
# Pin the removal file list as well as its clean executable/shortcut state.
classify_legacy_manager() {
python3 - <<'MANAGER_PREFLIGHT'
import hashlib
import json
import os
import stat
import subprocess
import sys

MANAGER_PACKAGE = 'sphere-manager'
INFO = '/var/lib/dpkg/info/sphere-manager.'
FILES = {
    '/usr/bin/sphere-manager': (0o755, '85bb3fb568b30fbbcdbae1ddc04ace65e9a3c64e27577b56b6d147d59b2d5b42'),
    INFO + 'md5sums': (0o644, '92be0d236d0be35a9946b0be1e15d762d47758de3af305512be1ab38aa73a8b2'),
    INFO + 'list': (0o644, 'b5eb1da26b13044d1ce3bd261f0eae797b44c94b2f74f175e406019b6b2564f5'),
}


def identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mode,
            value.st_uid, value.st_gid, value.st_nlink,
            value.st_mtime_ns, value.st_ctime_ns)


def checked(path, mode, expected):
    before = os.lstat(path)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
            or stat.S_IMODE(before.st_mode) != mode or before.st_nlink != 1 or before.st_size > 1048576):
        raise ValueError('unsafe legacy Manager file metadata: ' + path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME)
    try:
        if identity(before) != identity(os.fstat(fd)):
            raise ValueError('legacy Manager file changed during inspection: ' + path)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(1048577)
        if len(data) > 1048576:
            raise ValueError('legacy Manager file exceeds the inspection limit: ' + path)
        digest = hashlib.sha256(data).hexdigest()
        if identity(before) != identity(os.fstat(fd)):
            raise ValueError('legacy Manager file changed during inspection: ' + path)
    finally:
        os.close(fd)
    if digest != expected:
        raise ValueError('legacy Manager file differs from the reviewed release: ' + path)
    return (digest, identity(before))


def sole_owner(path):
    result = subprocess.run(['dpkg-query', '-S', path], capture_output=True, text=True)
    if result.returncode or result.stdout != MANAGER_PACKAGE + ': ' + path + '\n':
        raise ValueError('legacy Manager lacks sole package ownership: ' + path)


def classify():
    result = subprocess.run(['dpkg-query', '-W', '-f=${Version}|${Architecture}|${Status}|${Conffiles}',
                             MANAGER_PACKAGE], capture_output=True, text=True)
    if ((result.returncode == 1 and not result.stdout) or
            (result.returncode == 0 and result.stdout == '||unknown ok not-installed|')):
        return 'absent'
    if result.returncode or result.stdout != '3.1.0-1|amd64|install ok installed|':
        raise ValueError('legacy Manager requires the reviewed 3.1.0-1 amd64 installed state without conffiles')
    for name in ('preinst', 'postinst', 'prerm', 'postrm', 'conffiles'):
        if os.path.lexists(INFO + name):
            raise ValueError('legacy Manager has unexpected configuration or lifecycle hooks')
    for directory in ('/etc/systemd/system', '/run/systemd/system', '/usr/lib/systemd/system', '/lib/systemd/system'):
        for suffix in ('.service', '.service.d'):
            if os.path.lexists(directory + '/sphere-manager' + suffix):
                raise ValueError('legacy Manager has an unsupported service or override')
    files = {path: checked(path, mode, digest) for path, (mode, digest) in FILES.items()}
    sole_owner('/usr/bin/sphere-manager')
    path = '/usr/bin/sphere'
    before = os.lstat(path)
    if (not stat.S_ISLNK(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
            or os.readlink(path) != 'sphere-manager'):
        raise ValueError('legacy Manager shortcut differs from the reviewed release')
    if identity(before) != identity(os.lstat(path)):
        raise ValueError('legacy Manager shortcut changed during inspection')
    sole_owner(path)
    files[path] = ('sphere-manager', identity(before))
    digest = hashlib.sha256(json.dumps({'record': result.stdout, 'files': files},
                                      sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return 'installed:sha256:' + digest


if __name__ == '__main__':
    try:
        print(classify())
    except (OSError, ValueError) as error:
        print('AGPC Manager migration preflight refused: ' + str(error) +
              '. Inspect nonsecret package/file metadata; do not force removal.', file=sys.stderr)
        sys.exit(1)
MANAGER_PREFLIGHT
}

legacy_state=$(classify_legacy_chatd) || fail 'Legacy preflight failed. No download or package change was started.'
mcp_state=$(classify_legacy_mcp) || fail 'MCP preflight failed. No download or package change was started.'
cx_state=$(classify_legacy_cx) || fail 'CX preflight failed. No download or package change was started.'
manager_state=$(classify_legacy_manager) || fail 'Manager preflight failed. No download or package change was started.'

agentsphere_apt_bootstrap || fail 'Signed APT bootstrap failed. Package installation was not started.'

umask 077
temporary=$(mktemp -d /var/tmp/agent-sphere-apps.XXXXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
obsidian="$temporary/obsidian_1.13.7_amd64.deb"
curl --fail --location --proto '=https' --proto-redir '=https' --retry 2 \
    --output "$obsidian" \
    https://github.com/obsidianmd/obsidian-releases/releases/download/v1.13.7/obsidian_1.13.7_amd64.deb
printf '%s  %s\n' 17dc33b49cb3e785ecc27edd2ea0c79e40207798b554fd2886e36ebee7af9ae0 "$obsidian" | sha256sum --check --status \
    || fail 'Official Obsidian checksum mismatch. Package installation was not started.'
[[ $(dpkg-deb -f "$obsidian" Package) == obsidian && \
   $(dpkg-deb -f "$obsidian" Version) == 1.13.7 && \
   $(dpkg-deb -f "$obsidian" Architecture) == amd64 ]] \
    || fail 'Official Obsidian package metadata mismatch. Package installation was not started.'
chmod 0755 "$temporary"
chmod 0644 "$obsidian"
packages=(agent-sphere=0.2.0-4 agent-ultra=0.1.0-1 agpc-manager=3.1.0-2 agent-apps=0.2.0-1 "$obsidian")
# Preserve DPKG ownership of the locked legacy identity with the reviewed
# documentation-only record. Never remove a protected mote-chatd record.
if [[ $legacy_state == retention:* ]]; then
    packages+=(mote-chatd=2.0.0-6)
elif [[ $legacy_state == ordinary:* ]]; then
    # An installed old name otherwise makes APT prefer its newer retention
    # candidate. Explicitly select the reviewed normal replacement path.
    packages+=(mote-chatd-)
fi

# APT protocol v3 is checked again under APT's lock before any DPKG action.
{
printf '%s\n' '#!/bin/bash' 'set -euo pipefail'
declare -f classify_legacy_chatd classify_legacy_mcp classify_legacy_cx classify_legacy_manager
printf 'expected_legacy_state=%q\n' "$legacy_state"
printf 'expected_mcp_state=%q\n' "$mcp_state"
printf 'expected_cx_state=%q\n' "$cx_state"
printf 'expected_manager_state=%q\n' "$manager_state"
cat <<'GUARD'
fail() { printf 'Agent Computer transaction refused: %s\n' "$*" >&2; exit 1; }
legacy_state=$(classify_legacy_chatd) || fail 'legacy ownership is unsupported at transaction time'
[[ $legacy_state == "$expected_legacy_state" ]] || fail 'legacy ownership changed after preflight'
mcp_state=$(classify_legacy_mcp) || fail 'legacy MCP state is unsupported at transaction time'
[[ $mcp_state == "$expected_mcp_state" ]] || fail 'legacy MCP state changed after preflight'
cx_state=$(classify_legacy_cx) || fail 'legacy CX state is unsupported at transaction time'
[[ $cx_state == "$expected_cx_state" ]] || fail 'legacy CX state changed after preflight'
manager_state=$(classify_legacy_manager) || fail 'legacy Manager state is unsupported at transaction time'
[[ $manager_state == "$expected_manager_state" ]] || fail 'legacy Manager state changed after preflight'
[[ ${APT_HOOK_INFO_FD:-} == 0 ]] || fail 'APT action protocol is unavailable'
IFS= read -r header || fail 'empty action protocol'
[[ $header == 'VERSION 3' ]] || fail 'APT action protocol version 3 is required'
config_end=false
while IFS= read -r line; do
    if [[ -z $line ]]; then config_end=true; break; fi
    [[ $line == *=* ]] || fail 'malformed APT configuration record'
done
$config_end || fail 'incomplete APT action protocol'
declare -A removed=() installed=() configured=() artifacts=()
public_cx_migration=false
declare -A replacement=([mote-sync]=mote-vault-sync [mote-syncd]=mote-vault-syncd [model-node]=model-llm)
declare -A reviewed_old=([mote-sync]=1.1.0-2 [mote-syncd]=1.1.0-2 [model-node]=0.1.0-2)
if [[ $legacy_state == ordinary:installed ]]; then
    replacement[mote-chatd]=mote-transportd
    reviewed_old[mote-chatd]=2.0.0-4
fi
if [[ $mcp_state == installed:* ]]; then
    replacement[mote-bridge-mcp]=mote-mcpd
    reviewed_old[mote-bridge-mcp]=3.0.0-2
fi
if [[ $manager_state == installed:sha256:* ]]; then
    replacement[sphere-manager]=agpc-manager
    reviewed_old[sphere-manager]=3.1.0-1
fi
IFS=, read -r -a cx_predecessors <<< "${cx_state%%;*}"
for entry in "${cx_predecessors[@]}"; do
    name=${entry%%=*}; version=${entry#*=}
    case "$name" in cx-node|cx-agent|codex-mesh)
        if [[ $version != - ]]; then replacement[$name]=cx-mesh; reviewed_old[$name]=$version; fi ;;
    esac
done
declare -A floor=([agent-sphere]=0.2.0-4 [agent-ultra]=0.1.0-1 [agpc-manager]=3.1.0-2 [agent-apps]=0.2.0-1 [moted]=3.6.0-2 [medge]=3.1.0-2 [mlink]=2.1.0-1 [mote-transportd]=2.0.0-6 [mote-chatd]=2.0.0-6 [agos]=2.1.0-1 [cx-mesh]=1.1.0-1 [mote-mcpd]=3.0.0-3 [model-router]=0.1.0-1 [model-llm]=0.1.0-3 [mote-vault-sync]=1.1.0-3 [mote-vault-syncd]=1.1.0-3)
while IFS= read -r line; do
    read -r -a fields <<< "$line"
    [[ ${#fields[@]} == 9 ]] || fail 'malformed package action'
    name=${fields[0]}; old=${fields[1]}; direction=${fields[4]}
    new=${fields[5]}; action=${fields[8]}
    [[ $name =~ ^[a-z0-9][a-z0-9+.-]*$ ]] || fail 'invalid package name'
    [[ $direction == '<' || $direction == '=' || $direction == '>' ]] || fail 'invalid version action'
    if [[ $action == '**REMOVE**' ]]; then
        case "$name" in cx-node|cx-agent|codex-mesh) public_cx_migration=true ;; esac
        [[ -n ${replacement[$name]:-} && $old == "${reviewed_old[$name]}" && $new == - && -z ${removed[$name]:-} ]] || fail "removal of $name"
        removed[$name]=true
    elif [[ $action == '**CONFIGURE**' || $action == /*.deb ]]; then
        [[ $name != mote-chatd || $legacy_state == retention:* ]] || fail 'retention is not admitted for this ownership state'
        case "$name" in sphere-manager|mote-sync|mote-syncd|cx-node|cx-agent|codex-mesh|model-node|model-grid|mcp-run|ultra-mcp-ssh|mote-bridge-mcp) fail "retired package $name" ;; esac
        [[ $new != - ]] || fail 'missing target version'
        [[ $old == - ]] || dpkg --compare-versions "$new" ge "$old" || fail "downgrade of $name"
        if [[ -n ${floor[$name]:-} ]]; then
            dpkg --compare-versions "$new" ge "${floor[$name]}" || fail "obsolete package $name"
        fi
        if [[ $name == agent-sphere || $name == agent-apps || $name == agent-ultra || $name == agpc-manager ]]; then
            [[ $new == "${floor[$name]}" ]] || fail "unexpected composition version $name"
        fi
        if [[ $name == mote-transportd && $legacy_state == ordinary:* ]]; then
            [[ $new == 2.0.0-6 && ${fields[6]} == amd64 ]] || fail 'ordinary migration requires exact transport 2.0.0-6 amd64'
            if [[ $action == /*.deb ]]; then
                [[ ! -L $action && -f $action ]] || fail 'unsafe transport artifact'
                printf '%s  %s\n' 9c56cade3f014f75876cce126d2ef8c9d5c27a60709ff592ac0e9af9788dd23f "$action" | sha256sum --check --status || fail 'transport artifact changed'
            fi
        fi
        if [[ $action == /*.deb ]]; then
            [[ -z ${installed[$name]:-} ]] || fail "duplicate installation $name"
            installed[$name]=$new
            artifacts[$name]=$action
            if [[ $name == obsidian ]]; then
                [[ $new == 1.13.7 && ! -L $action && -f $action ]] || fail 'unexpected Obsidian artifact'
                printf '%s  %s\n' 17dc33b49cb3e785ecc27edd2ea0c79e40207798b554fd2886e36ebee7af9ae0 "$action" | sha256sum --check --status || fail 'Obsidian artifact changed'
            fi
        else
            [[ -z ${configured[$name]:-} ]] || fail "duplicate configuration $name"
            configured[$name]=$new
        fi
    else
        fail 'unknown package action'
    fi
done
for name in "${!removed[@]}"; do
    [[ -n ${installed[${replacement[$name]}]:-} ]] || fail "$name removal lacks its reviewed replacement"
done
if $public_cx_migration; then
    [[ ${installed[cx-mesh]:-} == 1.1.0-1 ]] || fail 'public CX migration requires exact cx-mesh 1.1.0-1'
    path=${artifacts[cx-mesh]}
    [[ ! -L $path && -f $path ]] || fail 'unsafe CX artifact'
    [[ $(dpkg-deb -f "$path" Architecture) == amd64 ]] || fail 'unexpected CX artifact architecture'
    printf '%s  %s\n' 5c8de2c9ff7fe2143514be6069c8a7c10fe83da8cab8bee30731c360324c8746 "$path" | sha256sum --check --status || fail 'CX artifact changed'
fi
if [[ -n ${removed[mote-bridge-mcp]:-} ]]; then
    [[ ${installed[mote-mcpd]:-} == 3.0.0-3 ]] || fail 'MCP migration requires exact mote-mcpd 3.0.0-3'
    path=${artifacts[mote-mcpd]}
    [[ ! -L $path && -f $path ]] || fail 'unsafe MCP artifact'
    [[ $(dpkg-deb -f "$path" Architecture) == amd64 ]] || fail 'unexpected MCP artifact architecture'
    printf '%s  %s\n' b4b1b640cb32f087af0a22b40f3edc85562bc9c87551ea60b7f6f7d80ca5fcf7 "$path" | sha256sum --check --status || fail 'MCP artifact changed'
fi
if [[ -n ${removed[sphere-manager]:-} ]]; then
    [[ ${installed[agpc-manager]:-} == 3.1.0-2 ]] || fail 'Manager migration requires exact agpc-manager 3.1.0-2'
    path=${artifacts[agpc-manager]}
    [[ ! -L $path && -f $path ]] || fail 'unsafe Manager artifact'
    [[ $(dpkg-deb -f "$path" Architecture) == amd64 ]] || fail 'unexpected Manager artifact architecture'
    printf '%s  %s\n' cc1a1f2727dbf91c1cee3ffac7d273131f22e0f2cc1ade787173bf7ebbfae9fc "$path" | sha256sum --check --status || fail 'Manager artifact changed'
fi
GUARD
} > "$temporary/guard"
chmod 0700 "$temporary/guard"
guard=$(realpath "$temporary/guard")
[[ $guard =~ ^/[a-zA-Z0-9_./-]+$ ]] || fail 'Invalid temporary hook path.'
apt-get update || fail 'APT update failed. Package installation was not started.'
if ! apt-get --simulate install "${packages[@]}" > "$temporary/plan"; then
    cat "$temporary/plan"
    fail 'All four entry packages and their dependencies must be available in the signed MoteBus APT repository. Package installation was not started.'
fi
cat "$temporary/plan"
declare -A removed=() planned=()
while read -r action package rest; do
    name=${package%%:*}
    case "$action" in
        Remv)
            case "$name:$rest" in
                'mote-chatd:[2.0.0-4]'*)
                    [[ $legacy_state == ordinary:installed ]] || fail 'Refusing removal of protected or unreviewed mote-chatd ownership.'
                    removed[mote-chatd]=mote-transportd ;;
                'mote-bridge-mcp:[3.0.0-2]'*)
                    [[ $mcp_state == installed:* ]] || fail 'Refusing unreviewed MCP package removal.'
                    removed[mote-bridge-mcp]=mote-mcpd ;;
                'sphere-manager:[3.1.0-1]'*)
                    [[ $manager_state == installed:sha256:* ]] || fail 'Refusing unreviewed Manager package removal.'
                    removed[sphere-manager]=agpc-manager ;;
                'mote-sync:[1.1.0-2]'*) removed[mote-sync]=mote-vault-sync ;;
                'mote-syncd:[1.1.0-2]'*) removed[mote-syncd]=mote-vault-syncd ;;
                cx-node:*|cx-agent:*|codex-mesh:*)
                    expected=-
                    IFS=, read -r -a predecessors <<< "${cx_state%%;*}"
                    for entry in "${predecessors[@]}"; do
                        [[ ${entry%%=*} != "$name" ]] || expected=${entry#*=}
                    done
                    [[ $expected != - && $rest == "[$expected]"* ]] || fail 'Refusing unreviewed CX predecessor removal.'
                    removed[$name]=cx-mesh ;;
                'model-node:[0.1.0-2]'*) removed[model-node]=model-llm ;;
                *) fail "Refusing package removal: $name. Package installation was not started." ;;
            esac ;;
        Purg|E:) fail 'APT error or purge refused. Package installation was not started.' ;;
        Inst) planned[$name]=true ;;
    esac
done < "$temporary/plan"
for name in "${!removed[@]}"; do
    [[ -n ${planned[${removed[$name]}]:-} ]] || fail "$name removal lacks its replacement. Package installation was not started."
done
# A piped script has no interactive stdin. Obtain the controlling terminal
# explicitly; without one, the caller must choose --yes for unattended use.
if [[ ${#confirmation[@]} == 0 && ! -t 0 ]]; then
    if ! { exec {confirmation_fd}<>/dev/tty; } 2>/dev/null; then
        fail 'APT confirmation needs a terminal. Run with --yes only to explicitly approve unattended installation.'
    fi
else
    exec {confirmation_fd}<&0
fi
apt-get -o "DPkg::Pre-Install-Pkgs::=$guard" \
    -o "DPkg::Tools::Options::$guard::Version=3" \
    -o "DPkg::Tools::Options::$guard::InfoFD=0" \
    -o 'Dpkg::Options::=--force-confold' \
    "${confirmation[@]}" install "${packages[@]}" <&"$confirmation_fd"
printf '%s\n' 'Agent Sphere, Agent Ultra, AGPC Manager and Agent Apps packages installed. Runtime configuration and health are separate checks.'
printf '%s\n' 'Use agpc-manager to configure owner grants and inspect live status.'
