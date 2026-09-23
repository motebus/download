#!/usr/bin/env python3
"""Promote a pinned native AGPC cohort without rebuilding unrelated APT releases."""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import agpc_profiles
import publish_apt as apt
import publish_native as native

APT_PATHS = {
    'dists/stable/main/binary-amd64/Packages', 'dists/stable/main/binary-amd64/Packages.gz',
    'dists/stable/Release', 'dists/stable/Release.gpg', 'dists/stable/InRelease',
    'agent-computer-apt-overlay.json', 'agent-computer-apt-overlay.json.asc',
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def index(site):
    packages = site / 'dists/stable/main/binary-amd64'
    text = subprocess.check_output(['apt-ftparchive', 'packages', 'pool'], cwd=site)
    (packages / 'Packages').write_bytes(text)
    (packages / 'Packages.gz').write_bytes(gzip.compress(text, mtime=0))
    options = {'Origin': 'MoteBus', 'Label': 'Sphere', 'Suite': 'stable', 'Codename': 'stable',
               'Architectures': 'amd64', 'Components': 'main',
               'Description': 'Install Sphere binary packages'}
    arguments = [value for key, item in options.items()
                 for value in ('-o', f'APT::FTPArchive::Release::{key}={item}')]
    data = subprocess.check_output(['apt-ftparchive', *arguments, 'release', 'dists/stable'], cwd=site)
    (site / 'dists/stable/Release').write_bytes(data)


def sign(root, site):
    fingerprint = apt.archive_fingerprint(root)
    passphrase = os.environ.get('MEDGE_APT_SIGNING_PASSPHRASE')
    apt.require(bool(passphrase), 'archive signing passphrase unavailable')
    common = ['gpg', '--batch', '--yes', '--pinentry-mode', 'loopback', '--passphrase-fd', '0',
              '--local-user', fingerprint, '--digest-algo', 'SHA256', '--armor']
    release = site / 'dists/stable/Release'
    for name, clear in [('dists/stable/Release.gpg', False), ('dists/stable/InRelease', True),
                        ('agent-computer-apt-overlay.json.asc', False)]:
        source = site / 'agent-computer-apt-overlay.json' if name.endswith('.json.asc') else release
        run(*common, '--clearsign' if clear else '--detach-sign', '--output', str(site / name),
            str(source), input=passphrase+'\n', text=True)
    key = str((root / 'medge-archive-keyring.gpg').resolve())
    run('gpgv', '--keyring', key, str(site / 'dists/stable/InRelease'))
    run('gpgv', '--keyring', key, str(site / 'agent-computer-apt-overlay.json.asc'),
        str(site / 'agent-computer-apt-overlay.json'))


def verify_preserved(before, after, additions):
    allowed = APT_PATHS | native.CHANGED_PATHS | agpc_profiles.PROFILE_FILES | {
        name + '.asc' for name in agpc_profiles.PROFILE_FILES} | {
        'agpc-native.source.json', 'agpc-native.source.json.asc'}
    # Existing pool files never change or disappear, even if a new version is added.
    apt.require(all(after.get(name) == checksum for name, checksum in before.items() if name not in allowed),
                'native AGPC promotion changed an unrelated existing site file')
    apt.require(set(after) - set(before) <= allowed | additions,
                'native AGPC promotion added an unreviewed site file')


def promote(root, site, evidence):
    root = root.resolve(); site = site.resolve()
    apt.require(agpc_profiles.enabled(root), 'standard/full installer pins required')
    config = apt.load_agent_computer_overlay(root)
    apt.require(config['schema'] == 'agent-computer-apt-overlay/v7', 'native AGPC v7 cohort required')
    base = native.restore_current(site)
    before = native.snapshot(site)
    apt.require((site / 'medge-archive-keyring.gpg').read_bytes() == (root / 'medge-archive-keyring.gpg').read_bytes(),
                'restored site archive key differs from reviewed key')
    run('gpgv', '--keyring', str((root / 'medge-archive-keyring.gpg').resolve()),
        str(site / 'dists/stable/InRelease'))
    with tempfile.TemporaryDirectory(prefix='agpc-native-cohort-') as temporary:
        bundle = Path(temporary) / 'cohort'
        apt.download_agent_computer_overlay(root, bundle)
        apt.validate_agent_computer_overlay(root, bundle)
        for package in apt.overlay_packages(config):
            apt.copy_package(bundle / package['asset'], site)
    shutil.copy2(root / apt.AGENT_COMPUTER_OVERLAY_FILE, site)
    index(site)
    sign(root, site)
    native_evidence = evidence.with_suffix('.native.json')
    native.overlay(root, site, native_evidence, base)
    after = native.snapshot(site)
    additions = {f"pool/main/{p['name'][0]}/{p['name']}/{p['asset']}" for p in apt.overlay_packages(config)}
    verify_preserved(before, after, additions)
    apt.require(native.current_pages() == base, 'Pages base changed during native AGPC promotion')
    result = {'schema': 'agpc.native-profile-promotion/v1', 'base': base,
              'aggregate_tag': config['release']['tag'], 'source_commit': config['release']['source_commit'],
              'changed_paths': sorted(name for name in after if before.get(name) != after[name]),
              'unchanged_existing_pool_files': sum(name.startswith('pool/') for name in before),
              'profile_sha256': {name: after[name] for name in sorted(agpc_profiles.PROFILE_FILES)},
              'native_pages': json.loads(native_evidence.read_text())}
    evidence.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'aggregate_tag': result['aggregate_tag'], 'profile_sha256': result['profile_sha256']}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('site', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    promote(args.root, args.site, args.evidence)


if __name__ == '__main__':
    main()
