#!/usr/bin/env python3
"""Exercise the original decoder worker after the fresh disposable CI lifecycle.

Only the release-admission predicate is replaced by the exact closed CI source,
completed lifecycle and installed-payload checks below. Production source gates
stay closed. This is worker evidence, not normal-entry or phone acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import stat
import subprocess
import sys
import time

PACKET=Path('/var/lib/agpc-voice-native-ci')
ROOT=Path('/var/lib/agpc-voice-dependencies')
SCRIPT=Path('/var/lib/agpc-voice-native-host-prep/decoder.py')
WORKFLOW='motebus/download/.github/workflows/verify-agpc-voice-native-entry.yml@refs/heads/main'


def require(value, reason):
    if not value: raise RuntimeError(reason)


def trusted(path, directory=False):
    for p in (path,*path.parents):
        s=p.lstat()
        require(s.st_uid==0 and not s.st_mode&0o022 and not stat.S_ISLNK(s.st_mode), 'Untrusted decoder fixture')
        require(stat.S_ISDIR(s.st_mode) if p!=path or directory else
                stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=32*1024*1024,
                'Invalid decoder fixture object')
    return path


def read(path): return json.loads(trusted(path).read_bytes())


def source(context):
    require(os.geteuid()==0 and sys.flags.isolated and platform.machine()=='x86_64', 'Native root isolated Python required')
    require(platform.freedesktop_os_release().get('VERSION_ID') in ('24.04','26.04') and
            platform.freedesktop_os_release().get('ID')=='ubuntu', 'Ubuntu24 or Ubuntu26 required')
    require(context.get('GITHUB_ACTIONS')=='true' and context.get('RUNNER_ENVIRONMENT')=='github-hosted'
            and context.get('GITHUB_REPOSITORY')=='motebus/download' and context.get('GITHUB_REF')=='refs/heads/main'
            and context.get('GITHUB_WORKFLOW_REF')==WORKFLOW and
            re.fullmatch('[0-9a-f]{40}',context.get('GITHUB_SHA','')) and all(
                re.fullmatch('[1-9][0-9]*',context.get(k,'')) for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')),
            'Reviewed disposable workflow required')
    p=subprocess.run(['/usr/bin/systemd-detect-virt','--container'],capture_output=True,timeout=10)
    require(p.returncode==1 and p.stdout.strip()==b'none' and Path('/run/systemd/system').is_dir(), 'Native systemd required')
    manifest=read(PACKET/'SOURCE.json')
    require(manifest['schema']=='agpc.voice-native-entry-ci-source/v1' and manifest['production_gate'] is False,
            'Exact closed source required')
    names=set()
    for row in manifest['files']:
        name=row['path']
        require(name not in names and re.fullmatch(r'[A-Za-z0-9_.+~/\-]+',name)
                and not name.startswith('/') and '..' not in Path(name).parts, 'Invalid source member')
        raw=trusted(PACKET/name).read_bytes();names.add(name)
        require(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'], 'Source bytes changed')
    result_path=Path('/var/lib/agpc-voice-native-entry-runs')/(context['GITHUB_RUN_ID']+'-'+context['GITHUB_RUN_ATTEMPT']+'-fresh')/'result.json'
    result=read(result_path)
    require(result['state']=='passed' and result['mode']=='fresh' and result['fresh_install_left_inactive'] is True
            and result['canonical_entry_ci_lifecycle_passed'] is True and result['installer_commit']==manifest['installer_commit']
            and result['ci']['GITHUB_SHA']==context['GITHUB_SHA'] and result['ci']['GITHUB_RUN_ID']==context['GITHUB_RUN_ID'],
            'Successful current fresh lifecycle required')
    for n in ('src/native_voice.py','src/native_voice_dialplan.py','src/native_install.py'):
        require(n in names,'Required source missing')
    sys.path.insert(0,str(PACKET/'src'))
    import native_voice as voice
    import native_voice_dialplan as decoder
    require(not voice.INSTALL_CONTRACT_ADMITTED and not decoder.DIALPLAN_CONTRACT_ADMITTED,
            'Fixture cannot admit production gates')
    def checked_release(_source=None):
        voice.require_ci_target()
        paths=[PACKET/'packages'/voice.filename(p) for p in voice.RELEASES[voice.RELEASE]]
        for artifact,path in zip(voice.RELEASES[voice.RELEASE],paths): voice.validate_artifact(path,artifact)
        voice.verify_installed(voice.RELEASE,paths)
        return voice.RELEASE
    # Explicit fixture admission; worker/transactions/receipt implementations stay original.
    decoder.verify_release=checked_release
    checked_release()
    return decoder,manifest,result_path


def wait(decoder, unit):
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        state=decoder.manager(unit)
        if state['LoadState']=='loaded' and state['ActiveState'] in ('active','failed') and state['Job']=='': return state
        time.sleep(.5)
    raise RuntimeError('Decoder native observation deadline')


def fixture(decoder, context, *, cast_audio=False):
    decoder.core.secure_directory(ROOT)
    stage=ROOT/('agpc-voice-dependencies-'+secrets.token_hex(16));stage.mkdir(mode=0o700)
    decoder.publish(stage,'fixture-context.json',context)
    decoder.publish(stage,'request.json',dict(schema=decoder.SCHEMA,release=decoder.verify_release(),transaction=stage.name,cast_audio=cast_audio))
    base='/usr/bin/python3 -I -B '+str(SCRIPT)+' worker '
    unit=stage.name+'.service'
    decoder.core.run(['/usr/bin/systemd-run','--quiet','--no-block','--unit='+unit,
        '--property=Type=oneshot','--property=RemainAfterExit=yes','--property=Restart=no','--property=UMask=0077',
        '--property=TimeoutStartSec=600','--property=TimeoutStopSec=90','--property=KillMode=control-group',
        '--property=StandardOutput=append:'+str(stage/'native.log'),
        '--property=StandardError=append:'+str(stage/'native.log'),
        '--property=ExecStartPre='+base+'start '+str(stage),
        '--property=ExecStartPost='+base+'success '+str(stage),
        '--property=ExecStopPost='+base+'stop '+str(stage),
        '/usr/bin/python3','-I','-B',str(SCRIPT),'worker','worker',str(stage)])
    state=wait(decoder,unit)
    if not (state['ActiveState']=='active' and state['SubState']=='exited' and state['ExecMainCode']=='1'
            and state['ExecMainStatus']=='0' and state['Result']=='success'):
        # Only this disposable fixture's fixed root-owned log is reported.
        # The worker receives GitHub execution metadata, no source-read token.
        log=trusted(stage/'native.log').read_bytes()
        print(json.dumps(dict(schema='agpc-voice.decoder-native-failure/v1',
            manager=state,transaction=stage.name,log=log[-65536:].decode(errors='replace'))),file=sys.stderr)
    require(state['ActiveState']=='active' and state['SubState']=='exited' and state['ExecMainCode']=='1'
            and state['ExecMainStatus']=='0' and state['Result']=='success','Decoder worker failed: '+str(stage))
    final=decoder.dependency_status(stage.name)
    require(final['state']=='verified_complete','Decoder completion receipt failed')
    decoder.core.run(['/usr/bin/systemctl','stop',unit])
    records={n:read(stage/n) for n in ('invocation.json','worker.json','main-success.json','stopped.json')}
    require(records['stopped.json']['service_result']=='success' and records['stopped.json']['exit_status']=='0',
            'Decoder stop receipt failed')
    if (stage/'apt-plan.json').exists(): records['apt-plan.json']=read(stage/'apt-plan.json')
    return dict(manager=state,completion=final,records=records)


def main():
    require(Path(__file__).resolve()==SCRIPT,'Fixed root-owned fixture script required');trusted(SCRIPT)
    if len(sys.argv)==4 and sys.argv[1]=='worker':
        stage=Path(sys.argv[3]);require(stage.parent==ROOT and re.fullmatch('agpc-voice-dependencies-[0-9a-f]{32}',stage.name),'Invalid fixture stage')
        decoder,_,_=source(read(stage/'fixture-context.json'))
        decoder.worker(sys.argv[2],stage);return
    require(sys.argv[1:]==['--disposable-fresh'],'Explicit fresh fixture required')
    keys=('GITHUB_ACTIONS','RUNNER_ENVIRONMENT','GITHUB_REPOSITORY','GITHUB_REF','GITHUB_WORKFLOW_REF','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')
    context={k:os.environ.get(k,'') for k in keys};decoder,manifest,previous=source(context)
    require(not decoder.decoder_present() and not decoder.cast_audio_present(),
            'Fixture requires absent FFmpeg and Pulse tools; prepare disposable baseline first')
    before=set((decoder.core.ROOT/'package-processes').glob('operation-*.json'))
    first=fixture(decoder,context);repeat=fixture(decoder,context)
    cast_install=fixture(decoder,context,cast_audio=True);cast_repeat=fixture(decoder,context,cast_audio=True)
    after=set((decoder.core.ROOT/'package-processes').glob('operation-*.json'))
    processes=[read(p) for p in sorted(after-before)]
    require(len(processes)==4 and all(decoder.core.finished_process_observation(p) and p['returncode']==0 for p in processes),
            'Actual decoder download and install completion required')
    require(first['records']['worker.json']['state']=='installed' and repeat['records']['worker.json']['state']=='verified_noop',
            'Install and repeat paths required')
    require(cast_install['records']['worker.json']['state']=='installed'
            and cast_repeat['records']['worker.json']['state']=='verified_noop'
            and 'pulseaudio-utils' in cast_install['completion']['installed']
            and 'ffmpeg' not in cast_install['completion']['installed'],'Explicit missing-only Cast tools required')
    print(json.dumps(dict(schema='agpc-voice.decoder-native-fixture/v1',github=context,source_commit=manifest['installer_commit'],
        source_manifest_sha256=hashlib.sha256(trusted(PACKET/'SOURCE.json').read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(trusted(SCRIPT).read_bytes()).hexdigest(),
        lifecycle_result_sha256=hashlib.sha256(trusted(previous).read_bytes()).hexdigest(),
        install=first,repeat=repeat,cast_install=cast_install,cast_repeat=cast_repeat,
        native_cast_dependencies_passed=True,package_process_observations=processes,native_decoder_worker_passed=True,normal_entry_acceptance=False,telephone_acceptance=False),sort_keys=True))


if __name__=='__main__': main()
