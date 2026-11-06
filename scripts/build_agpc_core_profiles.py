#!/usr/bin/env python3
"""Build unsigned Mesh/All installers for the exact Core composition.

No active source pin is changed. Inputs must be reviewed, committed public
component releases; signing and six native profile jobs still precede Pages.
"""
import argparse
import ast
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request

import publish_apt as apt
from agpc_core_package import validate_core_package

INPUT_SCHEMA = 'agpc-core-profile-input/v1'
COMPONENTS = ('agpc-manager', 'agpc-view', 'agpc-mesh', 'agpc-core', 'agpc-vmodel')
PROFILES = {'agpc.sh': 'standard', 'agpc-mesh.sh': 'standard',
            'agpc-all.sh': 'full', 'agpc-apps.sh': 'apps'}
BASELINE_FILES = ('agpc.sh', 'agpc.source.json', 'agpc-core.sh', 'agpc-core.source.json',
                  'agpc-all.sh', 'agpc-all.source.json', 'agpc-apps.sh', 'agpc-apps.source.json',
                  'uninstall.sh', apt.AGENT_COMPUTER_OVERLAY_FILE,
                  *apt.WINDOWS_INSTALLERS, apt.WINDOWS_INSTALLER_SOURCE)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def replace_once(text, old, new):
    apt.require(text.count(old) == 1, 'Core installer baseline drift at: ' + old)
    return text.replace(old, new)


def validate_inputs(root, value):
    apt.require(isinstance(value, dict) and set(value) == {
        'schema', 'installer_tag', 'aggregate_tag', 'baseline_source_commit',
        'baseline_files', 'components'}, 'invalid Core profile input fields')
    apt.require(value['schema'] == INPUT_SCHEMA, 'invalid Core profile input schema')
    apt.require(re.fullmatch(r'[0-9a-f]{40}', value['baseline_source_commit']) is not None,
                'exact baseline commit required')
    apt.require(re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-[0-9]+', value['installer_tag']) is not None
                and re.fullmatch(r'agent-computer-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]+', value['aggregate_tag']) is not None,
                'new exact installer and aggregate tags required')
    apt.require(isinstance(value['baseline_files'], dict) and set(value['baseline_files']) == set(BASELINE_FILES)
                and all(apt.sha256(root / name) == checksum for name, checksum in value['baseline_files'].items()),
                'baseline source bytes differ from reviewed pins')
    baseline = apt.load_agent_computer_overlay(root)
    source = apt.validate_agent_apps_installer(root)
    apt.require(baseline['schema'] == apt.AGENT_COMPUTER_VIEW_SCHEMA
                and baseline['release']['tag'] == 'agent-computer-v0.3.0-85'
                and source['schema'] == apt.AGENT_VIEW_INSTALLER_SCHEMA and source['tag'] == 'v0.3.0-96',
                'Core producer requires the immutable v96/cohort85 baseline')
    apt.require(value['installer_tag'] != source['tag'] and value['aggregate_tag'] != baseline['release']['tag'],
                'Core composition needs new immutable release tags')
    rows = value['components']
    apt.require(isinstance(rows, list) and [row.get('package', {}).get('name') for row in rows] == list(COMPONENTS),
                'exact Manager/View/Mesh/Core/vModel original component inventory required')
    config = copy.deepcopy(baseline); config['schema'] = apt.AGENT_COMPUTER_CORE_SCHEMA
    config['release']['tag'] = value['aggregate_tag']
    packages = {p['name']: p for p in config['release']['packages']}
    for row in rows:
        apt.require(set(row) == {'package', 'source_tag', 'main_job_id'}
                    and type(row['main_job_id']) is int and row['main_job_id'] > 0
                    and isinstance(row['source_tag'], str)
                    and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', row['source_tag']) is not None
                    and row['source_tag'] not in (value['aggregate_tag'], baseline['release']['tag']),
                    'exact original main job and distinct component release required')
        packages[row['package']['name']] = copy.deepcopy(row['package'])
    config['release']['packages'] = [packages[name] for name in apt.canonical_packages(config)]
    apt.validate_full_overlay_config(config['release'], schema=config['schema'])
    return baseline, config


