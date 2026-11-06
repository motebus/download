#!/usr/bin/env python3
"""Sign source-bound component previews using the existing archive release flow."""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = 'motebus/download'
WORKFLOW = 'publish-agpc-model-components.yml'
FINGERPRINT = 'AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0'
LIMIT = 64 * 1024 * 1024
FLAGS = ('release_admitted', 'native_install_accepted', 'abi_acceptance',
         'runtime_ready', 'signed', 'published')
# New identities, versions and producer jobs require review, not dispatch input.
CORE_FLAGS = ('installation_admitted', 'upgrade_acceptance', 'removal_acceptance',
              'rollback_acceptance', 'release_admitted', 'runtime_ready')
CORE_SOURCES = {
    'packaging/core/build.py', 'packaging/core/README', 'packaging/core/SPEC.md',
    'packaging/core/inputs/published-cohort85.json', 'packaging/core/inputs/agent-sphere.control',
    'src/core_package_contract.py', 'tests/test_core_package.py', '.gitlab-ci.yml',
    'scripts/require-native-runner.py', 'components/agpc-manager/build.py',
    'src/agpc_view_component.py', 'components/agpc-mesh/debian/changelog',
    'components/agpc-cdp/debian/changelog', 'packaging/run/VERSION', 'packaging/vmodel/input.json',
}
CORE_ROOTS = (
    ('agent-sphere', '0.3.0-43'), ('agpc-manager', '4.4.0-3'), ('agpc-view', '0.1.0-4'),
    ('agpc-cdp', '0.2.0-2'), ('agpc-run', '0.2.0-4'), ('agpc-mesh', '3.0.0-6'),
    ('contextd', '0.1.0-27'), ('iagent', '1.0.0-1'), ('agpc-vmodel', '0.1.0~vmodel.20261106.1'),
)
CORE_CANDIDATES = {'agpc-manager': 'components/agpc-manager/build.py',
                   'agpc-view': 'src/agpc_view_component.py',
                   'agpc-mesh': 'components/agpc-mesh/debian/changelog',
                   'agpc-vmodel': 'packaging/vmodel/input.json'}
CORE_FROZEN_PINS = {
    'packaging/core/inputs/published-cohort85.json': {
        'bytes': 17893, 'sha256': 'af8865a8a40720c450e29f961aecdd55f600717e873fb0d2f354e2a78277d9b8'},
    'packaging/core/inputs/agent-sphere.control': {
        'bytes': 959, 'sha256': '468aef045a3039985994a1528f60617f1320a5aed176fd32f4badc6a93ed7847'},
}
CORE_PAYLOAD = {'usr/share/doc/agpc-core/README', 'usr/share/agpc-core/cohort.json',
                'usr/share/doc/agpc-core/PROVENANCE.json'}
