"""Bounded native-install policy for release artifacts and fresh CI targets.

This is a direct command/dependency audit, not a general shell interpreter or
proof that an arbitrary runtime payload can never launch another process.
"""
from __future__ import annotations

import io
from pathlib import Path
import re
import shlex
import subprocess
import tarfile

RUNTIME_PACKAGE = re.compile(r'^(?:docker(?:[.+-].*)?|moby(?:-.*)?|podman(?:-.*)?|containerd(?:[.-].*)?|runc|crun|buildah|nerdctl|cri-o(?:-.*)?|lxc(?:-.*)?|lxd(?:-.*)?|incus(?:-.*)?|systemd-container)$')
RUNTIME_COMMAND = re.compile(r'^(?:docker(?:[.-].*)?|dockerd|podman(?:-.*)?|containerd(?:-.*)?|runc|crun|buildah|nerdctl|ctr|crio|lxc(?:-.*)?|lxd|incus(?:-.*)?|systemd-nspawn)$')


def reject_runtime_packages(names):
    denied = sorted({name.split(':', 1)[0] for name in names if RUNTIME_PACKAGE.fullmatch(name.split(':', 1)[0])})
    if denied:
        raise ValueError('native AGPC must not install container runtime packages: ' + ', '.join(denied))


def dependencies(fields):
    names = []
    for field in ('Depends', 'Pre-Depends', 'Recommends'):
        for term in fields.get(field, '').split(','):
            for alternative in term.split('|'):
                match = re.match(r'\s*([a-z0-9][a-z0-9+.-]*)', alternative)
                if match:
                    names.append(match[1])
    reject_runtime_packages(names)


def direct_command(text):
    # Scan command positions only: comments, diagnostic arguments and deliberate
    # InaccessiblePaths=-/run/docker.sock prohibitions are not invocations.
    for line in text.replace('\\\n', ' ').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        for part in re.split(r'[;&|]', line):
            try:
                words = shlex.split(part, comments=True)
            except ValueError:
                continue  # Dynamic shell constructs remain outside this audit.
            while words and (Path(words[0].lstrip('-+!:@')).name in
                             ('if', 'then', 'elif', 'do', 'exec', 'sudo', 'env') or '=' in words[0]):
                words.pop(0)
            if not words:
                continue
            command = Path(words[0].lstrip('-+!:@')).name
            if RUNTIME_COMMAND.fullmatch(command):
                raise ValueError('container runtime command in installation/startup path')
            if command in ('sh', 'bash', 'dash') and len(words) >= 3 and words[1] == '-c':
                direct_command(words[2])


def unit_directives(text):
    for line in text.replace('\\\n', ' ').splitlines():
        if '=' not in line or line.lstrip().startswith(('#', ';')):
            continue
        key, value = line.strip().split('=', 1)
        key = key.strip()
        if re.fullmatch(r'Exec[A-Za-z]+', key):
            direct_command(value)
        if key in ('Requires', 'Requisite', 'Wants', 'BindsTo', 'Upholds', 'Sockets', 'Unit'):
            for unit in value.split():
                name = unit.rsplit('.', 1)[0].split('@', 1)[0]
                if RUNTIME_COMMAND.fullmatch(name):
                    raise ValueError('container runtime dependency in systemd unit')
        if key in ('BindPaths', 'BindReadOnlyPaths', 'ReadWritePaths', 'ReadOnlyPaths'):
            for value_path in value.split():
                # Colon-separated bind source/destination and optional prefixes.
                for path in value_path.split(':'):
                    if Path(path).name in ('docker.sock', 'podman.sock', 'containerd.sock', 'crio.sock'):
                        raise ValueError('container runtime socket grant in systemd unit')


def audit_deb(path):
    result = {'asset': Path(path).name, 'hooks': 0, 'units': 0}
    raw = subprocess.check_output(['dpkg-deb', '--ctrl-tarfile', str(path)])
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        controls = {member.name.removeprefix('./'): member for member in archive}
        fields = {}
        key = None
        for line in archive.extractfile(controls['control']).read().decode().splitlines():
            if line.startswith((' ', '\t')) and key:
                fields[key] += ' ' + line.strip()
            elif ':' in line:
                key, value = line.split(':', 1)
                fields[key] = value.strip()
        dependencies(fields)
        reject_runtime_packages([fields['Package']])
        for name in ('preinst', 'postinst', 'prerm', 'postrm'):
            if name in controls:
                direct_command(archive.extractfile(controls[name]).read().decode())
                result['hooks'] += 1
    process = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(path)], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for member in archive:
                if (member.isfile() and any(location in member.name for location in ('/systemd/system/', '/systemd/user/'))
                        and member.name.endswith(('.service', '.socket', '.target', '.timer', '.path', '.mount', '.automount'))):
                    unit_directives(archive.extractfile(member).read().decode())
                    result['units'] += 1
        if process.wait():
            raise ValueError('cannot inspect native package payload')
    finally:
        if process.stdout:
            process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    return result