def render_profile(data, manager_sha):
    """Modify only reviewed current target pins, retaining historical migration evidence."""
    text = data.decode()
    for name, old, new in [('agpc-manager', '4.4.0-2', '4.4.0-3'),
                           ('agpc-view', '0.1.0-1', '0.1.0-4'), ('agpc-mesh', '3.0.0-3', '3.0.0-6')]:
        text = replace_once(text, f'{name}={old}', f'{name}={new}')
        text = replace_once(text, f'[{name}]={old}', f'[{name}]={new}')
    for old, new in [
        ('Install native AGPC: agent-sphere,', 'Install native AGPC Core: agpc-core, agent-sphere,'),
        ("required={'agent-sphere'", "required={'agpc-core','agpc-vmodel','iagent','medge','agent-sphere'"),
        ('\npackages=(', f'\npackages=(agpc-core={apt.AGPC_CORE_VERSION} agpc-vmodel={apt.AGPC_VMODEL_VERSION} iagent=1.0.0-1 medge=3.3.0-2 '),
        ('declare -A floor=(', f'declare -A floor=([agpc-core]={apt.AGPC_CORE_VERSION} [agpc-vmodel]={apt.AGPC_VMODEL_VERSION} [iagent]=1.0.0-1 '),
        ('$name == mote-secd ||', '$name == agpc-core || $name == agpc-vmodel || $name == iagent || $name == mote-secd ||'),
        ("[[ ${installed[agpc-manager]:-} == 4.4.0-2 ]] || fail 'Manager migration requires exact agpc-manager 4.4.0-2'",
         "[[ ${installed[agpc-manager]:-} == 4.4.0-3 ]] || fail 'Manager migration requires exact agpc-manager 4.4.0-3'"),
        ('2e2b6f0ee79c1d5c5b9d300fcefba9e21da05acacbfa6fc8093c71c8a6f1e091', manager_sha),
    ]:
        text = replace_once(text, old, new)
    previous_medge = """# Upgrade the existing management backend with its renamed Mesh owner;
# fresh profiles retain their existing package selection.
if [[ $(dpkg-query -W -f='${db:Status-Status}' medge 2>/dev/null || true) == installed ]]; then
    packages+=(medge=3.3.0-2)
fi
"""
    text = replace_once(text, previous_medge,
                        '# The Core profile includes the exact local management backend on fresh installs and upgrades.\n')
    return text.encode()


def archive_members(path, option):
    raw = subprocess.check_output(['dpkg-deb', option, str(path)])
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for item in archive:
            name = item.name.removeprefix('./').rstrip('/')
            apt.require(name not in result and not name.startswith('/') and '..' not in Path(name).parts,
                        'unsafe or duplicate component archive entry')
            result[name] = (item, archive.extractfile(item).read() if item.isfile() else None)
    return result


def removal_policy(path, package):
    apt.require(apt.sha256(path) == package['sha256'], 'component DEB checksum differs')
    for field, key in [('Package', 'name'), ('Version', 'version'), ('Architecture', 'architecture')]:
        apt.require(apt.package_field(path, field) == package[key], 'component DEB identity differs')
    apt.validate_deb_archive_permissions(path)
    apt.validate_public_deb_content(path)
    control = archive_members(path, '--ctrl-tarfile'); data = archive_members(path, '--fsys-tarfile')
    hooks = {}
    for name in ('prerm', 'postrm'):
        record = control.get(name)
        apt.require(record is None or record[0].isfile(), 'removal hook must be regular')
        hooks[name] = sha(record[1]) if record else None
    units = sorted(Path(name).name for name, (item, _) in data.items()
                   if item.isfile() and re.fullmatch(r'(?:usr/)?lib/systemd/system/[^/]+\.(?:service|socket|timer)', name))
    retained = sorted('/' + name for name, (item, _) in data.items() if item.isfile() and name.endswith('-mchat.env'))
    return {**{key: package[key] for key in ('version', 'architecture', 'sha256')},
            'hooks': hooks, 'units': units, 'retained_payloads': retained}


