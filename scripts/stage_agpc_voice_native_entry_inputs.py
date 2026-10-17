#!/usr/bin/env python3
"""Verify reviewed closed-gate entry CI inputs without importing their code."""
import argparse
import ast
import base64
import gzip
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

PREFIX = 'agpc-voice-native-entry-ci/'
VOICE_COMMIT = '1acb212b6c7d34be994b7f67c23821c0430fcd59'
VOICE_JOB, VOICE_PIPELINE, VOICE_REVIEW = 65812, 28133, 11
VOICE_FILENAME = 'agpc-voice_0.1.0~office117.20261015.2+l1isolation.2_all.deb'
VOICE_BYTES = 266432
PACKAGE_SHA256 = {
    VOICE_FILENAME: '89005f0c53235e7f72370a624a397d4ef4221a52d1a36d23fcb6b129f4c8d15a',
    'agpc-voice_0.1.0~office117.20261015.2_all.deb': '4f3daddb1e6b1290fb2bbc411b75a3ff04f26ffc9eb9f097416db40220a20453',
    'agpc-freeswitch-core_1.11.3+agpc1_amd64.deb': 'a207b111702e7ae7c8682cffa7468a450b66b4acb69203a8f545edcff25a25e4',
}
RUNTIME_NAMES = {'native_voice', 'native_install', 'native_rpc', 'rdp_client',
                 'browser_install', 'desktop_preferences'}
FILES = {'SOURCE.json', 'agpc-voice.sh', 'scripts/verify_agpc_voice_native_ci.py',
         'scripts/verify_agpc_voice_native_entry_ci.py'} | {
             'src/' + name + '.py' for name in RUNTIME_NAMES
         } | {'packages/' + name for name in PACKAGE_SHA256}
FALSE_FLAGS = {'production_gate', 'published', 'native_acceptance',
               'normal_installer_transaction', 'production_admission',
               'historical_L1_admission', 'secrets_included', 'host_mutated'}
require = voice.native.require


def verify_embedded(extracted):
    """Decode only the bounded literal payload; never evaluate staged source."""
    marker = 'AGPC_VOICE_PACKAGED_RUNTIME'
    text = extracted['agpc-voice.sh'].decode()
    require(text.count(marker) == 2, 'Standalone entry runtime required')
    body = text.split(marker, 1)[1].split('\n', 1)[1].rsplit(marker, 1)[0]
    tree = ast.parse(body)
    payloads = [n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'payload' for t in n.targets)]
    require(len(payloads) == 1, 'One literal runtime payload required')
    call = payloads[0]
    require(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == 'base64'
            and call.func.attr == 'b64decode' and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str),
            'Literal runtime payload required')
    compressed = base64.b64decode(call.args[0].value, validate=True)
    require(len(compressed) <= 1024 * 1024, 'Runtime payload exceeds limit')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        decoded = stream.read(1024 * 1024 + 1)
    require(len(decoded) <= 1024 * 1024, 'Runtime expansion exceeds limit')
    sources = voice.load_json(decoded)
    require(set(sources) == RUNTIME_NAMES and all(isinstance(text, str) and
            text.encode() == extracted['src/' + name + '.py'] for name, text in sources.items()),
            'Embedded and staged runtime differ')
    tree = ast.parse(sources['native_voice'])
    declarations = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('INSTALL_CONTRACT_ADMITTED', 'RELEASE'):
                    require(target.id not in declarations and isinstance(node.value, ast.Constant),
                            'One literal release gate required')
                    declarations[target.id] = node.value.value
    require(declarations.get('INSTALL_CONTRACT_ADMITTED') is False
            and declarations.get('RELEASE') == 'office117.20261015.2+l1isolation.2', 'Exact closed source gate required')


