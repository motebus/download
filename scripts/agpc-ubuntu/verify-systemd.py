#!/usr/bin/python3
"""Remote CI: isolated cgroup-v2 manager startup and graceful stop, not stack health."""
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
    options = json.loads(Path(__file__).with_name('runtime-options.json').read_text())
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
        # A real transient unit proves service creation, identity drop and reaping.
        run('exec', container, 'systemd-run', '--wait', '--pipe', '--collect',
            '--uid=cx-mesh', '/usr/bin/id', '-un')
        failed = subprocess.run(['docker', 'exec', container, 'systemctl', '--failed', '--no-pager'],
                                capture_output=True, text=True, timeout=10).stdout
        run('stop', '--time', '20', container, timeout=30)
        stopped = json.loads(run('inspect', container))[0]['State']
        assert not stopped['Running'] and stopped['ExitCode'] == 0, stopped
        print(json.dumps({'systemd_manager': manager, 'graceful_stop': 'passed',
                          'private_cgroup_v2': True, 'privileged': False,
                          'runtime_ready': False, 'full_stack_health': 'not-verified',
                          'failed_units': failed}, indent=2))
    finally:
        print(run('logs', container)[-16000:])
        run('rm', '-f', container)


if __name__ == '__main__':
    main()
