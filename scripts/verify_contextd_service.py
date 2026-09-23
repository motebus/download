#!/usr/bin/env python3
"""Verify an installed contextd service on a disposable native Linux CI host.

Run after the CI fixture installs the reviewed package. This verifier changes no
service, user, policy, package or retained context state. The daemon's namespace
probes create and clean up their own temporary directories.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import uuid


def run(*args, input=None):
    return subprocess.run(args, input=input, capture_output=True, text=True,
                          check=True, timeout=30).stdout.strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    require(os.geteuid() == 0, 'Run this verifier as root inside the disposable native CI host.')
    service = pwd.getpwnam('contextd')
    caller = pwd.getpwnam('nobody')
    require(service.pw_uid not in (0, caller.pw_uid) and caller.pw_uid != 0,
            'Separate unprivileged service and caller UIDs are required.')
    require(run('dpkg-query', '-W', '-f=${Status}', 'contextd') == 'install ok installed',
            'contextd must already be installed by the CI fixture.')
    require(run('systemctl', 'is-active', 'contextd.service') == 'active',
            'The installed contextd unit failed its service-user namespace preflight.')
    require(run('systemctl', 'show', '--property=User', '--value', 'contextd.service') == 'contextd',
            'The installed service must run as the dedicated contextd account.')
    pid = int(run('systemctl', 'show', '--property=MainPID', '--value', 'contextd.service'))
    require(pid > 1, 'The installed service has no live main process.')
    proc = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    require(set(map(int, proc['Uid'].split())) == {service.pw_uid},
            'The real daemon process is not running entirely as the service UID.')
    require(proc['NoNewPrivs'].strip() == '1', 'The installed unit must enforce NoNewPrivileges.')
    for path, mode in [('/var/lib/contextd', 0o700), ('/run/contextd', 0o755)]:
        metadata = Path(path).lstat()
        require(stat.S_ISDIR(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == mode
                and metadata.st_uid == service.pw_uid, f'Unsafe installed directory: {path}')
    socket = '/run/contextd/contextd.sock'
    metadata = Path(socket).lstat()
    require(stat.S_ISSOCK(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o666
            and metadata.st_uid == service.pw_uid, 'Unexpected local UID-isolated socket permissions.')
    checked = json.loads(run('runuser', '-u', 'contextd', '--', '/usr/sbin/contextd', 'check',
                             '--config', '/etc/contextd/contextd.json'))
    require(checked.get('ok') is True and checked.get('native_isolation') is True,
            'Native isolation must work as the dedicated service account.')
    request_id = str(uuid.uuid4())
    request = {'schema': 'contextd.request/v1', 'request_id': request_id,
               'operation': 'context.status', 'task_id': '', 'context_ref': '',
               'expected_revision': 0, 'args': {}}
    response = json.loads(run('runuser', '-u', 'nobody', '--', '/usr/sbin/contextd', 'request',
                              '--socket', socket, input=json.dumps(request) + '\n'))
    require(response.get('schema') == 'contextd.response/v1' and response.get('request_id') == request_id
            and response.get('ok') is True, 'A separate unprivileged UID cannot reach the local service.')
    result = response.get('result', {})
    require(result.get('native_isolation') is True and result.get('authorization') == 'local-unix-uid'
            and result.get('cross_uid_handoff') is False,
            'The running service must perform real isolated work without enabling cross-UID handoff.')
    print(json.dumps({'schema': 'contextd.installed-service-check/v1', 'service_active': True,
                      'service_user_probe': 'passed', 'unprivileged_caller_status': 'passed',
                      'running_service_isolation': 'passed', 'host_policy_changed': False,
                      'retained_context_state_changed': False}, indent=2))


if __name__ == '__main__':
    main()
