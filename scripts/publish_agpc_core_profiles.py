#!/usr/bin/env python3
"""Publish original main-CI Core/All assets and their exact aggregate; never install."""
import argparse
import io
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

from publish_agpc_model_components import SameOriginRedirect, encoded, json_bytes as read_json, require, run, sha
import build_agpc_core_profiles as producer
import publish_apt as apt

ROOT = Path(__file__).resolve().parents[1]
REPO = 'motebus/download'
INSTALLER_TAG = 'v0.3.0-97'
AGGREGATE_TAG = 'agent-computer-v0.3.0-87'
BASELINE_TAG = 'agent-computer-v0.3.0-85'
INPUT_PATH = 'scripts/agpc-core-profile-release-input.json'
RECORD_PATH = ROOT / 'scripts/agpc-core-profile-publication.json'
JOB_NAME = 'agpc-core-profile-release-artifacts'
PREFIX = 'agpc-core-profiles/'
LIMIT = 2 * 1024 * 1024
PROFILES = {'agpc.sh': 'standard', 'agpc-mesh.sh': 'standard',
            'agpc-all.sh': 'full', 'agpc-apps.sh': 'apps'}
SCRIPTS = set(PROFILES) | {'uninstall.sh'}
FILES = SCRIPTS | {name.replace('.sh', '.source.json') for name in PROFILES} | {
    'agent-computer-apt-overlay.json', 'release-manifest.json',
    'aggregate-component-release.json', 'SHA256SUMS'}
INSTALLER_NOTES = ('Mesh and All install the formal AGPC Core composition with vModel and iAgent. '
                   'Exact unsigned assets from successful protected main CI. Archive signing and six native '
                   'profile checks are required before Pages deployment; runtime readiness is separately verified.\n')