def render_uninstaller(data, aggregate_tag, policies):
    text = data.decode(); marker = "<<'PY_UNINSTALL_PREFLIGHT'\n"
    prefix, rest = text.split(marker, 1); code, suffix = rest.split('\nPY_UNINSTALL_PREFLIGHT\n', 1)
    nodes = {node.targets[0].id: node for node in ast.parse(code).body
             if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    policy = ast.literal_eval(nodes['POLICY'].value)
    alternate = ast.literal_eval(nodes['ALTERNATE_POLICY'].value)
    for name, value in policies.items():
        if name in policy: alternate.setdefault(name, []).append(policy[name])
        policy[name] = value
    replacements = {'POLICY': policy, 'ALTERNATE_POLICY': alternate, 'RELEASE_TAG': aggregate_tag}
    lines = code.splitlines(keepends=True)
    for name in sorted(replacements, key=lambda name: nodes[name].lineno, reverse=True):
        node = nodes[name]
        lines[node.lineno - 1:node.end_lineno] = [name + ' = ' + repr(replacements[name]) + '\n']
    code = replace_once(''.join(lines), "catalog.get('schema') != 'agent-computer-apt-overlay/v12'",
                        "catalog.get('schema') != 'agent-computer-apt-overlay/v13'")
    return (prefix + marker + code.rstrip('\n') + '\nPY_UNINSTALL_PREFLIGHT\n' + suffix).encode()


def build(root, inputs, output, source_commit, component_dir):
    apt.require(re.fullmatch(r'[0-9a-f]{40}', source_commit) is not None, 'exact producer source required')
    baseline, config = validate_inputs(root, inputs)
    approved = {p['name']: p for p in config['release']['packages']}
    policies = {name: removal_policy(component_dir / approved[name]['asset'], approved[name]) for name in COMPONENTS}
    validate_core_package(component_dir / approved['agpc-core']['asset'], approved)
    apt.require(not output.exists(), 'output must be a new directory')
    config['release']['source_commit'] = source_commit
    overlay = encoded(config)
    files = {name: render_profile((root / name).read_bytes(), approved['agpc-manager']['sha256'])
             for name in ('agpc.sh', 'agpc-all.sh')}
    files['agpc-mesh.sh'] = files['agpc.sh']
    files['agpc-apps.sh'] = (root / 'agpc-apps.sh').read_bytes()
    files['uninstall.sh'] = render_uninstaller((root / 'uninstall.sh').read_bytes(), inputs['aggregate_tag'], policies)
    manifest = {'schema': 'agent-sphere-release/v2', 'version': inputs['installer_tag'][1:],
                'source_commit': source_commit, 'source_ref': 'refs/heads/main',
                'component_baseline': {'pending_native_components': []}, 'installer_profiles': PROFILES,
                'assets': [{'name': name, 'sha256': sha(data), 'bytes': len(data)} for name, data in sorted(files.items())],
                'aggregate_tag': inputs['aggregate_tag'], 'overlay_sha256': sha(overlay),
                'core_producers': inputs['components'], 'baseline_source_commit': inputs['baseline_source_commit'],
                'native_profile_acceptance': 'required-before-pages-deploy'}
    for name, profile in PROFILES.items():
        files[name.replace('.sh', '.source.json')] = encoded({
            'schema': apt.AGENT_MESH_INSTALLER_SCHEMA, 'repository': 'motebus/download',
            'tag': inputs['installer_tag'], 'source_commit': source_commit,
            'asset': name, 'sha256': sha(files[name]), 'profile': profile})
    files[apt.AGENT_COMPUTER_OVERLAY_FILE] = overlay
    files['release-manifest.json'] = encoded(manifest)
    tags = {row['package']['name']: row['source_tag'] for row in inputs['components']}
    files['aggregate-component-release.json'] = encoded({
        'schema': 'reviewed-native-publication/v2', 'tag': inputs['aggregate_tag'],
        'public_source_commit': 'GITHUB_SHA', 'title': 'AGPC Core composition and Mesh installer',
        'notes': 'Exact native Core composition; package publication does not establish runtime readiness.',
        'assets': [{'name': p['asset'], 'sha256': p['sha256'],
                    'source_tag': tags.get(p['name'], baseline['release']['tag'])} for p in apt.overlay_packages(config)]})
    files['SHA256SUMS'] = ''.join(f'{sha(data)}  {name}\n' for name, data in sorted(files.items())).encode()
    output.mkdir(parents=True)
    for name, data in files.items():
        path = output / name; path.write_bytes(data); path.chmod(0o755 if name.endswith('.sh') else 0o644)
    for name in (*PROFILES, 'uninstall.sh'): subprocess.run(['bash', '-n', str(output / name)], check=True)
    return manifest


def export_baseline(root, commit, destination):
    apt.require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None, 'exact baseline commit required')
    destination.mkdir()
    for name in BASELINE_FILES:
        path = destination / name
        path.write_bytes(subprocess.check_output(['git', 'show', commit + ':' + name], cwd=root))
        path.chmod(0o755 if name.endswith(('.sh', '.ps1')) else 0o644)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path); parser.add_argument('inputs', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args(); root = args.root.resolve(); commit = os.environ.get('CI_COMMIT_SHA', '')
    apt.require(os.environ.get('CI_COMMIT_BRANCH') == 'main' and os.environ.get('CI_COMMIT_REF_PROTECTED') == 'true',
                'Core profiles require protected main CI')
    apt.require(commit == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
                and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=root), 'exact clean CI source required')
    relative = args.inputs.resolve().relative_to(root).as_posix()
    raw = subprocess.check_output(['git', 'show', commit + ':' + relative], cwd=root)
    apt.require(raw == args.inputs.read_bytes(), 'Core inputs must be the committed original blob')
    inputs = json.loads(raw)
    with tempfile.TemporaryDirectory(prefix='agpc-core-profiles-') as folder:
        temporary = Path(folder); baseline = export_baseline(root, inputs['baseline_source_commit'], temporary / 'baseline')
        validate_inputs(baseline, inputs)
        for row in inputs['components']:
            package = row['package']
            url = 'https://github.com/motebus/download/releases/download/' + row['source_tag'] + '/' + package['asset']
            with urllib.request.urlopen(url, timeout=120) as response:
                apt.require(response.url.startswith('https://'), 'component download requires HTTPS')
                data = response.read(64 * 1024 * 1024 + 1)
            apt.require(len(data) <= 64 * 1024 * 1024 and sha(data) == package['sha256'], 'component digest differs from committed original pin')
            (temporary / package['asset']).write_bytes(data)
        build(baseline, inputs, args.output, commit, temporary)


if __name__ == '__main__': main()
