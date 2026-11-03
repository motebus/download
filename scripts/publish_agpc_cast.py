#!/usr/bin/env python3
"""Publish a pinned Cast development preview without changing other downloads."""
import argparse
import ast
import base64
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile

import publish_native as native

ASSETS = {'agpc-cast.sh', 'agpc-cast.deb', 'agpc-cast-source.tar.gz', 'README.txt', 'VALIDATION.json'}
SOURCES = {'cast.py', 'audio.py', 'cast_mode.py', 'recording.py', 'menu.py'}
FINGERPRINT = 'AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0'


def inputs(root):
    record = json.loads((root / 'scripts/agpc-cast-publication.json').read_text())
    native.require(record['schema'] == 'agpc.cast-preview-publication-inputs/v1', 'unexpected Cast input schema')
    native.require(re.fullmatch(r'0\.1\.0-dev\.\d{8}\.\d+', record['version']), 'development version required')
    native.require(record['deb_version'] == record['version'].replace('-dev.', '~dev.'), 'Debian version mismatch')
    native.require(record['candidate_tag'] == 'agpc-cast-candidate-v' + record['version'], 'candidate tag mismatch')
    native.require(record['release_channel'] == 'development-preview', 'preview channel required')
    native.require(set(record['assets']) == ASSETS, 'unexpected Cast assets')
    for pin in record['assets'].values():
        native.require(re.fullmatch(r'[a-f0-9]{64}', pin['sha256']) and 0 < pin['bytes'] < 2_000_000, 'invalid Cast asset pin')
    return record


def download(record, folder):
    for name in sorted(ASSETS):
        subprocess.run(['gh', 'release', 'download', record['candidate_tag'], '--repo', native.REPOSITORY,
                        '--pattern', name, '--dir', str(folder)], check=True)


def source_files(data):
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            native.require(member.isfile() and not path.is_absolute() and '..' not in path.parts
                           and len(path.parts) >= 2 and path.parts[0] == 'cast-cli-source'
                           and path.suffix == '.py' and member.size < 200_000, 'unsafe Cast source archive')
            name = path.relative_to('cast-cli-source').as_posix()
            native.require(name not in files and len(files) < 40, 'duplicate or excessive Cast source entries')
            files[name] = archive.extractfile(member).read()
    native.require(SOURCES <= set(files), 'source archive is missing runtime modules')
    return files


def validate_bundle(bundle, record, test=False):
    for name, pin in record['assets'].items():
        path = bundle / name
        native.require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['bytes']
                       and native.file_digest(path) == pin['sha256'], 'Cast asset digest/size mismatch: ' + name)
    script = (bundle / 'agpc-cast.sh').read_text()
    python = script.split("<<'CAST_INSTALLER_PY'\n", 1)[1].rsplit('\nCAST_INSTALLER_PY', 1)[0]
    values = {}
    for node in ast.parse(python).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {'VERSION', 'DEB_VERSION', 'DEB_SHA256', 'DEB_PAYLOAD', 'HASHES'}:
                values[node.targets[0].id] = ast.literal_eval(node.value)
    package = (bundle / 'agpc-cast.deb').read_bytes()
    native.require(values['VERSION'] == record['version'] and values['DEB_VERSION'] == record['deb_version'], 'embedded version mismatch')
    native.require(base64.b64decode(values['DEB_PAYLOAD'], validate=True) == package
                   and native.digest(package) == values['DEB_SHA256'], 'embedded package mismatch')
    native.require(set(values['HASHES']) == SOURCES, 'unexpected embedded modules')
    metadata = subprocess.check_output(['dpkg-deb', '--show', '--showformat=${Package}\t${Version}\t${Architecture}',
                                        str(bundle / 'agpc-cast.deb')], text=True)
    native.require(metadata == 'agpc-cast\t' + record['deb_version'] + '\tall', 'package identity mismatch')
    data = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(bundle / 'agpc-cast.deb')])
    sources = source_files((bundle / 'agpc-cast-source.tar.gz').read_bytes())
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for name in SOURCES:
            member = archive.getmember('./usr/lib/agpc-cast/' + name)
            native.require(member.isfile(), 'runtime module is not a file')
            content = archive.extractfile(member).read()
            native.require(content == sources[name] and native.digest(content) == values['HASHES'][name], 'runtime source binding mismatch')
    validation = json.loads((bundle / 'VALIDATION.json').read_text())
    native.require(validation['version'] == record['version'] and validation['production_ready'] is False
                   and validation['install_scope'] == 'user-local', 'preview scope mismatch')
    subprocess.run(['bash', '-n', str(bundle / 'agpc-cast.sh')], check=True)
    if test:
        with tempfile.TemporaryDirectory(prefix='cast-preview-test-') as temporary:
            root = Path(temporary)
            for name, content in sources.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(root / 'tests'), '-v'], check=True)
            subprocess.run([sys.executable, str(root / 'cast.py'), '--help'], check=True)
            subprocess.run([sys.executable, str(root / 'cast.py'), 'menu', '--help'], check=True)
    return values['HASHES']


