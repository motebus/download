#!/usr/bin/env python3
"""Disposable native processes/sockets plus original multiservice file/Store code.

Synthetic route/configuration and PBX/media/provider admission remain explicit
fixtures. No claim about actual OpenSIPS, RTPengine, providers or phones follows
from this test. Actual target planning and phone verification are separate.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path('/var/lib/agpc-voice-multiservice-ci')


def require(ok,reason):
    if not ok:raise RuntimeError(reason)


def run(args):
    p=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    require(p.returncode==0,'Native fixture command failed: '+p.stderr.decode(errors='replace')[-2048:])
    return p.stdout


def wait(predicate):
    end=time.monotonic()+10
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.05)
    raise RuntimeError('Native fixture deadline')


def main():
    require(Path(__file__).resolve()==ROOT/'probe.py' and sys.argv[1:]==['--disposable'] and os.geteuid()==0 and sys.flags.isolated,
            'Explicit isolated root disposable fixture required')
    require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
            and os.environ.get('GITHUB_REPOSITORY')=='motebus/download' and os.environ.get('GITHUB_REF')=='refs/heads/main'
            and os.environ.get('GITHUB_WORKFLOW_REF')=='motebus/download/.github/workflows/verify-agpc-voice-multiservice.yml@refs/heads/main',
            'Reviewed GitHub hosted execution required')
    distro=platform.freedesktop_os_release()
    require(distro['ID']=='ubuntu' and distro['VERSION_ID'] in ('24.04','26.04')
            and platform.machine()=='x86_64' and Path('/run/systemd/system').is_dir(),'Native Ubuntu required')
    p=subprocess.run(['/usr/bin/systemd-detect-virt','--container'],capture_output=True,timeout=10)
    require(p.returncode==1 and p.stdout.strip()==b'none','Native non-container host required')
    manifest=json.loads((ROOT/'SOURCE.json').read_bytes())
    require(manifest['schema']=='agpc-voice.multiservice-native-inputs/v1','Exact multiservice source required')
    for row in manifest['files']:
        path=ROOT/row['path'];raw=path.read_bytes()
        require(path.is_file() and not path.is_symlink() and path.stat().st_uid==0
                and not path.stat().st_mode&0o022 and len(raw)==row['bytes']
                and hashlib.sha256(raw).hexdigest()==row['sha256'],'Original native source changed')
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
    from agpc_voice import dialplan_native_services as services,dialplan_native_maintenance as maintenance
    from agpc_voice import dialplan_native_transaction as tx,multiservice_operations as operations
    from agpc_voice import multiservice_native as observation,dialplan_native_receipt as receipt
    from test_multiservice_operations import Harness
    actual=dict(show=services.show,change=services.change,run=services._run,cgroup=services.cgroup_empty,
                call=maintenance.call,replace=tx.atomic_replace,parent=tx._trusted_parent,
                user=pwd.getpwnam,utility=observation.utility_fingerprint)
    account=pwd.getpwnam('agpc-voice');require(account.pw_uid>0,'Unprivileged fixture owner required')
    workspace=Path('/var/lib')/('agpc-voice-multiservice-probe-'+secrets.token_hex(8))
    workspace.mkdir(mode=0o755)
    cases=[]
    # Actual original transaction code, with six isolated native service sets.
    for active,lost in ((False,0),(True,0),(False,1),(False,2),(False,3),(False,4)):
        case=unittest.TestCase()
        with patch.object(tempfile,'tempdir',str(workspace)), Harness(case,active,retained_dots=32) as h:
            h.root.chmod(0o755)
            suffix=secrets.token_hex(8)
            mapping={name:'agpc-multi-ci-'+suffix+'-'+str(i)+'.service'
                     for i,name in enumerate(services.UNITS)}
            files=[];sockets={};observed=[]
            def bind(target,name,value):h.stack.enter_context(patch.object(target,name,value))
            bind(pwd,'getpwnam',actual['user'])
            bind(tx,'_trusted_parent',actual['parent'])
            bind(tx,'atomic_replace',lambda path,raw,digest,metadata,**kw:
                 actual['replace'](path,raw,digest,metadata,owner=0,allowed=h.allowed,**kw))
            for path in h.paths.values():os.chown(path,0,account.pw_gid)
            os.chown(h.db,account.pw_uid,account.pw_gid);h.utility=h.fingerprint()
            bind(observation,'UTILITY_DB',h.db);bind(observation,'utility_fingerprint',actual['utility'])
            server=h.root/'agent.py'
            server.write_text('''import hashlib,json,os,signal,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from agpc_voice.agent_maintenance import Maintenance
class Calls:
 current=None;maintenance=None
 def quiesce(self,token):
  if self.current is not None or self.maintenance not in (None,token):return False
  self.maintenance=token;return True
 def resume(self,token):
  if self.maintenance!=token:return False
  self.maintenance=None;return True
stop=False
def end(*args):
 global stop;stop=True
signal.signal(signal.SIGTERM,end)
config=Path(sys.argv[3]);gate=Path(sys.argv[4]);digest=hashlib.sha256(config.read_bytes()).hexdigest()
initial=None
if gate.exists():
 value=json.loads(gate.read_bytes());assert value['config_sha256']==digest;initial=value['token']
m=Maintenance(Path(sys.argv[2]),Calls(),invocation=os.environ['INVOCATION_ID'],config_sha256=digest,supported=True,initial_token=initial)
try:
 while not stop:m.tick();time.sleep(.01)
finally:m.close()
''');server.chmod(0o644)
            try:
                for logical,physical in mapping.items():
                    owner=next((k for k,v in observation.AGENTS.items() if v==logical),None)
                    if owner:
                        directory=h.root/('socket-'+owner);directory.mkdir(mode=0o700)
                        os.chown(directory,account.pw_uid,account.pw_gid);sockets[owner]=directory/'maintenance.sock'
                        service=('Type=simple\nUser=agpc-voice\nGroup=agpc-voice\nExecStart=/usr/bin/python3 -I -B '
                            +str(server)+' '+str(ROOT/'src')+' '+str(sockets[owner])+' '+h.paths[owner]+' '+h.gates[owner]+'\n')
                    else:service='Type=oneshot\nRemainAfterExit=yes\nExecStart=/usr/bin/true\n'
                    path=Path('/usr/lib/systemd/system')/physical
                    with path.open('x') as stream:stream.write('[Service]\n'+service+'[Install]\nWantedBy=multi-user.target\n')
                    path.chmod(0o644);files.append(path)
                run(['/usr/bin/systemctl','daemon-reload'])
                run(['/usr/bin/systemctl','enable',*mapping.values()])
                for logical,physical in mapping.items():
                    if logical not in observation.AGENTS.values() or active:
                        run(['/usr/bin/systemctl','start',physical])
                def native_run(args):return actual['run']([mapping.get(item,item) for item in args])
                def native_show(name):
                    # Preserve logical names at this fixture adapter boundary;
                    # actual systemd identities remain in the recorded mapping.
                    p=native_run(['show',name,'--property=Id,LoadState,ActiveState,SubState,MainPID,InvocationID,UnitFileState,ControlGroup'])
                    require(p.returncode==0,'Native service observation failed')
                    value=dict(row.split('=',1) for row in p.stdout.decode().splitlines())
                    require(value['Id']==mapping[name] and value['LoadState']=='loaded','Native unit identity differs')
                    observed.append(copy.deepcopy(value));return value
                def native_change(verb,name):
                    value=actual['change'](verb,name)
                    if name in observation.AGENTS.values() and verb in ('start','restart'):
                        owner=next(k for k,v in observation.AGENTS.items() if v==name)
                        wait(lambda:sockets[owner].exists())
                    h.units={n:native_show(n) for n in services.UNITS}
                    return value
                bind(services,'_run',native_run);bind(services,'show',native_show)
                bind(services,'change',native_change)
                bind(services,'cgroup_empty',lambda group,**kw:
                     actual['cgroup']('/system.slice/'+mapping.get(group.rsplit('/',1)[1],group.rsplit('/',1)[1]),**kw))
                bind(maintenance,'UNITS',{owner:(mapping[logical],sockets[owner]) for owner,logical in observation.AGENTS.items()})
                bind(maintenance,'call',actual['call'])
                bind(observation,'service_snapshot',lambda **kw:{n:native_show(n) for n in services.UNITS})
                original_observe=h.observe
                def native_observe(*args,**kw):
                    h.units={n:native_show(n) for n in services.UNITS}
                    value=original_observe(*args,**kw);value['utility']=actual['utility']();return value
                bind(observation,'observe',native_observe)
                h.units={n:native_show(n) for n in services.UNITS};h.original_units=copy.deepcopy(h.units)
                for owner in observation.AGENTS:
                    if active:wait(lambda owner=owner:sockets[owner].exists())
                worker=h.worker
                if lost:
                    worker.admit();worker.quiesce();worker.capture();worker.stop_owned();worker.install_dots()
                    replace=tx.atomic_replace;count=0
                    def interrupted(path,*args,**kw):
                        nonlocal count
                        value=replace(path,*args,**kw)
                        if path in h.paths.values():
                            count+=1
                            if count==lost:raise OSError('native fixture lost committed reply')
                        return value
                    failed=False
                    with patch.object(tx,'atomic_replace',interrupted):
                        try:worker.install_files()
                        except OSError:failed=True
                    require(failed,'Expected interruption did not occur')
                    worker=operations.Operations(h.stage,h.profile,worker.token,h.events.append)
                    worker.capture_data=receipt.read(h.stage,'capture.json')
                    worker.load_gates();worker.recover();worker.release()
                else:
                    result=tx.transaction_sequence(worker,h.events.append)
                    require(result['state']=='complete','Native-backed transaction did not complete')
                    for owner in observation.AGENTS:
                        worker._quiesce(owner,worker.capture_data['hashes'][owner+'-after.bin'])
                        worker.gates[owner]=tx.write_gate(owner,worker.token,worker.capture_data['hashes'][owner+'-after.bin'])
                    worker.recover();worker.release()
                h.units={n:native_show(n) for n in services.UNITS};h.assert_restored(case)
                require(not any(Path(path).exists() for path in h.gates.values()),'Owned maintenance gates remain')
                cases.append(dict(initial_agents_active=active,interrupted_after_file=lost,
                    files_restored=True,dots_restored=True,utility_ledger_unchanged=True,
                    retained_dot_count=len(h.initial["dots"]),
                    stored_forward_bytes=(h.stage/"dot-forward.json").stat().st_size,
                    stored_recovery_bytes=(h.stage/"dot-recovery.json").stat().st_size,
                    enabled_state_restored=True,maintenance_gates_released=True,
                    fixture_unit_map=mapping,final_units=h.units,native_service_observations=observed))
            finally:
                run(['/usr/bin/systemctl','stop',*mapping.values()])
                run(['/usr/bin/systemctl','disable',*mapping.values()])
                for path in files:path.unlink()
                run(['/usr/bin/systemctl','daemon-reload'])
        case.doCleanups()
    print(json.dumps(dict(schema='agpc-voice.multiservice-native-fixture/v1',source_commit=manifest['source_commit'],
        version=manifest['version'],script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        source_manifest_sha256=hashlib.sha256((ROOT/'SOURCE.json').read_bytes()).hexdigest(),
        github={k:os.environ.get(k) for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA')},
        os=distro,python=platform.python_version(),cases=cases,
        native_process_socket_file_recovery_passed=True,real_pbx_media_provider_admission=False,
        production_host_acceptance=False,telephone_acceptance=False),sort_keys=True))


if __name__=='__main__':main()
