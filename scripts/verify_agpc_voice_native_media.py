#!/usr/bin/env python3
"""Run source-owned fixture suites using the actual Noble CI decoder."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys


def digest(path):
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Untrusted native decoder file')
    return dict(path=str(path), bytes=info.st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main(root, output):
    system = platform.freedesktop_os_release()
    if (system.get('ID') != 'ubuntu' or system.get('VERSION_ID') != '24.04'
            or platform.machine() != 'x86_64' or os.geteuid() == 0
            or os.environ.get('GITHUB_REPOSITORY') != 'motebus/download'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise RuntimeError('Actual unprivileged Noble hosted main CI required')
    source = json.loads((root/'SOURCE.json').read_bytes())
    for row in source['files']:
        raw = (root/row['path']).read_bytes()
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise RuntimeError('Staged source changed')
    binary = Path('/usr/bin/ffmpeg')
    loaded = subprocess.check_output(['/usr/bin/ldd', str(binary)], text=True, timeout=20)
    if 'not found' in loaded:
        raise RuntimeError('Decoder dependency missing')
    paths = {binary.resolve(), *[Path(p).resolve() for p in re.findall(r'(/[^\s()]+)', loaded)]}
    before = [digest(p) for p in sorted(paths)]
    output.mkdir(parents=True, exist_ok=False)
    descriptor = dict(command=[str(binary)], ffmpeg_sha256=digest(binary)['sha256'], dependencies=before)
    (output/'decoder.json').write_text(json.dumps(descriptor, indent=2)+'\n')
    packages = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\n'], text=True, timeout=20)
    (output/'runner-packages.tsv').write_text(packages)
    record = dict(schema='agpc-voice.native-media-ci/v1', os=system,
                  python=platform.python_version(), source_commit=source['source_commit'],
                  source_manifest_sha256=hashlib.sha256((root/'SOURCE.json').read_bytes()).hexdigest(),
                  github={k:os.environ[k] for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_REF')},
                  decoder=descriptor, suites=[], dependencies_unchanged=False,
                  native_media_passed=False, telephone_acceptance=False, L1_acceptance=False)
    env = dict(os.environ, PYTHONPATH=str(root/'src'), PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               RADIO_TEST_DESCRIPTOR=str(output/'decoder.json'), MEDIA_TEST_RECEIPTS=str(output/'overall.json'),
               RADIO_TEST_RECEIPTS=str(output/'legacy.json'))
    try:
        for suite in ('test_overall_media_native.py', 'test_radio_native.py'):
            with (output/(suite+'.log')).open('w') as log:
                result = subprocess.run(['/usr/bin/python3', '-B', '-m', 'unittest', 'discover', '-s',
                    str(root/'tests'), '-p', suite, '-v'], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            record['suites'].append(dict(name=suite, exit=result.returncode))
            if result.returncode:
                raise RuntimeError('Native media suite failed: '+suite)
        record['dependencies_unchanged'] = before == [digest(p) for p in sorted(paths)]
        if not record['dependencies_unchanged']:
            raise RuntimeError('Native decoder changed during verification')
        record['native_media_passed'] = True
    finally:
        (output/'RESULT.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();main(args.root.absolute(),args.output.absolute())