def validate_manifest(extracted, commit):
    source = voice.load_json(extracted['SOURCE.json'])
    require(set(source) == {'schema', 'installer_commit', 'voice_commit', 'voice_ci_pipeline',
                            'voice_ci_job', 'voice_review', 'files'} | FALSE_FLAGS
            and source['schema'] == 'agpc.voice-native-entry-ci-source/v1'
            and source['installer_commit'] == commit and source['voice_commit'] == VOICE_COMMIT
            and all(type(source[k]) is int and source[k] == v for k, v in (
                ('voice_ci_pipeline', VOICE_PIPELINE), ('voice_ci_job', VOICE_JOB), ('voice_review', VOICE_REVIEW)))
            and all(source[key] is False for key in FALSE_FLAGS), 'Native entry source binding mismatch')
    records = source['files']
    require(isinstance(records, list) and len(records) == 12
            and all(isinstance(r, dict) and set(r) == {'path', 'bytes', 'sha256'}
                    and isinstance(r['path'], str) for r in records)
            and {r['path'] for r in records} == FILES - {'SOURCE.json'}, 'Exact twelve-file inventory required')
    for record in records:
        raw = extracted[record['path']]
        require(type(record['bytes']) is int and record['bytes'] > 0
                and isinstance(record['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
                and len(raw) == record['bytes'] and hashlib.sha256(raw).hexdigest() == record['sha256'],
                'Native source byte mismatch')
    for filename, expected in PACKAGE_SHA256.items():
        require(hashlib.sha256(extracted['packages/' + filename]).hexdigest() == expected,
                'Exact native package pin required')
    require(len(extracted['packages/' + VOICE_FILENAME]) == VOICE_BYTES, 'Selected Voice size mismatch')
    verify_embedded(extracted)
    return source


def stage(inputs, output, get_json=voice.api_json, get_bytes=voice.api_bytes):
    require(isinstance(inputs, dict) and set(inputs) == {
        'schema', 'source_commit', 'ci_job', 'install_review', 'archive_bytes', 'archive_sha256'},
        'Exact native entry public inputs required')
    require(inputs['schema'] == 'agpc.voice-native-entry-ci-public-inputs/v1', 'Invalid native entry inputs')
    commit = inputs['source_commit']
    require(isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{40}', commit), 'Exact source required')
    require(all(type(inputs[k]) is int and inputs[k] > 0 for k in ('ci_job', 'install_review')),
            'Exact CI and review identities required')
    require(type(inputs['archive_bytes']) is int and 0 < inputs['archive_bytes'] <= voice.LIMIT
            and isinstance(inputs['archive_sha256'], str)
            and re.fullmatch(r'[0-9a-f]{64}', inputs['archive_sha256']), 'Exact bounded archive pin required')
    observations = {}
    def observed_json(endpoint):
        value = get_json(endpoint)
        observations[endpoint] = value
        return value
    voice.verify_job(1341, inputs['ci_job'], commit, observed_json)
    require(observations[f"projects/1341/jobs/{inputs['ci_job']}"]['name'] ==
            'agpc-voice-native-entry-ci-inputs', 'Exact native entry producer job required')
    voice.verify_review(inputs['install_review'], 1341, commit, observed_json)
    voice.verify_job(1348, VOICE_JOB, VOICE_COMMIT, observed_json)
    require(observations[f'projects/1348/jobs/{VOICE_JOB}']['pipeline']['id'] == VOICE_PIPELINE,
            'Exact reviewed component pipeline required')
    voice.verify_review(VOICE_REVIEW, 1348, VOICE_COMMIT, observed_json)
    data = get_bytes(f"projects/1341/jobs/{inputs['ci_job']}/artifacts")
    require(len(data) == inputs['archive_bytes'] and hashlib.sha256(data).hexdigest() == inputs['archive_sha256'],
            'Native entry archive mismatch')
    extracted, total, seen = {}, 0, set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            name, mode = member.filename, member.external_attr >> 16
            require(name.startswith(PREFIX) and name not in seen and not member.flag_bits & 1
                    and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'Unsafe native artifact member')
            seen.add(name)
            if member.is_dir():
                require(name in (PREFIX, PREFIX + 'src/', PREFIX + 'scripts/', PREFIX + 'packages/'),
                        'Unexpected native artifact directory')
                continue
            relative = name[len(PREFIX):]
            require(relative in FILES and relative not in extracted, 'Unexpected native artifact file')
            total += member.file_size
            require(0 < member.file_size <= voice.LIMIT and total <= voice.LIMIT, 'Native artifact exceeds limit')
            extracted[relative] = archive.read(member)
    require(set(extracted) == FILES, 'Native entry input files missing')
    validate_manifest(extracted, commit)
    original = get_bytes(f'projects/1348/jobs/{VOICE_JOB}/artifacts/components/agpc-voice/dist/' + VOICE_FILENAME)
    require(original == extracted['packages/' + VOICE_FILENAME],
            'Native Voice differs from original reviewed component main CI')
    require(not output.exists() and not output.is_symlink(), 'Native output already exists')
    require(not any(p.is_symlink() for p in output.parents), 'Unsafe native output ancestry')
    output.mkdir(parents=True)
    for name, raw in extracted.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o755 if name == 'agpc-voice.sh' else 0o644)
    # Bind the root session to verified archive bytes, never to a later read
    # from the unprivileged staging directory.
    return commit, hashlib.sha256(extracted['SOURCE.json']).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    commit, manifest_sha256 = stage(voice.load_json(args.inputs.read_bytes()), args.output)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('source_commit=' + commit + '\n')
            stream.write('source_manifest_sha256=' + manifest_sha256 + '\n')
    print(json.dumps(dict(installer_commit=commit, component_job=VOICE_JOB,
                         signed=False, published=False, native_acceptance=False)))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError, zipfile.BadZipFile, urllib.error.URLError) as error:
        print('Native entry input staging failed: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