def validate_record(record):
    require(set(record) == {'schema', 'installer_tag', 'aggregate_tag', 'source_project', 'source_commit',
                            'source_ref', 'pipeline_id', 'job_id', 'input_sha256', 'archive', 'assets'},
            'unexpected publication record fields')
    require(record['schema'] == 'agpc-core-profile.publication-inputs/v1'
            and record['installer_tag'] == INSTALLER_TAG and record['aggregate_tag'] == AGGREGATE_TAG
            and record['source_project'] == 1341 and record['source_ref'] == 'main',
            'unreviewed publication identity')
    require(re.fullmatch(r'[0-9a-f]{40}', record['source_commit']) is not None
            and re.fullmatch(r'[0-9a-f]{64}', record['input_sha256']) is not None,
            'exact source and input pins required')
    require(all(type(record[k]) is int and record[k] > 0 for k in ('pipeline_id', 'job_id')),
            'exact successful producer IDs required')
    archive = record['archive']
    require(type(archive) is dict and set(archive) == {'bytes', 'sha256'}
            and type(archive['bytes']) is int and 0 < archive['bytes'] <= LIMIT
            and isinstance(archive['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', archive['sha256']) is not None,
            'original archive pin required')
    require(set(record['assets']) == FILES, 'unexpected bundle inventory')
    for name, item in record['assets'].items():
        require(set(item) == {'sha256', 'bytes'} and re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is not None
                and type(item['bytes']) is int and 0 < item['bytes'] <= LIMIT, 'invalid asset pin: ' + name)


def check_jobs(record, pipeline, job):
    require(pipeline['id'] == record['pipeline_id'] and pipeline['project_id'] == 1341
            and pipeline['status'] == 'success' and pipeline['ref'] == 'main'
            and pipeline['sha'] == record['source_commit'], 'canonical main pipeline not successful')
    require(job['id'] == record['job_id'] and job['name'] == JOB_NAME and job['status'] == 'success'
            and job['ref'] == 'main' and job.get('tag') is False
            and job['commit']['id'] == record['source_commit']
            and job['pipeline']['id'] == record['pipeline_id']
            and job['pipeline']['project_id'] == 1341 and job['pipeline']['ref'] == 'main'
            and job['pipeline']['sha'] == record['source_commit'] and job.get('allow_failure') is False,
            'required successful main job missing')


def api_reader():
    source = urllib.parse.urlsplit(os.environ['AGPC_GITLAB_SOURCE_URL'])
    require(source.scheme == 'https' and source.netloc == 'gitlab.ypcloud.com'
            and source.path == '/codex/codex-agpc/agpc-download-source.git'
            and not source.query and not source.fragment and not source.username and not source.password, 'unexpected canonical source URL')
    base = source.scheme + '://' + source.netloc + '/api/v4/projects/1341'
    opener = urllib.request.build_opener(SameOriginRedirect())
    def get(path):
        request = urllib.request.Request(base + path, headers={'PRIVATE-TOKEN': os.environ['AGPC_GITLAB_READ_TOKEN']})
        try:
            with opener.open(request, timeout=30) as response:
                data = response.read(LIMIT + 1)
        except Exception:
            raise RuntimeError('canonical producer API request failed') from None
        require(len(data) <= LIMIT, 'oversized producer response')
        return data
    return get


def fresh_identity(record, get):
    branch = read_json(get('/repository/branches/main'))
    require(branch.get('protected') is True and branch['commit']['id'] == record['source_commit'],
            'source main advanced or is unprotected')
    check_jobs(record, read_json(get('/pipelines/' + str(record['pipeline_id']))),
               read_json(get('/jobs/' + str(record['job_id']))))


def baseline_files(inputs, get):
    value = read_json(inputs)
    commit = value.get('baseline_source_commit')
    require(isinstance(commit, str) and re.fullmatch(r'[a-f0-9]{40}', commit) is not None,
            'exact immutable baseline required')
    pins = value.get('baseline_files')
    require(type(pins) is dict and set(pins) == set(producer.BASELINE_FILES), 'baseline closure differs')
    result = {}
    for name in producer.BASELINE_FILES:
        raw = get('/repository/files/' + urllib.parse.quote(name, safe='') + '/raw?ref=' + commit)
        require(sha(raw) == pins[name], 'original baseline blob differs: ' + name)
        result[name] = raw
    return result


def fresh_producer(record, get=None):
    validate_record(record)
    get = get or api_reader()
    fresh_identity(record, get)
    inputs = get('/repository/files/' + urllib.parse.quote(INPUT_PATH, safe='')
                 + '/raw?ref=' + record['source_commit'])
    require(sha(inputs) == record['input_sha256'], 'committed producer inputs differ')
    baseline = baseline_files(inputs, get)
    archive = get('/jobs/' + str(record['job_id']) + '/artifacts')
    require({'bytes': len(archive), 'sha256': sha(archive)} == record['archive'], 'original CI archive differs')
    files = archive_files(archive)
    validate_bundle(files, record, inputs, baseline)
    return files


def archive_files(raw):
    require(0 < len(raw) <= LIMIT, 'oversized original archive')
    result, seen = {}, set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in archive.infolist():
            require(member.filename not in seen and not stat.S_ISLNK(member.external_attr >> 16),
                    'duplicate or linked original archive member')
            seen.add(member.filename)
            if member.is_dir():
                require(member.filename == PREFIX, 'unreviewed original archive directory')
                continue
            require(member.filename in {PREFIX + name for name in FILES}
                    and 0 < member.file_size <= LIMIT, 'unreviewed original archive member')
            result[member.filename.removeprefix(PREFIX)] = archive.read(member)
    require(set(result) == FILES, 'original archive inventory differs')
    return result


def validate_bundle(files, record, inputs, baseline):
    validate_record(record)
    require(set(files) == FILES and sha(inputs) == record['input_sha256'], 'bundle/input inventory differs')
    for name, data in files.items():
        require(record['assets'][name] == {'sha256': sha(data), 'bytes': len(data)}, 'CI asset differs: ' + name)
    require(not any(re.search(rb'(?:https?|ssh|git)://[^\s\"\'<>]*gitlab', data, re.I)
                    for data in [*files.values(), inputs]), 'private source URL in public assets')
    expected_sums = ''.join(sha(files[name]) + '  ' + name + '\n' for name in sorted(FILES - {'SHA256SUMS'}))
    require(files['SHA256SUMS'] == expected_sums.encode(), 'checksum inventory mismatch')
    source_input = read_json(inputs)
    require(source_input.get('installer_tag') == INSTALLER_TAG and source_input.get('aggregate_tag') == AGGREGATE_TAG,
            'producer input identity mismatch')
    require(set(baseline) == set(producer.BASELINE_FILES), 'baseline closure differs')
    with tempfile.TemporaryDirectory(prefix='agpc-core-baseline-') as directory:
        root = Path(directory)
        for name, data in baseline.items():
            require(sha(data) == source_input['baseline_files'][name], 'original baseline blob differs: ' + name)
            path = root / name
            path.write_bytes(data)
            path.chmod(0o755 if name.endswith(('.sh', '.ps1')) else 0o644)
        previous, config = producer.validate_inputs(root, source_input)
    require(previous['release']['tag'] == BASELINE_TAG, 'baseline cohort differs')
    config['release']['source_commit'] = record['source_commit']
    require(read_json(files['agent-computer-apt-overlay.json']) == config, 'overlay composition/source binding mismatch')
    manifest = read_json(files['release-manifest.json'])
    require(manifest == {
        'schema': 'agent-sphere-release/v2', 'version': INSTALLER_TAG[1:],
        'source_commit': record['source_commit'], 'source_ref': 'refs/heads/main',
        'component_baseline': {'pending_native_components': []}, 'installer_profiles': PROFILES,
        'assets': [{'name': name, 'sha256': sha(files[name]), 'bytes': len(files[name])} for name in sorted(SCRIPTS)],
        'aggregate_tag': AGGREGATE_TAG, 'overlay_sha256': sha(files['agent-computer-apt-overlay.json']),
        'core_producers': source_input['components'], 'baseline_source_commit': source_input['baseline_source_commit'],
        'native_profile_acceptance': 'required-before-pages-deploy'}, 'release manifest binding mismatch')
    require(files['agpc-mesh.sh'] == files['agpc.sh'], 'Mesh entry differs from standard profile')
    for name, profile in PROFILES.items():
        require(read_json(files[name.replace('.sh', '.source.json')]) == {
            'schema': 'agpc-installer-source/v4', 'repository': REPO, 'tag': INSTALLER_TAG,
            'source_commit': record['source_commit'], 'asset': name, 'sha256': sha(files[name]), 'profile': profile},
            'installer source binding mismatch: ' + name)
    source_tags = {row['package']['name']: row['source_tag'] for row in source_input['components']}
    assets = [{'name': p['asset'], 'sha256': p['sha256'], 'source_tag': source_tags.get(p['name'], BASELINE_TAG)}
              for p in apt.overlay_packages(config)]
    aggregate = read_json(files['aggregate-component-release.json'])
    require(aggregate == {
        'schema': 'reviewed-native-publication/v2', 'tag': AGGREGATE_TAG, 'public_source_commit': 'GITHUB_SHA',
        'title': 'AGPC Core composition and Mesh installer',
        'notes': 'Exact native Core composition; package publication does not establish runtime readiness.',
        'assets': assets}, 'aggregate/overlay binding mismatch')
    for asset in assets:
        require(re.fullmatch(r'[a-z0-9][a-z0-9.+-]*_[A-Za-z0-9.+~:-]+_(?:all|amd64)\.deb', asset['name']) is not None
                and re.fullmatch(r'[0-9a-f]{64}', asset['sha256']) is not None, 'unsafe aggregate asset')
    return aggregate


def context():
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPO, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': REPO + '/.github/workflows/publish-agpc-core-profiles.yml@refs/heads/main'}
    require(all(os.environ.get(k) == v for k, v in expected.items()), 'unreviewed publisher context')
    require(re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', '')) is not None, 'exact publisher revision required')


def fresh_public_main():
    require(read_json(run('gh', 'api', f'repos/{REPO}/branches/main').encode())['commit']['sha']
            == os.environ['GITHUB_SHA'], 'publisher main advanced')


def release_info(tag):
    response = subprocess.run(['gh', 'api', f'repos/{REPO}/releases/tags/{tag}'],
                              capture_output=True, text=True, timeout=30)
    if response.returncode == 0:
        return read_json(response.stdout.encode())
    require('HTTP 404' in response.stderr, 'release lookup failed')
    return None


def absent_release(tag):
    require(release_info(tag) is None, 'release already exists; never overwrite')
    response = subprocess.run(['gh', 'api', f'repos/{REPO}/git/ref/tags/{tag}'],
                              capture_output=True, text=True, timeout=30)
    require(response.returncode != 0 and 'HTTP 404' in response.stderr, 'tag exists or absence unknown')


def file_sha(path):
    import hashlib
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download_asset(tag, name, expected, stage):
    run('gh', 'release', 'download', tag, '--repo', REPO, '--pattern', name, '--dir', str(stage))
    path = stage / name
    require(path.is_file() and not path.is_symlink() and file_sha(path) == expected,
            'released asset differs: ' + name)


def verify_counterpart(tag, pins):
    """Permit the missing half after exact readback; never repair an existing release."""
    info = release_info(tag)
    if info is None:
        absent_release(tag)
        return
    require(info['tag_name'] == tag and info['draft'] is False
            and len(info['assets']) == len(pins) and {item['name'] for item in info['assets']} == set(pins),
            'existing counterpart release has unexpected assets')
    with tempfile.TemporaryDirectory(prefix='agpc-profile-existing-') as directory:
        for name, digest in sorted(pins.items()):
            download_asset(tag, name, digest, Path(directory))
    print(encoded({'verified_existing_release': tag, 'sha256': pins}).decode())


def publish(mode):
    context()
    record_bytes = RECORD_PATH.read_bytes()
    committed = subprocess.check_output(['git', 'show', os.environ['GITHUB_SHA']
        + ':scripts/agpc-core-profile-publication.json'], cwd=ROOT, stderr=subprocess.DEVNULL, timeout=30)
    require(committed == record_bytes, 'publication inputs differ from committed source')
    record = read_json(record_bytes)
    files = fresh_producer(record)
    fresh_public_main()
    aggregate = read_json(files['aggregate-component-release.json'])
    installer_pins = {name: item['sha256'] for name, item in record['assets'].items()}
    aggregate_pins = {item['name']: item['sha256'] for item in aggregate['assets']}
    tag = INSTALLER_TAG if mode == 'installer' else AGGREGATE_TAG
    absent_release(tag)
    verify_counterpart(AGGREGATE_TAG if mode == 'installer' else INSTALLER_TAG,
                       aggregate_pins if mode == 'installer' else installer_pins)
    with tempfile.TemporaryDirectory(prefix='agpc-profile-publication-') as directory:
        stage = Path(directory) / 'assets'; stage.mkdir()
        if mode == 'installer':
            for name, data in files.items():
                (stage / name).write_bytes(data)
        else:
            for item in aggregate['assets']:
                download_asset(item['source_tag'], item['name'], item['sha256'], stage)
        from publish_apt import validate_no_gitlab_urls
        validate_no_gitlab_urls(stage)
        fresh_identity(record, api_reader())
        fresh_public_main()
        absent_release(tag)
        notes = Path(directory) / 'notes.txt'
        notes.write_text(INSTALLER_NOTES if mode == 'installer' else aggregate['notes'])
        # Uploading 34 reviewed assets may exceed the normal per-command 60s bound.
        try:
            result = subprocess.run(['gh', 'release', 'create', tag, '--repo', REPO,
                '--target', os.environ['GITHUB_SHA'], '--title',
                'AGPC Mesh and All installers' if mode == 'installer' else aggregate['title'],
                '--notes-file', str(notes), '--prerelease', '--latest=false',
                *map(str, sorted(stage.iterdir()))], capture_output=True, text=True, timeout=600)
            require(result.returncode == 0, 'release creation failed; inspect existing tag and assets before recovery')
        except subprocess.TimeoutExpired:
            raise RuntimeError('release creation timed out; inspect existing tag and assets before recovery') from None
    print('Published exact reviewed assets: ' + tag)


def prepare(args):
    require(not args.record_output.exists(), 'publication record already exists')
    pipeline, job = [read_json(p.read_bytes()) for p in (args.pipeline, args.job)]
    raw_archive = args.archive.read_bytes()
    files = archive_files(raw_archive)
    inputs = args.inputs.read_bytes()
    record = {'schema': 'agpc-core-profile.publication-inputs/v1', 'installer_tag': INSTALLER_TAG,
              'aggregate_tag': AGGREGATE_TAG, 'source_project': 1341, 'source_commit': pipeline['sha'],
              'source_ref': 'main', 'pipeline_id': pipeline['id'], 'job_id': job['id'],
              'input_sha256': sha(inputs), 'archive': {'bytes': len(raw_archive), 'sha256': sha(raw_archive)},
              'assets': {name: {'sha256': sha(data), 'bytes': len(data)}
                                                   for name, data in sorted(files.items())}}
    check_jobs(record, pipeline, job)
    baseline = {name: subprocess.check_output(['git', 'show', read_json(inputs)['baseline_source_commit'] + ':' + name], cwd=args.baseline_root) for name in producer.BASELINE_FILES}
    validate_bundle(files, record, inputs, baseline)
    args.record_output.write_bytes(encoded(record))
    print('Prepared review record; protected publication revalidates original API inputs and artifacts.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    preparation = commands.add_parser('prepare')
    for name in ('archive', 'pipeline', 'job', 'inputs', 'record-output', 'baseline-root'):
        preparation.add_argument('--' + name, type=Path, required=True)
    publication = commands.add_parser('publish')
    publication.add_argument('mode', choices=('installer', 'aggregate'))
    args = parser.parse_args()
    prepare(args) if args.action == 'prepare' else publish(args.mode)


if __name__ == '__main__':
    main()
