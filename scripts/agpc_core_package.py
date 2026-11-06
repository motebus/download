"""Validate the closed Core composition payload without executing package code."""
import io
import json
from pathlib import PurePosixPath
import subprocess
import tarfile

import publish_apt as apt

PAYLOAD = {'usr/share/doc/agpc-core/README', 'usr/share/agpc-core/cohort.json',
           'usr/share/doc/agpc-core/PROVENANCE.json'}
FLAGS = ('installation_admitted', 'upgrade_acceptance', 'removal_acceptance',
         'rollback_acceptance', 'release_admitted', 'runtime_ready')


def json_value(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            apt.require(key not in result, 'duplicate Core JSON key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def members(path, option):
    raw = subprocess.check_output(['dpkg-deb', option, str(path)])
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            name = member.name.removeprefix('./').rstrip('/') or '.'
            apt.require(name not in result and not name.startswith('/')
                        and '..' not in PurePosixPath(name).parts, 'unsafe Core archive member')
            apt.require(member.uid == member.gid == 0 and member.uname in ('', 'root')
                        and member.gname in ('', 'root'), 'Core archive must be root-owned')
            apt.require((member.isdir() and member.mode == 0o755)
                        or (member.isfile() and member.mode == 0o644 and member.size <= 2_000_000),
                        'Core archive must contain only ordinary metadata files/directories')
            result[name] = None if member.isdir() else archive.extractfile(member).read()
    return result


def validate_core_package(path, approved):
    package = approved['agpc-core']
    apt.require(apt.sha256(path) == package['sha256'], 'Core archive digest differs from approved pin')
    for field, value in [('Package', 'agpc-core'), ('Version', apt.AGPC_CORE_VERSION), ('Architecture', 'amd64')]:
        apt.require(apt.package_field(path, field) == value, 'Core package identity changed: ' + field)
    terms = apt.package_field(path, 'Depends').split(', ')
    relations = {name: '>=' if name == 'agpc-cdp' else '=' for name in apt.AGPC_CORE_DEPENDENCIES}
    expected = {f'{name} ({relations[name]} {version})' for name, version in apt.AGPC_CORE_DEPENDENCIES.items()}
    apt.require(len(terms) == len(expected) and set(terms) == expected,
                'Core must depend on exactly the reviewed native roots and versions')
    apt.require(all(approved[name]['version'] == version for name, version in apt.AGPC_CORE_DEPENDENCIES.items()),
                'Core dependencies differ from the signed cohort')
    for field in ('Pre-Depends', 'Recommends', 'Suggests', 'Provides', 'Breaks', 'Replaces', 'Conflicts'):
        apt.require(not apt.package_field(path, field), 'Core has an unreviewed relationship: ' + field)
    controls = members(path, '--ctrl-tarfile')
    apt.require(set(controls) == {'.', 'control'} and controls['.'] is None,
                'Core control archive may contain only control; hooks/triggers are forbidden')
    data = members(path, '--fsys-tarfile')
    directories = {'.'} | {str(parent) for name in PAYLOAD for parent in PurePosixPath(name).parents}
    apt.require(set(data) == PAYLOAD | directories and all(data[name] is None for name in directories),
                'Core package payload differs from its closed metadata-only inventory')
    cohort = json_value(data['usr/share/agpc-core/cohort.json'])
    proof = json_value(data['usr/share/doc/agpc-core/PROVENANCE.json'])
    apt.require(cohort.get('schema') == 'agpc.core.package-cohort/v1'
                and cohort.get('name') == 'agpc-core' and cohort.get('version') == apt.AGPC_CORE_VERSION
                and cohort.get('architecture') == 'amd64' and cohort.get('kind') == 'dependency-cohort'
                and cohort.get('installer') == 'agpc-mesh.sh', 'Core embedded cohort identity differs')
    rows = cohort.get('dependencies')
    apt.require(isinstance(rows, list) and len(rows) == len(expected)
                and all(isinstance(row, dict) and row.get('relation') == relations.get(row.get('name')) for row in rows)
                and {row.get('name'): row.get('version') for row in rows} == apt.AGPC_CORE_DEPENDENCIES,
                'Core embedded dependencies differ from package control')
    apt.require(proof.get('schema') == 'agpc.core.package-source/v1'
                and proof.get('source', {}).get('project') == 1336
                and proof['source'].get('commit') == package['provenance']['source_commit'],
                'Core embedded source differs from the original package producer')
    apt.require(cohort.get('transitive_cohort_admitted') is False
                and all(cohort.get(flag) is False and proof.get(flag) is False for flag in FLAGS),
                'Core build metadata must not manufacture lifecycle or release admission')
    apt.validate_public_deb_content(path)
    return cohort
