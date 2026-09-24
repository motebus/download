#!/usr/bin/env python3
"""Bind standard/full native installers to an already activated signed cohort."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

PROFILE_FILES = {
    'agpc.sh', 'agpc.source.json', 'agpc-all.sh', 'agpc-all.source.json',
    'agent-sphere-apps.sh', 'agent-sphere-apps.source.json',
    'uninstall.sh',
}
LIMIT = 2 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def enabled(root):
    path = root / 'agpc.source.json'
    return path.is_file() and json.loads(path.read_text()).get('schema') == 'agpc-installer-source/v2'


def download(record, name):
    url = f"https://github.com/{record['repository']}/releases/download/{record['tag']}/{name}"
    with urllib.request.urlopen(url, timeout=60) as response:
        require(response.url.startswith('https://'), 'profile download requires HTTPS')
        data = response.read(LIMIT + 1)
    require(len(data) <= LIMIT, 'oversized profile release asset')
    return data


def activated_files(root, site):
    import publish_apt
    from validate_agent_sphere_apt import validate_full_index_pins
    standard = publish_apt.validate_agent_apps_installer(root)
    require(standard['schema'] == 'agpc-installer-source/v2', 'standard/full profile required')
    full = json.loads((root / 'agpc-all.source.json').read_text())
    require((standard['tag'], standard['source_commit']) == (full['tag'], full['source_commit']),
            'standard/full profiles must share an exact source release')
    manifest = json.loads(download(standard, 'release-manifest.json'))
    require(manifest.get('schema') == 'agent-sphere-release/v2'
            and manifest.get('source_commit') == standard['source_commit']
            and manifest.get('source_ref') == 'refs/heads/main'
            and manifest.get('version') == standard['tag'][1:]
            and manifest.get('component_baseline', {}).get('pending_native_components') == []
            and manifest.get('installer_profiles') == {
                'agpc.sh': 'standard', 'agpc-all.sh': 'full',
                'agent-sphere-apps.sh': 'full-compatibility'},
            'installer source release is not the completed native profile build')
    assets = manifest.get('assets', [])
    require(isinstance(assets, list) and all(isinstance(item, dict) for item in assets),
            'invalid installer release asset inventory')
    for record in (standard, full):
        matches = [item for item in assets if item.get('name') == record['asset']]
        require(len(matches) == 1 and matches[0].get('sha256') == record['sha256'],
                'installer source release digest differs from reviewed pin')
        require(download(record, record['asset']) == (root / record['asset']).read_bytes(),
                'installer bytes differ from their versioned release')
    config = publish_apt.load_agent_computer_overlay(root)
    require(config['schema'] == 'agent-computer-apt-overlay/v7'
            and json.loads((site / 'agent-computer-apt-overlay.json').read_text()) == config,
            'standard/full installers require their activated native package cohort')
    key = str((root / 'medge-archive-keyring.gpg').resolve())
    subprocess.run(['gpgv', '--keyring', key, str(site / 'dists/stable/InRelease')], check=True)
    subprocess.run(['gpgv', '--keyring', key, str(site / 'agent-computer-apt-overlay.json.asc'),
                    str(site / 'agent-computer-apt-overlay.json')], check=True)
    validate_full_index_pins(site, config)
    for package in publish_apt.overlay_packages(config):
        path = site / 'pool/main' / package['name'][0] / package['name'] / package['asset']
        require(path.is_file() and not path.is_symlink()
                and digest(path.read_bytes()) == package['sha256'], 'activated package payload mismatch')
    files = {name: (root / name).read_bytes() for name in PROFILE_FILES}
    return {'standard': standard, 'full': full, 'aggregate_tag': config['release']['tag']}, files
