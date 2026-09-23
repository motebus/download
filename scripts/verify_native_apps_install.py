"""Accept the published standalone apps installer on an ephemeral native runner."""
import hashlib
import json
import os
from pathlib import Path
import platform

import publish_native
from verify_native_linux_install import command, containers


def main():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Linux'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or platform.machine() != 'x86_64' or Path('/proc/1/comm').read_text().strip() != 'systemd'):
        raise RuntimeError('Installation acceptance requires an ephemeral native GitHub Linux runner')
    root = Path(__file__).resolve().parents[1]
    output = root / '.cache/native-apps-acceptance'
    output.mkdir(parents=True, exist_ok=True)
    _, provenance, files = publish_native.assemble(root)
    script = output / 'agpc-apps.sh'
    script.write_bytes(files['agpc-apps.sh'])
    plan = json.loads(command(['bash', str(script), 'install', '--dry-run', '--json']))
    for directory in ('/usr/local/bin', '/usr/share'):
        command(['sudo', 'chown', 'root:root', directory])
        command(['sudo', 'chmod', '0755', directory])
    core_receipt = Path('/usr/local/lib/agpc-native/install.json')
    if core_receipt.exists():
        raise RuntimeError('Standalone acceptance requires a host without a core receipt')
    unrelated = ['uchat', 'uchatd', 'xrdp', 'xorgxrdp', 'cx-mesh', 'agent-sphere']
    def inventory(names):
        rows = command(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${Status}\n']).splitlines()
        return [row for row in rows if row.split('\t')[0] in names]
    before = inventory(unrelated)
    containers_before = containers()
    command(['sudo', 'bash', str(script), 'install'])
    if core_receipt.exists() or inventory(unrelated) != before or containers() != containers_before:
        raise RuntimeError('Standalone apps changed unrelated core or container packages')
    receipt_path = Path('/usr/local/lib/agpc-native/apps-install.json')
    receipt = json.loads(receipt_path.read_text())
    if receipt['state'] != 'installed' or receipt['ready'] or receipt['packages'] != plan['packages']:
        raise RuntimeError('Standalone apps receipt did not verify installation')
    for package in plan['packages']:
        expected = 'install ok installed\t' + package['version']
        if command(['dpkg-query', '-W', '-f=${Status}\t${Version}', package['name']]).strip() != expected:
            raise RuntimeError('Standalone application package verification failed')
    config = Path('/etc/mote/ss-webos/ss-webos-deb.env')
    command(['sudo', 'sed', '-i', '$a# Standalone apps preservation marker', str(config)])
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    # An unrelated failed core receipt must not block the second installation.
    failed_receipt = '{"schema":"agpc.native-install/v1","state":"failed","stage":"rdp"}\n'
    fixture = output / 'failed-core.json'
    fixture.write_text(failed_receipt)
    command(['sudo', 'install', '-m', '0644', str(fixture), str(core_receipt)])
    command(['sudo', 'bash', str(script), 'install'])
    if core_receipt.read_text() != failed_receipt or hashlib.sha256(config.read_bytes()).hexdigest() != config_hash:
        raise RuntimeError('Reinstallation changed core receipt or application configuration')
    if inventory(unrelated) != before or containers() != containers_before:
        raise RuntimeError('Reinstallation changed unrelated packages')
    final = json.loads(receipt_path.read_text())
    if final['state'] != 'installed' or final['runtime_packages']:
        raise RuntimeError('Reinstallation did not retain existing direct dependencies')
    (output / 'evidence.json').write_text(json.dumps({
        'entrypoint_sha256': provenance['files']['agpc-apps.sh']['sha256'],
        'standalone_install': 'passed', 'failed_core_reinstall': 'passed',
        'conffile_preserved': True, 'unrelated_packages_preserved': True,
        'receipt': final, 'ready': False,
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