def verify_signature(root, site, name):
    subprocess.run(['gpgv', '--keyring', str((root / 'medge-archive-keyring.gpg').resolve()),
                    str(site / (name + '.asc')), str(site / name)], check=True)


def overlay(root, site, bundle, record, source_hashes, commit, evidence, base=None):
    native.require(re.fullmatch(r'[a-f0-9]{40}', commit), 'publisher commit required')
    native.require(''.join((root / 'medge-archive-keyring.fingerprint').read_text().split()).upper() == FINGERPRINT,
                   'archive fingerprint changed')
    before = native.snapshot(site)
    prefix = 'agpc-cast/' + record['version'] + '/'
    previous = site / 'agpc-cast.source.json'
    if previous.exists():
        verify_signature(root, site, 'agpc-cast.source.json')
        old = json.loads(previous.read_text())
        native.require(old.get('schema') == 'agpc.cast-preview-source/v1', 'unrecognized previous Cast publication')
        native.require(subprocess.run(['dpkg', '--compare-versions', record['deb_version'], 'ge', old['deb_version']]).returncode == 0,
                       'Cast downgrade forbidden')
    receipt = {'schema': 'agpc.cast-preview-source/v1', 'version': record['version'], 'deb_version': record['deb_version'],
               'channel': 'development-preview', 'production_ready': False, 'installation_scope': 'user-local',
               'dpkg_registered_by_installer': False, 'embedded_package': 'agpc-cast.deb',
               'publisher': {'repository': native.REPOSITORY, 'commit': commit},
               'source': {'kind': 'user-authorized-task-build', 'archive_sha256': record['assets']['agpc-cast-source.tar.gz']['sha256'],
                          'canonical_runtime_repository': None, 'runtime_sha256': source_hashes},
               'assets': record['assets'], 'archive_key_fingerprint': FINGERPRINT}
    files = {prefix + name: (bundle / name).read_bytes() for name in ASSETS}
    files[prefix + 'agpc-cast.source.json'] = (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode()
    files[prefix + 'agpc-cast-SHA256SUMS'] = ''.join(
        native.digest(content) + '  ' + name.removeprefix(prefix) + '\n' for name, content in sorted(files.items())).encode()
    for name, content in files.items():
        if (site / name).exists():
            native.require((site / name).read_bytes() == content, 'versioned Cast content is immutable')
            verify_signature(root, site, name)
    new = set()
    for name, content in files.items():
        path = site / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o755 if name.endswith('.sh') else 0o644)
            new.add(name)
    native.sign_files(root, site, new)
    aliases = {'agpc-cast.sh', 'agpc-cast.source.json', 'agpc-cast-SHA256SUMS'}
    for name in aliases:
        for suffix in ('', '.asc'):
            (site / (name + suffix)).write_bytes((site / (prefix + name + suffix)).read_bytes())
        (site / name).chmod(0o755 if name.endswith('.sh') else 0o644)
    allowed = set(files) | {n + '.asc' for n in files} | aliases | {n + '.asc' for n in aliases}
    after = native.snapshot(site)
    native.verify_preservation(before, after, allowed)
    evidence.write_text(json.dumps({'schema': 'agpc.cast-publication-evidence/v1', 'base': base, 'source': receipt,
        'preserved_files': len(set(before) - allowed), 'published_sha256': {n: after[n] for n in sorted(allowed)}}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'publish'))
    parser.add_argument('root', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--site', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    record = inputs(args.root)
    with tempfile.TemporaryDirectory(prefix='cast-preview-bundle-') as temporary:
        bundle = args.bundle or Path(temporary)
        if args.bundle is None:
            download(record, bundle)
        hashes = validate_bundle(bundle, record, test=args.action == 'validate')
        if args.action == 'publish':
            native.require(os.environ.get('GITHUB_REPOSITORY') == native.REPOSITORY
                           and os.environ.get('GITHUB_REF') == 'refs/heads/main', 'publish only from main')
            commit = os.environ['GITHUB_SHA']
            native.require(native.gh_json('repos/' + native.REPOSITORY + '/branches/main')['commit']['sha'] == commit, 'publisher main advanced')
            native.require(args.site is not None and args.evidence is not None, 'site and evidence required')
            base = native.restore_current(args.site)
            overlay(args.root, args.site, bundle, record, hashes, commit, args.evidence, base)
            native.require(native.current_pages() == base, 'Pages base changed before promotion')


if __name__ == '__main__':
    main()
