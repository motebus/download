#!/usr/bin/python3
"""Real accounts and historical DPKG residuals; no live services or credentials."""
import hashlib,json,os,pwd,grp,shlex,subprocess,sys
from pathlib import Path

def run(*args):
    result=subprocess.run(args,capture_output=True,text=True)
    if result.returncode:raise RuntimeError(str(args)+'\n'+result.stdout+'\n'+result.stderr)
    return result.stdout+result.stderr

def dummy(name, directories=()):
    root=Path('/tmp/deps')/name;(root/'DEBIAN').mkdir(parents=True)
    (root/'DEBIAN/control').write_text(f'Package: {name}\nVersion: 99.0\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\nDescription: Isolated dependency stand-in\n')
    for directory in directories:(root/directory).mkdir(parents=True,exist_ok=True)
    output='/tmp/'+name+'.deb';run('dpkg-deb','--build','--root-owner-group',str(root),output);return output

def fingerprint(path):
    with Path(path).open('rb') as file:
        meta=os.fstat(file.fileno());digest=hashlib.sha256(file.read()).hexdigest()
    return [digest,meta.st_ino,meta.st_mtime_ns,meta.st_uid,meta.st_gid,meta.st_mode]

def guard(source,expected):
    function=source.split('classify_legacy_cx() {\n',1)[1].split('\nCX_PREFLIGHT\n}',1)[0]
    body=source.split("cat <<'GUARD'\n",1)[1].split('\nGUARD\n',1)[0]
    container=source.split('agentsphere_container_runtime_package() {\n',1)[1].split('\n}\n',1)[0]
    script='#!/bin/bash\nset -euo pipefail\nagentsphere_container_runtime_package() {\n'+container+'\n}\nclassify_legacy_cx() {\n'+function+'\nCX_PREFLIGHT\n}\n'
    for component in ['chatd','mcp','manager','uchat']:script+='classify_legacy_'+component+'() { echo absent; }\n'
    script+='expected_legacy_state=absent\nexpected_mcp_state=absent\nexpected_manager_state=absent\nexpected_uchat_state=absent\nexpected_cx_state='+shlex.quote(expected)+'\n'+body
    path=Path('/tmp/production-guard');path.write_text(script);path.chmod(0o700)
    return ['-o','DPkg::Pre-Install-Pkgs::='+str(path),'-o','DPkg::Tools::Options::'+str(path)+'::Version=3','-o','DPkg::Tools::Options::'+str(path)+'::InfoFD=0']

def main():
    assert os.geteuid()==0 and Path('/.dockerenv').exists()
    scenario=sys.argv[1];assert scenario in ['old1','old6']
    Path('/.cx-rename-fixture').touch()
    Path('/usr/bin/systemctl').write_bytes(Path('/source/tests/cx-mesh-upgrade/systemctl.py').read_bytes())
    Path('/usr/bin/systemctl').chmod(0o755)
    Path('/run/systemd/system').mkdir(parents=True,exist_ok=True)
    Path('/usr/sbin/policy-rc.d').unlink(missing_ok=True)
    os.environ['DEBIAN_FRONTEND']='noninteractive'
    for name in ['moted','mote-bridge-mcp','mote-mcpd','mote-chatd','mote-transportd','codex','chatgpt','motemcp']:
        run('dpkg','-i',dummy(name))
    # Minimal containers omit ownership of shared directories present on the
    # reviewed hosts, including pre-usrmerge /lib systemd directories. Supply
    # real DPKG ownership, without editing its database.
    run('dpkg','-i',dummy('system-directory-owner',('usr/bin','usr/lib','usr/libexec','lib/systemd/system')))
    run('dpkg','-i','/packages/historical.deb')
    run('dpkg','-i','/packages/old1.deb')
    if scenario=='old6':run('dpkg','-i','/packages/old6.deb')
    run('dpkg','-i','/packages/old-mesh.deb')
    apt=['apt-get','-y','-o','APT::Sandbox::User=root','-o','Dpkg::Options::=--force-confold']
    if scenario=='old6':
        # Match the previously reviewed lab sequence through CX Mesh 1.1.
        run(*apt,'install','/packages/baseline.deb')
        assert Path('/var/lib/dpkg/info/cx-node.list').read_text()=='/etc/cx-node/cx-node.toml\n', repr(Path('/var/lib/dpkg/info/cx-node.list').read_text())
    run(*apt,'install','/packages/consolidated.deb')
    old=pwd.getpwnam('cx-node');old_gid=grp.getgrnam('cx-node').gr_gid
    assert old.pw_uid>0 and old_gid>0
    record=run('dpkg-query','-W','-f=${Version}\n${Status}\n${Conffiles}','cx-node')
    assert 'deinstall ok config-files' in record and '/etc/cx-node/cx-node.toml' in record
    state=Path('/var/lib/cx-node')
    for name in ['sessions/fixture.json','.codex/auth.json']:
        path=state/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('fixture bytes, no real credentials\n');path.chmod(0o600);os.chown(path,old.pw_uid,old_gid);os.chown(path.parent,old.pw_uid,old_gid)
    before={name:fingerprint(name) for name in ['/etc/cx-node/cx-node-mchat.env',str(state/'sessions/fixture.json'),str(state/'.codex/auth.json')]}
    source=Path('/source/agpc.sh').read_text()
    classifier=source.split("python3 - <<'CX_PREFLIGHT'\n",1)[1].split('\nCX_PREFLIGHT\n',1)[0]
    Path('/tmp/classifier.py').write_text(classifier)
    initial=run('python3','/tmp/classifier.py').strip()
    if sys.argv[2:]==['--historical-only']:
        print(json.dumps({'scenario':scenario,'historical_preflight_passed':True}));return
    assert len(sys.argv)==2
    run(*apt,*guard(source,initial),'install','/packages/new.deb')
    assert not run('dpkg','--audit').strip()
    assert run('dpkg-query','-W','-f=${Version}\n${Status}\n${Conffiles}','cx-node')==record
    current=pwd.getpwnam('cx-mesh');assert current.pw_uid==old.pw_uid and grp.getgrnam('cx-mesh').gr_gid==old_gid
    assert current.pw_dir=='/var/lib/cx-mesh'
    for name,expected in before.items():assert fingerprint(name.replace('cx-node','cx-mesh'))==expected,name
    for name in ['/etc/cx-node','/var/lib/cx-node','/usr/bin/cx-node','/usr/bin/cx-agent']:assert not os.path.lexists(name),name
    residual=run('python3','/tmp/classifier.py').strip()
    assert residual.startswith('cx-node=-,cx-agent=-,codex-mesh=-;')
    run(*apt,*guard(source,residual),'--reinstall','install','/packages/new.deb')
    run('python3','/tmp/classifier.py')
    for name,expected in before.items():assert fingerprint(name.replace('cx-node','cx-mesh'))==expected,name
    Path('/usr/bin/cx-node').symlink_to('/usr/bin/cx-mesh')
    denied=subprocess.run(['python3','/tmp/classifier.py'],capture_output=True,text=True)
    assert denied.returncode and 'retired CX path remains' in denied.stderr
    print(json.dumps({'scenario':scenario,'passed':True,'real_nonroot_uid_gid_preserved':True,'identity_credentials_state_preserved':True,'historical_dpkg_records_preserved':True,'production_agpc_guard_and_repeat_passed':True,'compatibility_alias_refused':True,'systemctl_mocked':True,'dependency_standins':True}))

if __name__=='__main__':main()
