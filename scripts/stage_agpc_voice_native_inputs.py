#!/usr/bin/env python3
"""Fetch exact main-CI inputs for disposable Voice package validation, without signing."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import zipfile

import publish_agpc_voice as voice

PREFIX = 'agpc-voice-native-ci/'
VOICE_COMMIT = '92a89e307762478de23b9559d3b755e9ee42b231'
VOICE_JOB = 65637
VOICE_REVIEW = 4
VOICE_FILENAME = 'agpc-voice_0.1.0~office117.20261015.2_all.deb'
VOICE_BYTES = 48834
VOICE_SHA256 = '4f3daddb1e6b1290fb2bbc411b75a3ff04f26ffc9eb9f097416db40220a20453'
FILES = {'SOURCE.json', 'scripts/verify_agpc_voice_native_ci.py'} | {
    'src/' + name + '.py' for name in (
        'native_voice', 'native_install', 'native_rpc', 'rdp_client',
        'browser_install', 'desktop_preferences')
} | {'packages/' + name for name in (
    'agpc-voice_0.1.0~office117.20261015.2_all.deb',
    'agpc-voice_0.1.0~candidate.6_all.deb',
    'agpc-freeswitch-core_1.11.3+agpc1_amd64.deb')}


def stage(inputs, output, get_json=voice.api_json, get_bytes=voice.api_bytes):
    require = voice.native.require
    require(isinstance(inputs, dict), 'Native inputs must be an object')
    require(inputs.get('schema') == 'agpc.voice-native-ci-public-inputs/v1', 'Invalid native inputs')
    commit = inputs.get('source_commit', '')
    require(isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{40}', commit), 'Exact source required')
    require(type(inputs.get('ci_job')) is int and inputs['ci_job'] > 0, 'Exact CI job required')
    require(type(inputs.get('archive_bytes')) is int and 0 < inputs['archive_bytes'] <= voice.LIMIT,
            'Invalid native archive size')
    require(isinstance(inputs.get('archive_sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', inputs['archive_sha256']), 'Archive hash required')
    voice.verify_job(1341, inputs['ci_job'], commit, get_json)
    voice.verify_job(1348, VOICE_JOB, VOICE_COMMIT, get_json)
    data = get_bytes(f"projects/1341/jobs/{inputs['ci_job']}/artifacts")
    require(len(data) == inputs['archive_bytes']
            and hashlib.sha256(data).hexdigest() == inputs['archive_sha256'], 'Native archive mismatch')
    extracted = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        total = 0
        for member in archive.infolist():
            require(member.filename.startswith(PREFIX) and not member.flag_bits & 1
                    and not stat.S_ISLNK(member.external_attr >> 16), 'Unsafe native artifact member')
            if member.is_dir():
                require(member.filename in (PREFIX, PREFIX + 'src/', PREFIX + 'scripts/', PREFIX + 'packages/'),
                        'Unexpected native artifact directory')
                continue
            rel = member.filename[len(PREFIX):]
            require(rel in FILES and rel not in extracted, 'Unexpected native artifact file')
            total += member.file_size
            require(0 < member.file_size <= voice.LIMIT and total <= voice.LIMIT, 'Native artifact exceeds limit')
            extracted[rel] = archive.read(member)
    require(set(extracted) == FILES, 'Native input files missing')
    source = voice.load_json(extracted['SOURCE.json'])
    require(source.get('schema') == 'agpc.voice-native-ci-source/v1'
            and source.get('installer_commit') == commit and source.get('production_gate') is False
            and source.get('voice_commit') == VOICE_COMMIT
            and type(source.get('voice_ci_job')) is int and source['voice_ci_job'] == VOICE_JOB
            and type(source.get('voice_review')) is int and source['voice_review'] == VOICE_REVIEW
            and all(source.get(key) is False for key in (
                'published', 'native_acceptance', 'normal_installer_transaction')),
            'Native input source binding mismatch')
    records = source.get('files', [])
    require(isinstance(records, list) and len(records) == len(FILES) - 1
            and all(isinstance(r, dict) and set(r) == {'path', 'bytes', 'sha256'}
                    and isinstance(r['path'], str) for r in records)
            and {r.get('path') for r in records} == FILES - {'SOURCE.json'}, 'Native source inventory mismatch')
    for record in records:
        raw = extracted[record['path']]
        require(type(record['bytes']) is int and record['bytes'] > 0
                and isinstance(record['sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
                and len(raw) == record['bytes'] and hashlib.sha256(raw).hexdigest() == record['sha256'],
                'Native source byte mismatch')
    original = get_bytes(f'projects/1348/jobs/{VOICE_JOB}/artifacts/components/agpc-voice/dist/' + VOICE_FILENAME)
    require(original == extracted['packages/' + VOICE_FILENAME] and len(original) == VOICE_BYTES
            and hashlib.sha256(original).hexdigest() == VOICE_SHA256,
            'Native Voice input differs from original component main CI')
    require(not output.exists(), 'Native output already exists')
    output.mkdir(parents=True)
    for name, raw in extracted.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    commit = stage(voice.load_json(args.inputs.read_bytes()), args.output)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('source_commit=' + commit + '\n')
    print(json.dumps(dict(installer_commit=commit, component_job=65637,
                         signed=False, published=False, native_acceptance=False)))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, zipfile.BadZipFile, urllib.error.URLError) as error:
        print('Native input staging failed: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
