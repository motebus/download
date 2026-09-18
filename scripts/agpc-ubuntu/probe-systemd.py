#!/usr/bin/python3
"""CI diagnostic, not admission: probe default Docker without host mounts/capabilities."""
import json
import subprocess
import time

container = subprocess.check_output([
    'docker', 'run', '-d', '--network', 'none', '--cgroupns', 'private',
    '--tmpfs', '/run', '--tmpfs', '/run/lock', '--tmpfs', '/tmp',
    'agpc-ubuntu26:candidate'], text=True).strip()
try:
    ready = False
    state = {}
    for _ in range(20):
        state = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]['State']
        if not state['Running']:
            break
        check = subprocess.run(['docker', 'exec', container, 'systemctl', 'show', '--property=Version'],
                               capture_output=True, text=True, timeout=5)
        if check.returncode == 0 and check.stdout.startswith('Version='):
            ready = True
            break
        time.sleep(.5)
    logs = subprocess.run(['docker', 'logs', container], capture_output=True, text=True)
    record = {'diagnostic_only': True, 'systemd_manager_responds': ready,
              'runtime_ready': False, 'docker_privileged': False, 'extra_capabilities': [],
              'host_mounts': [], 'network': 'none', 'state': state,
              'logs': (logs.stdout + logs.stderr)[-12000:]}
    print(json.dumps(record, indent=2))
finally:
    subprocess.run(['docker', 'rm', '-f', container], check=True, stdout=subprocess.DEVNULL)
