#!/usr/bin/env python3
"""Export bounded process metadata for this disposable canonical-entry CI only.

Never clear a hold, retry a writer, read credentials, or grant admission. Source
bytes and diagnostic projections are retained separately; argv is not exported.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat

PACKET = Path('/var/lib/agpc-voice-native-ci')
RUNS = Path('/var/lib/agpc-voice-native-entry-runs')
PROCESSES = Path('/usr/local/lib/agpc-native/package-processes')
MODES = ('fresh', 'upgrade', 'upgrade-l1-isolation', 'upgrade-k1-office', 'upgrade-servicemap')
FIXED = {
    'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
    'GITHUB_REPOSITORY': 'motebus/download', 'GITHUB_REF': 'refs/heads/main',
    'GITHUB_WORKFLOW_REF': 'motebus/download/.github/workflows/verify-agpc-voice-native-entry.yml@refs/heads/main',
}
BINDING = ('source_commit', 'source_manifest_sha256', 'runtime_sha256', 'github',
           'execution_id', 'host', 'authorization_sha256')
FIELDS = {'schema', 'state', 'phase', 'reason', 'fault_classes', 'pid', 'supervisor',
          'child_domain', 'direct_exit_proof', 'quiescence_proof',
          'finalization_proof', 'returncode', 'tracked', 'test_binding'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def trusted(path, directory=False):
    for part in (path, *path.parents):
        info = part.lstat()
        require(info.st_uid == 0 and not info.st_mode & 0o022
                and not stat.S_ISLNK(info.st_mode), 'Unsafe diagnostic ancestry')
        if part != path or directory:
            require(stat.S_ISDIR(info.st_mode), 'Diagnostic ancestry is not a directory')
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and 0 < info.st_size <= 65536, 'Unbounded diagnostic file')
    return path


def read(path):
    trusted(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(65537)
        after = os.fstat(stream.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and len(raw) == after.st_size <= 65536, 'Diagnostic changed during read')
    return raw


def validate_binding(session, state, source_raw, mode, environment, host):
    require(mode in MODES and session.get('schema') == 'agpc.voice-native-entry-ci-session/v1',
            'Exact session and mode required')
    github = session.get('github', {})
    require(set(github) == set(FIXED) | {'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA'}
            and all(github.get(k) == v == environment.get(k) for k, v in FIXED.items())
            and all(isinstance(github.get(k), str) and re.fullmatch(r'[1-9][0-9]*', github[k])
                    and github[k] == environment.get(k) for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
            and isinstance(github.get('GITHUB_SHA'), str)
            and re.fullmatch(r'[0-9a-f]{40}', github['GITHUB_SHA'])
            and github['GITHUB_SHA'] == environment.get('GITHUB_SHA'), 'Different CI execution')
    execution = github['GITHUB_RUN_ID'] + '-' + github['GITHUB_RUN_ATTEMPT'] + '-' + mode
    require(session.get('mode') == mode and session.get('host') == host
            and state.get('execution_id') == execution and state.get('host') == host
            and state.get('github') == github, 'Different session owner')
    require(session.get('source_manifest_sha256') == hashlib.sha256(source_raw).hexdigest()
            and state.get('source_manifest_sha256') == session['source_manifest_sha256']
            and state.get('source_commit') == session.get('source_commit'),
            'Different source binding')
    require(all(k in state for k in BINDING)
            and isinstance(state['runtime_sha256'], dict) and len(state['runtime_sha256']) == 6,
            'Incomplete process binding')
    return execution, {k: state[k] for k in BINDING}


def project(raw, binding):
    record = json.loads(raw)
    require(isinstance(record, dict)
            and record.get('schema') == 'agpc.package-process-observation/v1'
            and record.get('test_binding') == binding, 'Foreign process observation')
    # argv/command/environment and arbitrary extra keys cannot enter the artifact.
    return {key: record[key] for key in sorted(FIELDS) if key in record}


def collect(packet, runs, processes, mode, environment, host):
    """Paths are injectable for offline tests only; CLI uses fixed constants."""
    session = json.loads(read(packet / 'CI-SESSION.json'))
    execution = environment['GITHUB_RUN_ID'] + '-' + environment['GITHUB_RUN_ATTEMPT'] + '-' + mode
    require(re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*-(?:fresh|upgrade|upgrade-l1-isolation|upgrade-k1-office|upgrade-servicemap)',
                         execution), 'Invalid execution path')
    root = trusted(runs / execution, directory=True)
    state = json.loads(read(root / 'admission-state.json'))
    validated, binding = validate_binding(session, state, read(packet / 'SOURCE.json'),
                                         mode, environment, host)
    require(validated == execution, 'Execution path mismatch')
    result = dict(schema='agpc.voice-native-process-diagnostics/v1', execution_id=execution,
                  binding=binding, observations=[], holds_cleared=False,
                  production_admission=False, telephone_acceptance=False)
    if processes.exists() or processes.is_symlink():
        trusted(processes, directory=True)
        candidates = sorted(processes.glob('operation-*.json'))
        require(len(candidates) <= 64, 'Too many process observations')
        for path in candidates:
            require(re.fullmatch(r'operation-[0-9a-f]{32}\.json', path.name),
                    'Unexpected diagnostic name')
            raw = read(path)
            result['observations'].append(dict(name=path.name, bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(), observation=project(raw, binding)))
    destination = root / 'package-process-diagnostics.json'
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=MODES, required=True)
    args = parser.parse_args()
    release = platform.freedesktop_os_release()
    require(os.geteuid() == 0 and release.get('ID') == 'ubuntu'
            and release.get('VERSION_ID') == '24.04' and platform.machine() == 'x86_64',
            'Root on disposable Noble amd64 required')
    result = collect(PACKET, RUNS, PROCESSES, args.mode, os.environ, platform.node())
    print(json.dumps(dict(exported=len(result['observations']), holds_cleared=False)))


if __name__ == '__main__':
    main()
