#!/usr/bin/env python3
"""Write one root-private session in the reviewed disposable entry CI workflow.

Environment values bind the execution; they are not independent host authority.
The CLI has no target override, package writer or production admission option.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import time

PACKET = Path('/var/lib/agpc-voice-native-ci')
MODES = ('fresh', 'upgrade', 'upgrade-l1-isolation')
FIXED = {
    'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
    'GITHUB_REPOSITORY': 'motebus/download', 'GITHUB_REF': 'refs/heads/main',
    'GITHUB_WORKFLOW_REF': 'motebus/download/.github/workflows/verify-agpc-voice-native-entry.yml@refs/heads/main',
}
KEYS = set(FIXED) | {'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA'}
FILES = {'agpc-voice.sh', 'scripts/verify_agpc_voice_native_ci.py',
         'scripts/verify_agpc_voice_native_entry_ci.py'} | {
    'src/' + name + '.py' for name in ('native_voice', 'native_install', 'native_rpc',
                                     'rdp_client', 'browser_install', 'desktop_preferences')
} | {'packages/' + name for name in ('agpc-voice_0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1+callback999.1_all.deb',
    'agpc-voice_0.1.0~office117.20261015.2+l1isolation.2_all.deb',
    'agpc-voice_0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1_all.deb', 'agpc-freeswitch-core_1.11.3+agpc1_amd64.deb')}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def trusted(path, *, directory=False):
    for item in (path, *path.parents):
        info = item.lstat()
        require(info.st_uid == 0 and not info.st_mode & 0o022 and not stat.S_ISLNK(info.st_mode),
                'Untrusted root-owned session input')
        if item != path or directory:
            require(stat.S_ISDIR(info.st_mode), 'Session input ancestry is not a directory')
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and 0 < info.st_size <= 64 * 1024 * 1024, 'Session input is not a bounded regular file')
    return path


def prepare(packet, mode, commit, manifest_sha256, environment):
    """Internal path injection is for offline tests; main always uses PACKET."""
    require(os.geteuid() == 0, 'Root execution required')
    require(mode in MODES and isinstance(commit, str)
            and re.fullmatch(r'[0-9a-f]{40}', commit) and isinstance(manifest_sha256, str)
            and re.fullmatch(r'[0-9a-f]{64}', manifest_sha256), 'Exact mode/source/manifest required')
    github = {key: environment.get(key) for key in KEYS}
    require(all(github[k] == v for k, v in FIXED.items()) and all(
        isinstance(github[k], str) and re.fullmatch(r'[1-9][0-9]*', github[k])
        for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')) and isinstance(github['GITHUB_SHA'], str)
        and re.fullmatch(r'[0-9a-f]{40}', github['GITHUB_SHA']), 'Exact entry workflow context required')
    trusted(packet, directory=True)
    raw = trusted(packet / 'SOURCE.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == manifest_sha256, 'Root-staged source manifest differs')
    source = json.loads(raw)
    require(isinstance(source, dict) and source.get('schema') == 'agpc.voice-native-entry-ci-source/v1'
            and source.get('installer_commit') == commit and all(source.get(k) is False for k in (
                'production_gate', 'published', 'native_acceptance', 'normal_installer_transaction',
                'production_admission', 'historical_L1_admission', 'secrets_included', 'host_mutated')),
            'Closed source manifest required')
    records = source.get('files')
    require(isinstance(records, list) and len(records) == 13 and all(
        isinstance(r, dict) and set(r) == {'path', 'bytes', 'sha256'} and isinstance(r['path'], str)
        for r in records) and {r['path'] for r in records} == FILES, 'Exact session bundle required')
    for record in records:
        data = trusted(packet / record['path']).read_bytes()
        require(type(record['bytes']) is int and record['bytes'] == len(data)
                and record['sha256'] == hashlib.sha256(data).hexdigest(), 'Root-staged bundle differs')
    actual = set()
    for path in packet.rglob('*'):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            trusted(path, directory=True)
        else:
            trusted(path)
            actual.add(path.relative_to(packet).as_posix())
    require(actual == FILES | {'SOURCE.json'}, 'Unexpected file or existing CI session')
    now = int(time.time())
    record = dict(schema='agpc.voice-native-entry-ci-session/v1',
        scope='inactive-canonical-entry-lifecycle', mode=mode, github=github,
        host=platform.node(), source_commit=commit, source_manifest_sha256=manifest_sha256,
        not_before=now, expires_at=now + 1800)
    destination = packet / 'CI-SESSION.json'
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    args = parser.parse_args()
    release = platform.freedesktop_os_release()
    require(release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04'
            and platform.machine() == 'x86_64', 'Disposable Noble amd64 required')
    prepare(PACKET, args.mode, args.source_commit, args.source_manifest_sha256, os.environ)
    print(json.dumps(dict(ci_session_created=True, production_admission=False, historical_L1_admission=False)))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError) as error:
        raise SystemExit('Native entry session refused: ' + type(error).__name__) from None
