#!/usr/bin/python3
"""Remote CI: isolated cgroup-v2 manager startup and graceful stop, not stack health."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def run(*args, **kwargs):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f'docker {args}: {result.stdout} {result.stderr}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apparmor-profile', choices=['agpc-systemd'])
    parser.add_argument('--diagnose-without-apparmor', action='store_true',
                        help='CI isolation experiment only; never runtime admission')
    args = parser.parse_args()
    options = json.loads(Path(__file__).with_name('runtime-options.json').read_text())
    if args.apparmor_profile and args.diagnose_without_apparmor:
        parser.error('profile verification cannot disable AppArmor')
    if args.apparmor_profile:
        options['docker_run_args'] += ['--security-opt', 'apparmor=' + args.apparmor_profile]
    if args.diagnose_without_apparmor:
        options['docker_run_args'] += ['--security-opt', 'apparmor=unconfined']
    info = json.loads(run('info', '--format', '{{json .}}'))
    assert info['CgroupVersion'] == options['required_cgroup_version'], 'cgroup v2 is required'
    assert int(info['ServerVersion'].split('.')[0]) >= options['minimum_engine_major']
    # No network or published ports: this test must not join the live Mote mesh.
    container = run('run', '-d', '-t', '--network', 'none',
                    '--env', 'SYSTEMD_LOG_TARGET=console', '--env', 'SYSTEMD_LOG_LEVEL=debug',
                    *options['docker_run_args'], 'agpc-ubuntu26:candidate').strip()
    try:
        manager = ''
        for _ in range(60):
            state = json.loads(run('inspect', container))[0]
            if not state['State']['Running']:
                raise RuntimeError('systemd exited before its manager became ready')
            check = subprocess.run(['docker', 'exec', container, 'systemctl', 'show', '--property=Version'],
                                   capture_output=True, text=True, timeout=5)
            if check.returncode == 0 and check.stdout.startswith('Version='):
                manager = check.stdout.strip()
                break
            time.sleep(.5)
        assert manager, 'systemd manager did not become ready'
        config = state['HostConfig']
        assert config['Privileged'] is False
        assert config['CapAdd'] == ['SYS_ADMIN'] or config['CapAdd'] == ['CAP_SYS_ADMIN']
        assert not config['Binds'] and not config['PortBindings']
        assert config['CgroupnsMode'] == 'private'
        assert run('exec', container, 'cat', '/proc/1/cgroup').strip() == '0::/init.scope'
        assert 'writable-cgroups=true' in config['SecurityOpt']
        if args.apparmor_profile:
            assert state['AppArmorProfile'] == args.apparmor_profile
            run('exec', container, 'mkdir', '-p', '/mnt/forbidden')
            # Call mount directly: util-linux retries read-only and changes its error text.
            run('exec', container, 'python3', '-c',
                "import ctypes, errno; c=ctypes.CDLL(None,use_errno=True); "
                "r=c.mount(b'tmpfs',b'/mnt/forbidden',b'tmpfs',0,None); "
                "assert r == -1 and ctypes.get_errno() in (errno.EPERM,errno.EACCES)")
        # The manager's private socket precedes the system bus during boot.
        run('exec', container, 'systemctl', 'start', 'dbus.service', timeout=30)
        # A real transient unit proves service creation, identity drop and reaping.
        run('exec', container, 'systemd-run', '--wait', '--pipe', '--collect',
            '--uid=cx-mesh', '--property=PrivateTmp=true',
            '--property=ProtectSystem=strict', '--property=ProtectHome=true',
            '--property=ProtectControlGroups=true', '--property=NoNewPrivileges=true',
            '/usr/bin/python3', '-c',
            "import os, pathlib; assert os.getuid() != 0; "
            "assert os.statvfs('/usr').f_flag & os.ST_RDONLY; "
            "pathlib.Path('/tmp/agpc-unit-check').write_text('private tmp'); "
            "assert 'NoNewPrivs:\t1' in pathlib.Path('/proc/self/status').read_text()")
        failed = subprocess.run(['docker', 'exec', container, 'systemctl', '--failed', '--no-pager'],
                                capture_output=True, text=True, timeout=10).stdout
        run('stop', '--time', '20', container, timeout=30)
        stopped = json.loads(run('inspect', container))[0]['State']
        assert not stopped['Running'] and stopped['ExitCode'] == 0, stopped
        print(json.dumps({'systemd_manager': manager, 'graceful_stop': 'passed',
                          'private_cgroup_v2': True, 'apparmor_profile': args.apparmor_profile, 'privileged': False,
                          'runtime_ready': False, 'apparmor_diagnostic': args.diagnose_without_apparmor,
                          'full_stack_health': 'not-verified',
                          'failed_units': failed}, indent=2))
    finally:
        print(run('logs', container)[-16000:])
        run('rm', '-f', container)


if __name__ == '__main__':
    main()
