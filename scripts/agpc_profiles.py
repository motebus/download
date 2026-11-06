#!/usr/bin/env python3
"""Bind standard/full native installers to an already activated signed cohort."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

PROFILE_FILES = {
    'agpc.sh', 'agpc.source.json', 'agpc-all.sh', 'agpc-all.source.json',
    'agpc-apps.sh', 'agpc-apps.source.json',
    'uninstall.sh',
}
LEGACY_PROFILE_FILES = {
    "agpc.sh", "agpc.source.json", "agpc-all.sh", "agpc-all.source.json",
    "agent-sphere-apps.sh", "agent-sphere-apps.source.json", "uninstall.sh",
}
CORE_PROFILE_FILES = {"agpc-core.sh", "agpc-core.source.json"}
MESH_PROFILE_FILES = {"agpc-mesh.sh", "agpc-mesh.source.json"}
LIMIT = 2 * 1024 * 1024


def profile_files(root):
    source = json.loads((root / "agpc.source.json").read_text())
    import publish_apt
    if publish_apt.legacy_installer_aliases(root): return LEGACY_PROFILE_FILES
    return PROFILE_FILES | set(publish_apt.core_installer_files(source.get("schema")))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def enabled(root):
    path = root / 'agpc.source.json'
    return path.is_file() and json.loads(path.read_text()).get('schema') in ('agpc-installer-source/v2', 'agpc-installer-source/v3', 'agpc-installer-source/v4')


def download(record, name):
    url = f"https://github.com/{record['repository']}/releases/download/{record['tag']}/{name}"
    with urllib.request.urlopen(url, timeout=60) as response:
        require(response.url.startswith('https://'), 'profile download requires HTTPS')
        data = response.read(LIMIT + 1)
    require(len(data) <= LIMIT, 'oversized profile release asset')
    return data


def activated_files(root, site):
    import publish_apt
    if publish_apt.legacy_installer_aliases(root): return legacy_activated_files(root, site)
    from validate_agent_sphere_apt import validate_full_index_pins
    standard = publish_apt.validate_agent_apps_installer(root)
    require(standard['schema'] in ('agpc-installer-source/v2', 'agpc-installer-source/v3', 'agpc-installer-source/v4'), 'standard/full profile required')
    mesh = standard['schema'] == 'agpc-installer-source/v4'
    view = standard['schema'] in ('agpc-installer-source/v3', 'agpc-installer-source/v4')
    full = json.loads((root / 'agpc-all.source.json').read_text())
    apps = json.loads((root / 'agpc-apps.source.json').read_text())
    require((standard['tag'], standard['source_commit']) == (full['tag'], full['source_commit'])
            == (apps['tag'], apps['source_commit']),
            'standard/full/apps profiles must share an exact source release')
    records = [standard, full, apps]
    expected_profiles = {'agpc.sh': 'standard', 'agpc-all.sh': 'full', 'agpc-apps.sh': 'apps'}
    if view:
        entry, receipt = publish_apt.core_installer_files(standard['schema'])
        core = json.loads((root / receipt).read_text())
        records.append(core)
        expected_profiles[entry] = 'standard'
    manifest = json.loads(download(standard, 'release-manifest.json'))
    require(manifest.get('schema') == 'agent-sphere-release/v2'
            and manifest.get('source_commit') == standard['source_commit']
            and manifest.get('source_ref') == 'refs/heads/main'
            and manifest.get('version') == standard['tag'][1:]
            and manifest.get('component_baseline', {}).get('pending_native_components') == []
            and manifest.get('installer_profiles') == expected_profiles,
            'installer source release is not the completed native profile build')
    assets = manifest.get('assets', [])
    require(isinstance(assets, list) and all(isinstance(item, dict) for item in assets),
            'invalid installer release asset inventory')
    for record in records:
        matches = [item for item in assets if item.get('name') == record['asset']]
        require(len(matches) == 1 and matches[0].get('sha256') == record['sha256'],
                'installer source release digest differs from reviewed pin')
        require(download(record, record['asset']) == (root / record['asset']).read_bytes(),
                'installer bytes differ from their versioned release')
    if view:
        matches = [item for item in assets if item.get('name') == 'uninstall.sh']
        require(len(matches) == 1 and matches[0].get('sha256') == digest((root / 'uninstall.sh').read_bytes())
                and download(standard, 'uninstall.sh') == (root / 'uninstall.sh').read_bytes(),
                'View removal policy differs from its source release')
    config = publish_apt.load_agent_computer_overlay(root)
    require(config['schema'] in ('agent-computer-apt-overlay/v8', 'agent-computer-apt-overlay/v9',
                                 'agent-computer-apt-overlay/v10', 'agent-computer-apt-overlay/v11',
                                 'agent-computer-apt-overlay/v12', 'agent-computer-apt-overlay/v13')
            and json.loads((site / 'agent-computer-apt-overlay.json').read_text()) == config,
            'standard/full installers require their activated native package cohort')
    require(mesh == (config['schema'] == 'agent-computer-apt-overlay/v13')
            and view == (config['schema'] in ('agent-computer-apt-overlay/v12', 'agent-computer-apt-overlay/v13')),
            'Core entry schema must match its exact View or Core composition cohort')
    if view:
        require(manifest.get('aggregate_tag') == config['release']['tag']
                and manifest.get('overlay_sha256') == digest((root / 'agent-computer-apt-overlay.json').read_bytes()),
                'View installer release must bind the exact aggregate and overlay')
    key = str((root / 'medge-archive-keyring.gpg').resolve())
    subprocess.run(['gpgv', '--keyring', key, str(site / 'dists/stable/InRelease')], check=True)
    subprocess.run(['gpgv', '--keyring', key, str(site / 'agent-computer-apt-overlay.json.asc'),
                    str(site / 'agent-computer-apt-overlay.json')], check=True)
    validate_full_index_pins(site, config)
    for package in publish_apt.overlay_packages(config):
        path = site / 'pool/main' / package['name'][0] / package['name'] / package['asset']
        require(path.is_file() and not path.is_symlink()
                and digest(path.read_bytes()) == package['sha256'], 'activated package payload mismatch')
    files = {name: (root / name).read_bytes() for name in profile_files(root)}
    result = {'standard': standard, 'full': full, 'apps': apps,
              'aggregate_tag': config['release']['tag']}
    if view: result['core'] = core
    return result, files


def index_html(root):
    """Render current links from the activated schema; never relabel old releases."""
    raw = (root / 'scripts/native-index.html').read_text()
    source_path = root / 'agpc.source.json'
    source = json.loads(source_path.read_text()) if source_path.is_file() else {}
    if source.get('schema') != 'agpc-installer-source/v4':
        return raw.encode()
    import publish_apt
    config = publish_apt.load_agent_computer_overlay(root)
    require(config['schema'] == publish_apt.AGENT_COMPUTER_CORE_SCHEMA, 'Mesh download links require the Core cohort')
    package = next(p for p in config['release']['packages'] if p['name'] == 'agpc-core')
    raw = raw.replace('agpc-core.sh', 'agpc-mesh.sh').replace('agpc-core.source.json', 'agpc-mesh.source.json')
    url = 'https://github.com/motebus/download/releases/download/' + config['release']['tag'] + '/' + package['asset']
    details = ('<p>Core installs the native <code>agpc-core</code> dependency package with iAgent and vModel. '
               'The Mesh entry is the Core installer; <code>agpc-mesh</code> remains its separate runtime package. '
               '<a href="' + url + '">' + package['asset'] + '</a> is the exact versioned DEB.</p>\n')
    return raw.replace('<h2>Core installation</h2>', details + '<h2>Core installation</h2>').encode()


def legacy_activated_files(root, site):
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
    files = {name: (root / name).read_bytes() for name in LEGACY_PROFILE_FILES}
    return {'standard': standard, 'full': full, 'aggregate_tag': config['release']['tag']}, files