COMPONENTS = {
    'core': {
        'product': 'agpc-core', 'project': 1336, 'package': 'agpc-core',
        'version': '0.1.0~core.20261106.1', 'tag': 'agpc-core-v0.1.0-core.20261106.1',
        'public_asset_filename': 'agpc-core_0.1.0.core.20261106.1_amd64.deb',
        'job': 'agpc-core-package', 'prefix': 'packaging/core/dist/',
        'manifest': 'CORE-PACKAGE-MANIFEST.json', 'schema': 'agpc.core.package-build/v1',
        'checks': {'source_binding', 'identity', 'exact_dependencies', 'closed_payload',
                   'root_ownership_modes', 'no_lifecycle_hooks'},
    },
    'vmodel': {
        'product': 'agpc-core', 'project': 1336, 'package': 'agpc-vmodel',
        'version': '0.1.0~vmodel.20261106.1', 'tag': 'agpc-vmodel-v0.1.0-vmodel.20261106.1',
        'public_asset_filename': 'agpc-vmodel_0.1.0.vmodel.20261106.1_amd64.deb',
        'job': 'vmodel-package-native', 'prefix': 'packaging/vmodel/dist/',
        'manifest': 'PUBLICATION-MANIFEST.json', 'schema': 'agpc.core.vmodel-native-package/v1',
        'checks': {'native-package-build-and-readback'},
    },
    'model': {
        'product': 'agpc-model', 'project': 1363, 'package': 'model-llm',
        'version': '0.1.0-5~agpcmodel20261106.1', 'tag': 'agpc-model-v0.1.0-5-agpcmodel20261106.1',
        'public_asset_filename': 'model-llm_0.1.0-5.agpcmodel20261106.1_amd64.deb',
        'job': 'provider-native', 'prefix': 'dist/', 'manifest': 'PROVIDER-MANIFEST.json',
        'schema': 'agpc.model.native-build/v1',
        'checks': {'native-environment', 'source-verification', 'architecture', 'tool-cargo',
                   'tool-rustc', 'tool-cc', 'format', 'contracts', 'management', 'clippy',
                   'release-build', 'elf', 'dynamic-symbols', 'shlibs', 'deb-build',
                   'package-readback', 'probe-version', 'probe-config', 'probe-spec',
                   *{'hook-syntax-' + name for name in ('preinst', 'postinst', 'prerm', 'postrm')}},
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def run(*args, **kwargs):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.PIPE,
                                       timeout=60, **kwargs).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError('publication command failed: ' + args[0]) from None


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        before, after = urllib.parse.urlsplit(request.full_url), urllib.parse.urlsplit(newurl)
        require((before.scheme, before.netloc) == (after.scheme, after.netloc),
                'cross-origin authenticated API redirect refused')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def json_bytes(data):
    require(len(data) <= 4 * 1024 * 1024, 'oversized JSON')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def pin(data):
    return {'bytes': len(data), 'sha256': sha(data)}


def exact_pin(value):
    return (isinstance(value, dict) and set(value) == {'bytes', 'sha256'}
            and type(value['bytes']) is int and 0 < value['bytes'] <= LIMIT
            and isinstance(value['sha256'], str)
            and re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is not None)


def filename(spec):
    return spec['package'] + '_' + spec['version'] + '_amd64.deb'


def public_filename(spec):
    # GitHub normalizes '~' to '.' even when release asset metadata is patched.
    # This reviewed label never changes the original archive name or DEB version.
    expected = filename(spec).replace('~', '.')
    actual = spec.get('public_asset_filename', '')
    require(actual == expected and re.fullmatch(r'[A-Za-z0-9_.+-]+\.deb', actual),
            'unreviewed public asset filename')
    return actual


def source_path(path):
    return (isinstance(path, str) and path and not path.startswith('/')
            and '\\' not in path and '..' not in PurePosixPath(path).parts
            and str(PurePosixPath(path)) == path)


def validate_record(record, component):
    spec = COMPONENTS[component]
    require(set(record) == {'schema', 'component', 'delivery_product', 'tag', 'candidate_tag',
                           'source_project', 'source_commit', 'source_ref', 'pipeline_id',
                           'job_id', 'archive', 'producer_manifest', 'source_inventory_sha256',
                           'assets'}, 'unexpected publication record fields')
    require(record['schema'] == 'agpc.component-publication/v1'
            and record['component'] == component and record['delivery_product'] == spec['product']
            and record['source_project'] == spec['project'] and record['source_ref'] == 'main'
            and record['tag'] == spec['tag'] and record['candidate_tag'] == 'candidate-' + spec['tag'],
            'unreviewed publication identity')
    require(re.fullmatch(r'[0-9a-f]{40}', record['source_commit']) is not None,
            'exact source commit required')
    require(all(type(record[k]) is int and record[k] > 0 for k in ('pipeline_id', 'job_id')),
            'exact producer IDs required')
    require(exact_pin(record['archive']) and exact_pin(record['producer_manifest']),
            'original archive/manifest pins required')
    require(re.fullmatch(r'[0-9a-f]{64}', record['source_inventory_sha256']) is not None,
            'source inventory pin required')
    require(set(record['assets']) == {public_filename(spec), 'MANIFEST.json', 'SHA256SUMS'}
            and all(exact_pin(value) for value in record['assets'].values()),
            'unexpected public asset inventory')


def check_jobs(record, pipeline, job, spec):
    require(pipeline['id'] == record['pipeline_id'] and pipeline['project_id'] == spec['project']
            and pipeline['status'] == 'success' and pipeline['ref'] == 'main'
            and pipeline['sha'] == record['source_commit'], 'successful original main pipeline required')
    require(job['id'] == record['job_id'] and job['name'] == spec['job']
            and job['status'] == 'success' and job['ref'] == 'main'
            and job.get('tag') is False and job.get('allow_failure') is False
            and job['commit']['id'] == record['source_commit']
            and job['pipeline']['id'] == record['pipeline_id']
            and job['pipeline']['project_id'] == spec['project']
            and job['pipeline']['sha'] == record['source_commit']
            and job['pipeline']['ref'] == 'main', 'required successful package job missing')


def archive_files(data, spec):
    require(len(data) <= LIMIT, 'oversized producer archive')
    wanted = {spec['prefix'] + filename(spec), spec['prefix'] + spec['manifest']}
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set()
        for member in archive.infolist():
            path = member.filename.rstrip('/')
            require(source_path(path) and member.filename not in names, 'unsafe or duplicate ZIP member')
            names.add(member.filename)
            require(not stat.S_ISLNK(member.external_attr >> 16), 'symlink in original archive')
            if member.filename in wanted:
                require(0 < member.file_size <= LIMIT, 'oversized producer member')
                result[member.filename] = archive.read(member)
    require(set(result) == wanted, 'original CI package/manifest missing')
    return result[spec['prefix'] + filename(spec)], result[spec['prefix'] + spec['manifest']]


def deb_entries(deb, control=False, metadata_only=False):
    with tempfile.TemporaryDirectory(prefix='agpc-payload-read-') as directory:
        path = Path(directory) / 'package.deb'
        path.write_bytes(deb)
        process = subprocess.Popen(['dpkg-deb', '--ctrl-tarfile' if control else '--fsys-tarfile', str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            raw = process.stdout.read(LIMIT + 1)
            require(len(raw) <= LIMIT, 'oversized package payload')
            require(process.wait(timeout=30) == 0, 'package archive read failed')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
    result = {}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            require(member.uid == member.gid == 0, 'package file owner differs')
            name = member.name.removeprefix('./').rstrip('/')
            if metadata_only:
                name = name or '.'
                require(name not in seen and member.uname in ('', 'root')
                        and member.gname in ('', 'root'), 'Core duplicate member or owner differs')
                seen.add(name)
            if name in ('', '.') and member.isdir():
                require(member.mode == 0o755, 'package directory mode differs')
                if metadata_only:
                    result[name] = (None, member.mode)
                continue
            require(source_path(name), 'unsafe package payload path')
            if member.isdir():
                require(member.mode == 0o755, 'package directory mode differs')
                if metadata_only:
                    result[name] = (None, member.mode)
                continue
            require(member.isfile() and name not in result and member.size <= LIMIT,
                    'non-regular or duplicate package payload')
            if metadata_only:
                require(member.mode == 0o644 and member.size <= 2_000_000,
                        'Core payload must contain only ordinary metadata')
            result[name] = (archive.extractfile(member).read(), member.mode)
    return result


def deb_payload(deb):
    return {name: data for name, (data, _) in deb_entries(deb).items()}


def core_control(cohort):
    depends = ', '.join(f"{row['name']} ({row['relation']} {row['version']})"
                        for row in cohort['dependencies'])
    return (f"Package: agpc-core\nVersion: {cohort['version']}\nArchitecture: amd64\n"
            "Section: metapackages\nPriority: optional\n"
            "Maintainer: Codex AGPC <codex@ypcloud.com>\n"
            f"Depends: {depends}\n"
            "Description: AGPC Core native dependency cohort\n"
            " Composes exact native component versions without copying runtimes.\n"
            " Package installation does not establish admission or AGPC readiness.\n").encode()


def validate_core_cohort(cohort, spec):
    require(set(cohort) == {'schema', 'name', 'version', 'architecture', 'kind', 'installer',
                           'dependencies', 'inherited_agent_sphere_depends',
                           'transitive_cohort_admitted', *CORE_FLAGS},
            'unexpected Core cohort fields')
    require(cohort['schema'] == 'agpc.core.package-cohort/v1'
            and cohort['name'] == spec['package'] and cohort['version'] == spec['version']
            and cohort['architecture'] == 'amd64' and cohort['kind'] == 'dependency-cohort'
            and cohort['installer'] == 'agpc-mesh.sh'
            and cohort['transitive_cohort_admitted'] is False
            and all(cohort[name] is False for name in CORE_FLAGS),
            'Core cohort identity or admission differs')
    rows = cohort['dependencies']
    require(isinstance(rows, list) and len(rows) == len(CORE_ROOTS), 'Core root count differs')
    for row, (name, version) in zip(rows, CORE_ROOTS):
        require(isinstance(row, dict) and set(row) == {'name', 'version', 'relation', 'evidence'}
                and row['name'] == name and row['version'] == version
                and row['relation'] == ('>=' if name == 'agpc-cdp' else '='),
                'Core exact dependency differs')
        evidence = row['evidence']
        if name in CORE_CANDIDATES:
            require(evidence == {'kind': 'source-candidate', 'path': CORE_CANDIDATES[name],
                                 'artifact': None}, 'Core candidate must not claim artifact admission')
        else:
            require(isinstance(evidence, dict) and set(evidence) ==
                    {'kind', 'tag', 'asset', 'sha256', 'source_commit'}
                    and evidence['kind'] == 'frozen-published-reference'
                    and evidence['tag'] == 'agent-computer-v0.3.0-85'
                    and evidence['asset'] == name + '_' + version + '_'
                        + ('all' if name in ('agent-sphere', 'agpc-run') else 'amd64') + '.deb'
                    and re.fullmatch(r'[0-9a-f]{64}', evidence['sha256']) is not None
                    and re.fullmatch(r'[0-9a-f]{40}', evidence['source_commit']) is not None,
                    'Core frozen dependency evidence differs')


def validate_core_producer(data, deb, record, spec):
    require(set(data) == {'schema', 'source', 'producer', 'package', 'cohort', 'checks',
                         'payload', *CORE_FLAGS} and data['schema'] == spec['schema'],
            'unexpected Core producer fields')
    require(data['producer'] == {'kind': 'gitlab-native-ci', 'job_id': record['job_id'],
                'pipeline_id': record['pipeline_id'], 'job_name': spec['job'], 'ref': 'main'},
            'original main Core package producer required')
    source = data['source']
    require(set(source) == {'project', 'commit', 'files'} and source['project'] == 1336
            and source['commit'] == record['source_commit'], 'Core source identity differs')
    files = source['files']
    require(isinstance(files, dict) and set(files) == CORE_SOURCES
            and all(exact_pin(value) for value in files.values())
            and all(files[path] == expected for path, expected in CORE_FROZEN_PINS.items()),
            'Core source closure or frozen evidence differs')
    require(sha(encoded(files)) == record['source_inventory_sha256'], 'Core source inventory differs')
    require(data['package'] == {'name': spec['package'], 'version': spec['version'],
                'architecture': 'amd64', 'filename': filename(spec), **pin(deb)},
            'Core original package identity or bytes differ')
    require(all(data[name] is False for name in CORE_FLAGS), 'Core preview cannot admit lifecycle/runtime')
    require(data['checks'] == {name: True for name in spec['checks']}
            and all(value is True for value in data['checks'].values()), 'Core required checks differ')
    validate_core_cohort(data['cohort'], spec)
    controls = deb_entries(deb, control=True, metadata_only=True)
    require(controls == {'.': (None, 0o755), 'control': (core_control(data['cohort']), 0o644)},
            'Core control content or inventory differs; no hooks or extra relationships allowed')
    entries = deb_entries(deb, metadata_only=True)
    directories = {'.'} | {str(parent) for name in CORE_PAYLOAD for parent in PurePosixPath(name).parents}
    require(set(entries) == CORE_PAYLOAD | directories
            and all(entries[name] == (None, 0o755) for name in directories),
            'Core metadata-only payload inventory differs')
    payload = {name: entries[name][0] for name in CORE_PAYLOAD}
    require(data['payload'] == {name: pin(raw) for name, raw in payload.items()},
            'Core payload pins differ')
    require(payload['usr/share/agpc-core/cohort.json'] == encoded(data['cohort']),
            'Core embedded cohort differs')
    proof = {'schema': 'agpc.core.package-source/v1', 'source': source,
             **{name: False for name in CORE_FLAGS}}
    require(payload['usr/share/doc/agpc-core/PROVENANCE.json'] == encoded(proof),
            'Core embedded provenance differs from original producer')
    require(pin(payload['usr/share/doc/agpc-core/README']) == files['packaging/core/README'],
            'Core README differs from captured source')
    return data


def literal_constants(raw):
    """Inspect source constants without importing or executing producer code."""
    values = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            require(node.targets[0].id not in values, 'duplicate source constant')
            values[node.targets[0].id] = value
    return values


def validate_core_sources(producer, sources):
    """Correlate original CI cohort bytes with independently retrieved source inputs."""
    require(set(sources) == CORE_SOURCES
            and {name: pin(raw) for name, raw in sources.items()} == producer['source']['files'],
            'Core tracked input closure differs')
    values = literal_constants(sources['src/core_package_contract.py'])
    require(values.get('PACKAGE') == 'agpc-core' and values.get('VERSION') == COMPONENTS['core']['version']
            and values.get('ARCHITECTURE') == 'amd64' and values.get('ROOT_DEPENDENCIES') == CORE_ROOTS
            and values.get('DEPENDENCY_RELATIONS') == {'agpc-cdp': '>='},
            'Core tracked dependency contract differs')
    baseline = json_bytes(sources['packaging/core/inputs/published-cohort85.json'])
    require(baseline['release']['tag'] == 'agent-computer-v0.3.0-85', 'Core frozen release differs')
    published = {row['name']: row for row in baseline['release']['packages']}
    manager = re.search(rb'\nVersion: ([^\n]+)', sources['components/agpc-manager/build.py'])
    mesh = re.match(rb'agpc-mesh \(([^)]+)\)', sources['components/agpc-mesh/debian/changelog'])
    vmodel = json_bytes(sources['packaging/vmodel/input.json'])
    require(manager and manager[1].decode() == dict(CORE_ROOTS)['agpc-manager']
            and literal_constants(sources['src/agpc_view_component.py']).get('VERSION')
                == dict(CORE_ROOTS)['agpc-view']
            and mesh and mesh[1].decode() == dict(CORE_ROOTS)['agpc-mesh']
            and vmodel['package'] == 'agpc-vmodel' and vmodel['version'] == dict(CORE_ROOTS)['agpc-vmodel']
            and vmodel['iagent']['version'] == dict(CORE_ROOTS)['iagent']
            and sources['packaging/run/VERSION'].decode().strip() == dict(CORE_ROOTS)['agpc-run']
            and sources['components/agpc-cdp/debian/changelog'].startswith(
                ('agpc-cdp (' + dict(CORE_ROOTS)['agpc-cdp'] + ')').encode()),
            'Core dependency source versions differ')
    for row in producer['cohort']['dependencies']:
        name = row['name']
        if name in CORE_CANDIDATES:
            continue
        original = published[name]
        require(original['version'] == row['version'] and row['evidence'] == {
                    'kind': 'frozen-published-reference', 'tag': 'agent-computer-v0.3.0-85',
                    'asset': original['asset'], 'sha256': original['sha256'],
                    'source_commit': original['provenance']['source_commit']},
                'Core frozen dependency source differs')
    inherited = re.search(rb'^Depends: (.+)$', sources['packaging/core/inputs/agent-sphere.control'], re.M)
    require(inherited and producer['cohort']['inherited_agent_sphere_depends'] == inherited[1].decode(),
            'Core inherited dependency evidence differs')


def validate_producer(raw, deb, record, spec):
    require(pin(raw) == record['producer_manifest'], 'producer manifest differs')
    data = json_bytes(raw)
    if spec['package'] == 'agpc-core':
        return validate_core_producer(data, deb, record, spec)
    require(data['schema'] == spec['schema'] and data['delivery_product'] == spec['product']
            and data['build_kind'] == 'gitlab-native-ci', 'not an original native CI package')
    source = data['source']
    require(source['project'] == spec['project'] and source['commit'] == record['source_commit']
            and source['ref'] == 'main' and source['dirty'] is False, 'producer source mismatch')
    name_key = 'name' if spec['package'] == 'agpc-vmodel' else 'job_name'
    id_value = int if spec['package'] == 'agpc-vmodel' else str
    require(data['producer'] == {'pipeline_id': id_value(record['pipeline_id']), 'job_id': id_value(record['job_id']),
                                 name_key: spec['job']}, 'producer job mismatch')
    files = source['files']
    require(isinstance(files, dict) and files
            and all(source_path(name) and exact_pin(value) for name, value in files.items()),
            'exact source inventory required')
    require(sha(encoded(files)) == record['source_inventory_sha256'], 'source inventory differs')
    require(data['package'] == {'name': spec['package'], 'version': spec['version'], 'architecture': 'amd64',
                               'filename': filename(spec), **pin(deb)}, 'CI package identity or bytes differ')
    require(all(data.get(name) is False for name in FLAGS) and data.get('supported_os') == [],
            'component preview cannot manufacture native/release/runtime admission')
    checks = data['checks']
    require(isinstance(checks, list) and checks and all(isinstance(c, dict) for c in checks),
            'native producer checks missing')
    names = [c.get('name') for c in checks]
    require(all(isinstance(name, str) for name in names) and len(set(names)) == len(names)
            and spec['checks'] <= set(names) and all(type(c.get('exit')) is int and c['exit'] == 0 for c in checks),
            'required producer checks failed or missing')
    if spec['package'] == 'agpc-vmodel':
        payload = {'usr/bin/vmodel': 0o755,
                   'usr/share/doc/agpc-vmodel/consumer-contract.json': 0o644,
                   'usr/share/doc/agpc-vmodel/provenance.json': 0o644}
        controls = {'control': 0o644}
        compiled = compiled_identity(data)
        require(set(data['records']) == {filename(spec), 'BUILD-RECEIPT.json', 'PACKAGE-PLAN.json'}
                and all(exact_pin(value) for value in data['records'].values())
                and data['records'][filename(spec)] == pin(deb)
                and data.get('payload_executed') is False,
                'original compiled input and package build receipt required')
    else:
        environment = next(c for c in checks if c['name'] == 'native-environment')
        require(environment.get('container') is False and environment.get('unprivileged') is True,
                'Provider native build environment is not accepted')
        payload = {'usr/bin/model-llm': 0o755, 'lib/systemd/system/model-llm.service': 0o644,
                   'usr/share/model-llm/model-llm.toml.example': 0o644,
                   **{'usr/share/doc/model-llm/' + name: 0o644 for name in
                      ('README.md', 'SPEC.md', 'copyright', 'provider-provenance.json')}}
        controls = {'control': 0o644, 'md5sums': 0o644,
                    **{name: 0o755 for name in ('preinst', 'postinst', 'prerm', 'postrm')}}
        composition = data['source_composition']
        require(composition['frozen']['project'] == 1317
                and composition['frozen']['commit'] == 'cb579c409e2f0f29b7511976d0fc27d0238c1a1d'
                and composition['overlay']['project'] == 1336
                and re.fullmatch(r'[0-9a-f]{40}', composition['overlay']['commit']) is not None
                and re.fullmatch(r'[0-9a-f]{64}', composition['origin_sha256']) is not None,
                'Provider source composition missing')
    for control, expected in ((False, payload), (True, controls)):
        entries = deb_entries(deb, control)
        require({name: mode for name, (_, mode) in entries.items()} == expected,
                'unreviewed package file inventory or modes')
        if not control and spec['project'] == 1363:
            provenance = json_bytes(entries['usr/share/doc/model-llm/provider-provenance.json'][0])
            require(provenance['schema'] == 'agpc.model.payload-provenance/v1'
                    and provenance['delivery_product'] == spec['product']
                    and provenance['source'] == source and provenance['producer'] == data['producer']
                    and provenance['source_composition'] == data['source_composition']
                    and provenance['native_shlibs'] == data['native_shlibs']
                    and provenance['binary_sha256'] == sha(entries['usr/bin/model-llm'][0])
                    and all(provenance.get(name) is False for name in FLAGS[:4]),
                    'Provider payload provenance differs from original producer')
    # Metadata read only: no DEB maintainer script or runtime payload is executed.
    with tempfile.TemporaryDirectory(prefix='agpc-package-metadata-') as directory:
        path = Path(directory) / filename(spec)
        path.write_bytes(deb)
        for field, expected in [('Package', spec['package']), ('Version', spec['version']),
                                ('Architecture', 'amd64')]:
            require(run('dpkg-deb', '--field', str(path), field) == expected, 'DEB identity mismatch')
    return data


def public_bundle(raw, deb, record, spec):
    data = validate_producer(raw, deb, record, spec)
    manifest = {
        'schema': 'agpc.component-artifact-preview/v1', 'delivery_product': spec['product'],
        'package': data['package'], 'source_project': spec['project'],
        'public_asset_filename': public_filename(spec),
        'source_commit': record['source_commit'], 'source_ref': 'main',
        'pipeline_id': record['pipeline_id'], 'job_id': record['job_id'],
        'original_archive': record['archive'], 'producer_manifest': record['producer_manifest'],
        'source_inventory_sha256': record['source_inventory_sha256'],
        'producer_checks': ([{'name': name, 'exit': 0} for name in sorted(data['checks'])]
                            if spec['package'] == 'agpc-core' else
                            [{'name': c['name'], 'exit': c['exit']} for c in data['checks']]),
        'producer_admission': {name: data[name] for name in
                               (CORE_FLAGS if spec['package'] == 'agpc-core' else FLAGS)},
        'supported_os': [], 'scope': 'source-bound artifact preview; not an installer or AGPC Ready',
    }
    key = ('cohort' if spec['package'] == 'agpc-core' else
           'compiled_input' if spec['package'] == 'agpc-vmodel' else 'source_composition')
    manifest[key + '_sha256'] = sha(encoded(data[key]))
    if spec['package'] == 'agpc-core':
        manifest['cohort'] = data['cohort']
        manifest['package_kind'] = 'metadata-only dependency cohort'
        manifest['transitive_cohort_admitted'] = False
    if spec['package'] == 'agpc-vmodel':
        manifest['compiled_input'] = compiled_identity(data)
        manifest['compiled_input']['source_project'] = 1336
        manifest['compiled_input']['source_ref'] = 'main'
        manifest['packaging_relation'] = (
            'Original compiled main retained independently; native/vmodel inputs must match packaging main. '
            'CI and packaging metadata can differ and are verified at their respective commits.')
    files = {public_filename(spec): deb, 'MANIFEST.json': encoded(manifest)}
    files['SHA256SUMS'] = ''.join(sha(files[name]) + '  ' + name + '\n' for name in sorted(files)).encode()
    return files


def compiled_identity(producer):
    pins = producer['compiled_input']
    require(pins['schema'] == 'agpc.core.vmodel-package-input/v1'
            and pins['owner'] == 'agpc-core' and pins['package'] == 'agpc-vmodel'
            and pins['version'] == COMPONENTS['vmodel']['version'] and pins['architecture'] == 'amd64'
            and re.fullmatch(r'[0-9a-f]{40}', pins['source_commit']) is not None
            and all(isinstance(pins[k], str) and re.fullmatch(r'[1-9][0-9]*', pins[k]) is not None
                    for k in ('pipeline', 'job'))
            and exact_pin({'bytes': pins['archive_bytes'], 'sha256': pins['archive_sha256']})
            and all(re.fullmatch(r'[0-9a-f]{64}', pins[k]) is not None for k in
                    ('manifest_sha256', 'vmodel_sha256', 'library_sha256'))
            and all(pins.get(k) is False for k in
                    ('release_admitted', 'native_install_accepted', 'abi_acceptance', 'runtime_ready')),
            'invalid original compiled input')
    return {'source_commit': pins['source_commit'], 'pipeline_id': int(pins['pipeline']),
            'job_id': int(pins['job']), 'archive': {'bytes': pins['archive_bytes'], 'sha256': pins['archive_sha256']},
            'manifest_sha256': pins['manifest_sha256']}


def verify_packaging_receipts(archive, producer, spec):
    if spec['package'] != 'agpc-vmodel':
        return
    with zipfile.ZipFile(io.BytesIO(archive)) as inputs:
        receipts = {}
        for name in ('BUILD-RECEIPT.json', 'PACKAGE-PLAN.json'):
            path = spec['prefix'] + name
            entry = inputs.getinfo(path)
            require(0 < entry.file_size <= 4 * 1024 * 1024, 'oversized package receipt')
            raw = inputs.read(entry)
            require(pin(raw) == producer['records'][name], 'original package receipt differs')
            receipts[name] = json_bytes(raw)
        receipt = receipts['BUILD-RECEIPT.json']
        require(receipt['schema'] == 'agpc.core.vmodel-nonrelease-build/v1'
                and receipt['compiled_input'] == producer['compiled_input']
                and receipt['filename'] == producer['package']['filename']
                and receipt['sha256'] == producer['package']['sha256']
                and receipt['bytes'] == producer['package']['bytes']
                and all(receipt.get(key) is False for key in (*FLAGS, 'payload_executed', 'maintainer_scripts_executed'))
                and receipt.get('supported_os') == [], 'package build receipt identity/admission differs')
        commands = receipt['commands']
        require(isinstance(commands, list) and len(commands) >= 3
                and all(isinstance(c, dict) and type(c.get('exit')) is int and c['exit'] == 0
                        and isinstance(c.get('command'), list) and c['command'] for c in commands),
                'native package commands failed or missing')
        tools = {Path(c['command'][0]).name for c in commands}
        require({'dpkg', 'dpkg-deb'} <= tools
                and any('dpkg-shlibdeps' in ' '.join(c['command']) for c in commands),
                'native shlibs/build/readback commands missing')


def api_reader(spec):
    origin = urllib.parse.urlsplit(os.environ['AGPC_GITLAB_SOURCE_URL'])
    require(origin.scheme == 'https' and origin.netloc == 'gitlab.ypcloud.com'
            and origin.path == '/codex/codex-agpc/agpc-download-source.git'
            and not origin.query and not origin.fragment
            and not origin.username and not origin.password, 'unreviewed source API origin')
    base = origin.scheme + '://' + origin.netloc + '/api/v4/projects/' + str(spec['project'])
    opener = urllib.request.build_opener(SameOriginRedirect())
    def get(path):
        request = urllib.request.Request(base + path, headers={'PRIVATE-TOKEN': os.environ['AGPC_GITLAB_READ_TOKEN']})
        try:
            with opener.open(request, timeout=60) as response:
                data = response.read(LIMIT + 1)
        except Exception:
            raise RuntimeError('canonical producer API request failed') from None
        require(len(data) <= LIMIT, 'oversized producer response')
        return data
    return get


def fresh_producer(record, spec, get=None):
    get = get or api_reader(spec)
    branch = json_bytes(get('/repository/branches/main'))
    require(branch.get('protected') is True and branch['commit']['id'] == record['source_commit'],
            'source main advanced or is unprotected')
    pipeline = json_bytes(get('/pipelines/' + str(record['pipeline_id'])))
    job = json_bytes(get('/jobs/' + str(record['job_id'])))
    check_jobs(record, pipeline, job, spec)
    archive = get('/jobs/' + str(record['job_id']) + '/artifacts')
    require(pin(archive) == record['archive'], 'original CI archive differs')
    deb, raw = archive_files(archive, spec)
    producer = validate_producer(raw, deb, record, spec)
    verify_packaging_receipts(archive, producer, spec)
    source_blobs = {}
    for path, expected in producer['source']['files'].items():
        blob = get('/repository/files/' + urllib.parse.quote(path, safe='') + '/raw?ref=' + record['source_commit'])
        require(pin(blob) == expected, 'tracked source input differs')
        source_blobs[path] = blob
    if spec['package'] == 'agpc-core':
        validate_core_sources(producer, source_blobs)
    if spec['package'] == 'agpc-vmodel':
        compiled = compiled_identity(producer)
        native = json_bytes(get('/jobs/' + str(compiled['job_id'])))
        compiled_pipeline = json_bytes(get('/pipelines/' + str(compiled['pipeline_id'])))
        compiled_record = {**record, 'job_id': compiled['job_id'], 'pipeline_id': compiled['pipeline_id'],
                           'source_commit': compiled['source_commit']}
        check_jobs(compiled_record, compiled_pipeline, native, {**spec, 'job': 'vmodel-native'})
        raw_archive = get('/jobs/' + str(compiled['job_id']) + '/artifacts')
        require(pin(raw_archive) == compiled['archive'], 'original compiled archive differs')
        with zipfile.ZipFile(io.BytesIO(raw_archive)) as inputs:
            require(len(inputs.namelist()) == len(set(inputs.namelist())), 'duplicate compiled ZIP member')
            for name in ('native/vmodel/dist/MANIFEST.json', 'native/vmodel/dist/vmodel'):
                entry = inputs.getinfo(name)
                require(0 < entry.file_size <= LIMIT and not stat.S_ISLNK(entry.external_attr >> 16),
                        'unsafe compiled artifact')
            manifest = inputs.read('native/vmodel/dist/MANIFEST.json')
            binary = inputs.read('native/vmodel/dist/vmodel')
        require(sha(manifest) == compiled['manifest_sha256'], 'original compiled manifest differs')
        native_manifest = json_bytes(manifest)
        require(native_manifest['schema'] == 'agpc.core.vmodel-artifact/v1'
                and native_manifest['candidate'] == spec['version']
                and native_manifest['source']['project'] == spec['project']
                and native_manifest['source']['commit'] == compiled['source_commit']
                and native_manifest['producer'] == {'CI_JOB_ID': str(compiled['job_id']),
                    'CI_PIPELINE_ID': str(compiled['pipeline_id']), 'ref': 'main'},
                'compiled producer provenance differs')
        native_pin = native_manifest['artifacts']['vmodel']
        require(pin(binary) == {key: native_pin[key] for key in ('bytes', 'sha256')}
                and sha(binary) == producer['compiled_input']['vmodel_sha256']
                and binary == deb_payload(deb)['usr/bin/vmodel'],
                'DEB executable differs from original compiled artifact')
        source_files = native_manifest['source']['files']
        require(isinstance(source_files, dict) and source_files
                and all(source_path(path) and exact_pin(expected) for path, expected in source_files.items()),
                'compiled source closure missing')
        require({k: v for k, v in source_files.items() if k.startswith('native/vmodel/')}
                == {k: v for k, v in producer['source']['files'].items() if k.startswith('native/vmodel/')},
                'compiled runtime inventory differs at packaging main')
        for path, expected in source_files.items():
            blob = get('/repository/files/' + urllib.parse.quote(path, safe='') + '/raw?ref='
                       + compiled['source_commit'])
            require(pin(blob) == expected, 'original compiled source differs')
            if path.startswith('native/vmodel/'):
                current = get('/repository/files/' + urllib.parse.quote(path, safe='') + '/raw?ref='
                              + record['source_commit'])
                require(pin(current) == expected, 'compiled runtime input differs at packaging main')
    return public_bundle(raw, deb, record, spec)


def context():
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPO,
                'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': REPO + '/.github/workflows/' + WORKFLOW + '@refs/heads/main'}
    require(all(os.environ.get(k) == v for k, v in expected.items()), 'unreviewed publisher context')
    require(re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', '')) is not None,
            'exact publisher revision required')


def current_public_main():
    require(json.loads(run('gh', 'api', 'repos/' + REPO + '/branches/main'))['commit']['sha']
            == os.environ['GITHUB_SHA'], 'publisher main advanced')


def absent_release(tag):
    for endpoint in ('releases/tags/' + tag, 'git/ref/tags/' + tag):
        result = subprocess.run(['gh', 'api', 'repos/' + REPO + '/' + endpoint],
                                capture_output=True, text=True, timeout=30)
        require(result.returncode != 0 and 'HTTP 404' in result.stderr, 'release/tag exists or absence unknown')


def publish(component):
    context()
    spec = COMPONENTS[component]
    path = 'scripts/component-publications/' + component + '.json'
    record_bytes = (ROOT / path).read_bytes()
    committed = subprocess.check_output(['git', 'show', os.environ['GITHUB_SHA'] + ':' + path],
                                        cwd=ROOT, stderr=subprocess.DEVNULL, timeout=30)
    require(committed == record_bytes, 'publication input is not committed at publisher revision')
    record = json_bytes(record_bytes)
    validate_record(record, component)
    files = fresh_producer(record, spec)
    require({name: pin(data) for name, data in files.items()} == record['assets'], 'public asset pins differ')
    current_public_main()
    absent_release(spec['tag'])
    with tempfile.TemporaryDirectory(prefix='agpc-component-publication-') as directory:
        stage = Path(directory) / 'bundle'; stage.mkdir()
        for name, data in files.items():
            run('gh', 'release', 'download', record['candidate_tag'], '--repo', REPO,
                '--pattern', name, '--dir', str(stage))
            require((stage / name).is_file() and not (stage / name).is_symlink()
                    and (stage / name).read_bytes() == data, 'staged asset differs from original producer')
        from publish_apt import validate_no_gitlab_urls
        validate_no_gitlab_urls(stage)
        keyhome = Path(directory) / 'gnupg'; keyhome.mkdir(mode=0o700)
        previous = os.environ.get('GNUPGHOME'); os.environ['GNUPGHOME'] = str(keyhome)
        try:
            fingerprint = ''.join((ROOT / 'medge-archive-keyring.fingerprint').read_text().split()).upper()
            require(fingerprint == FINGERPRINT, 'archive fingerprint changed')
            run('gpg', '--batch', '--import', input=os.environ['MEDGE_APT_SIGNING_KEY'])
            from publish_native import sign_files
            sign_files(ROOT, stage, {'MANIFEST.json', 'SHA256SUMS'})
            require(fresh_producer(record, spec) == files, 'producer changed during signing')
            current_public_main()
            absent_release(spec['tag'])
            notes = Path(directory) / 'notes.txt'
            notes.write_text(spec['product'] + ' source-bound component artifact preview.\n'
                'Package identity: ' + spec['package'] + ' ' + spec['version'] + ' (amd64).\n'
                'Verify MANIFEST.json.asc and SHA256SUMS.asc with the established MoteBus archive key.\n'
                'Native installation, ABI/runtime acceptance and AGPC Ready are not admitted. '
                'This release does not activate APT, Pages, Core/Full installers or model routes.\n')
            run('gh', 'release', 'create', spec['tag'], '--repo', REPO, '--target', os.environ['GITHUB_SHA'],
                '--title', spec['product'] + ' artifact preview', '--notes-file', str(notes),
                '--prerelease', '--latest=false', *map(str, sorted(stage.iterdir())))
        finally:
            if previous is None:
                os.environ.pop('GNUPGHOME', None)
            else:
                os.environ['GNUPGHOME'] = previous


def prepare(args):
    spec = COMPONENTS[args.component]
    require(not args.record_output.exists() and not args.bundle_output.exists(),
            'preparation output already exists')
    raw_archive = args.archive.read_bytes()
    deb, raw = archive_files(raw_archive, spec)
    producer = json_bytes(raw)
    pipeline, job = json_bytes(args.pipeline.read_bytes()), json_bytes(args.job.read_bytes())
    record = {'schema': 'agpc.component-publication/v1', 'component': args.component,
              'delivery_product': spec['product'], 'tag': spec['tag'], 'candidate_tag': 'candidate-' + spec['tag'],
              'source_project': spec['project'], 'source_commit': pipeline['sha'], 'source_ref': 'main',
              'pipeline_id': pipeline['id'], 'job_id': job['id'], 'archive': pin(raw_archive),
              'producer_manifest': pin(raw), 'source_inventory_sha256': sha(encoded(producer['source']['files']))}
    check_jobs(record, pipeline, job, spec)
    files = public_bundle(raw, deb, record, spec)
    verify_packaging_receipts(raw_archive, producer, spec)
    record['assets'] = {name: pin(data) for name, data in files.items()}
    validate_record(record, args.component)
    args.bundle_output.mkdir(parents=True)
    for name, data in files.items():
        (args.bundle_output / name).write_bytes(data)
    args.record_output.write_bytes(encoded(record))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('component', choices=COMPONENTS)
    for option in ('archive', 'pipeline', 'job', 'record-output', 'bundle-output'):
        p.add_argument('--' + option, type=Path, required=True)
    p = commands.add_parser('publish')
    p.add_argument('component', choices=COMPONENTS)
    args = parser.parse_args()
    prepare(args) if args.action == 'prepare' else publish(args.component)


if __name__ == '__main__':
    main()
