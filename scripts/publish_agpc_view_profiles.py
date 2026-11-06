#!/usr/bin/env python3
"""Publish original main-CI Core/All assets and their exact aggregate; never install."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

from publish_agpc_view import SameOriginRedirect, encoded, read_json, require, run, sha

ROOT = Path(__file__).resolve().parents[1]
REPO = 'motebus/download'
INSTALLER_TAG = 'v0.3.0-96'
AGGREGATE_TAG = 'agent-computer-v0.3.0-85'
BASELINE_TAG = 'agent-computer-v0.3.0-84'
VIEW_TAG = 'agpc-view-v0.1.0-1'
VIEW_PACKAGE = 'agpc-view_0.1.0-1_amd64.deb'
INPUT_PATH = 'scripts/agpc-view-profile-release-input.json'
RECORD_PATH = ROOT / 'scripts/agpc-view-profile-publication.json'
JOB_NAME = 'agpc-view-profile-release-artifacts'
PREFIX = 'agpc-view-profiles/'
LIMIT = 2 * 1024 * 1024
PROFILES = {'agpc.sh': 'standard', 'agpc-core.sh': 'standard',
            'agpc-all.sh': 'full', 'agpc-apps.sh': 'apps'}
SCRIPTS = set(PROFILES) | {'uninstall.sh'}
FILES = SCRIPTS | {name.replace('.sh', '.source.json') for name in PROFILES} | {
    'agent-computer-apt-overlay.json', 'release-manifest.json',
    'aggregate-component-release.json', 'SHA256SUMS'}
INSTALLER_NOTES = ('Core and All include the native AGPC View GUI. Exact unsigned assets from successful '
                   'protected main CI. Archive signing and native profile acceptance are required before '
                   'Pages deployment; this release does not establish runtime readiness.\n')


def validate_record(record):
    require(set(record) == {'schema', 'installer_tag', 'aggregate_tag', 'source_project', 'source_commit',
                            'source_ref', 'pipeline_id', 'job_id', 'input_sha256', 'assets'},
            'unexpected publication record fields')
    require(record['schema'] == 'agpc-view-profile.publication-inputs/v1'
            and record['installer_tag'] == INSTALLER_TAG and record['aggregate_tag'] == AGGREGATE_TAG
            and record['source_project'] == 1341 and record['source_ref'] == 'main',
            'unreviewed publication identity')
    require(re.fullmatch(r'[0-9a-f]{40}', record['source_commit']) is not None
            and re.fullmatch(r'[0-9a-f]{64}', record['input_sha256']) is not None,
            'exact source and input pins required')
    require(all(type(record[k]) is int and record[k] > 0 for k in ('pipeline_id', 'job_id')),
            'exact successful producer IDs required')
    require(set(record['assets']) == FILES, 'unexpected bundle inventory')
    for name, item in record['assets'].items():
        require(set(item) == {'sha256', 'bytes'} and re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is not None
                and type(item['bytes']) is int and 0 < item['bytes'] <= LIMIT, 'invalid asset pin: ' + name)


def check_jobs(record, pipeline, job):
    require(pipeline['id'] == record['pipeline_id'] and pipeline['project_id'] == 1341
            and pipeline['status'] == 'success' and pipeline['ref'] == 'main'
            and pipeline['sha'] == record['source_commit'], 'canonical main pipeline not successful')
    require(job['id'] == record['job_id'] and job['name'] == JOB_NAME and job['status'] == 'success'
            and job['ref'] == 'main' and job['commit']['id'] == record['source_commit']
            and job['pipeline']['id'] == record['pipeline_id']
            and job['pipeline']['project_id'] == 1341 and job['pipeline']['ref'] == 'main'
            and job['pipeline']['sha'] == record['source_commit'] and job.get('allow_failure') is False,
            'required successful main job missing')


def api_reader():
    source = urllib.parse.urlsplit(os.environ['AGPC_GITLAB_SOURCE_URL'])
    require(source.scheme == 'https' and source.netloc == 'gitlab.ypcloud.com'
            and source.path == '/codex/codex-agpc/agpc-download-source.git'
            and not source.query and not source.fragment, 'unexpected canonical source URL')
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


def fresh_producer(record, get=None):
    validate_record(record)
    get = get or api_reader()
    fresh_identity(record, get)
    inputs = get('/repository/files/' + urllib.parse.quote(INPUT_PATH, safe='')
                 + '/raw?ref=' + record['source_commit'])
    require(sha(inputs) == record['input_sha256'], 'committed producer inputs differ')
    files = {name: get('/jobs/' + str(record['job_id']) + '/artifacts/' + PREFIX + name)
             for name in sorted(FILES)}
    validate_bundle(files, record, inputs)
    return files


def validate_bundle(files, record, inputs):
    validate_record(record)
    require(set(files) == FILES and sha(inputs) == record['input_sha256'], 'bundle/input inventory differs')
    for name, data in files.items():
        require(record['assets'][name] == {'sha256': sha(data), 'bytes': len(data)}, 'CI asset differs: ' + name)
    # Text-only bundle: refuse a private source location in any uploaded byte.
    require(not any(re.search(rb'(?:https?|ssh|git)://[^\s\"\'<>]*gitlab', data, re.I)
                    for data in [*files.values(), inputs]), 'private source URL in public assets')
    expected_sums = ''.join(sha(files[name]) + '  ' + name + '\n' for name in sorted(FILES - {'SHA256SUMS'}))
    require(files['SHA256SUMS'] == expected_sums.encode(), 'checksum inventory mismatch')
    source_input = read_json(inputs)
    require(source_input['schema'] == 'agpc-view-profile-input/v1'
            and source_input['installer_tag'] == INSTALLER_TAG and source_input['aggregate_tag'] == AGGREGATE_TAG
            and source_input['view_release_tag'] == VIEW_TAG, 'producer input identity mismatch')
    package = source_input['view_package']
    require(package['name'] == 'agpc-view' and package['version'] == '0.1.0-1'
            and package['architecture'] == 'amd64' and package['asset'] == VIEW_PACKAGE,
            'unexpected View identity')
    manifest = read_json(files['release-manifest.json'])
    require(manifest == {
        'schema': 'agent-sphere-release/v2', 'version': INSTALLER_TAG[1:],
        'source_commit': record['source_commit'], 'source_ref': 'refs/heads/main',
        'component_baseline': {'pending_native_components': []}, 'installer_profiles': PROFILES,
        'assets': [{'name': name, 'sha256': sha(files[name]), 'bytes': len(files[name])} for name in sorted(SCRIPTS)],
        'aggregate_tag': AGGREGATE_TAG, 'overlay_sha256': sha(files['agent-computer-apt-overlay.json']),
        'view_producer': {'package_job_id': source_input['view_main_job_id'],
                          'gui_job_id': source_input['view_gui_job_id'], 'package': package},
        'native_profile_acceptance': 'required-before-pages-deploy'}, 'release manifest binding mismatch')
    require(files['agpc-core.sh'] == files['agpc.sh'], 'Core alias differs from standard profile')
    for name, profile in PROFILES.items():
        require(read_json(files[name.replace('.sh', '.source.json')]) == {
            'schema': 'agpc-installer-source/v3', 'repository': REPO, 'tag': INSTALLER_TAG,
            'source_commit': record['source_commit'], 'asset': name, 'sha256': sha(files[name]), 'profile': profile},
            'installer source binding mismatch: ' + name)
    overlay = read_json(files['agent-computer-apt-overlay.json'])
    release = overlay['release']
    require(overlay['schema'] == 'agent-computer-apt-overlay/v12' and release['repository'] == REPO
            and release['tag'] == AGGREGATE_TAG and release['source_commit'] == record['source_commit'],
            'overlay source binding mismatch')
    packages = release['packages'] + release.get('retention_packages', [])
    require(len(packages) == 34 and len({p['asset'] for p in packages}) == 34
            and [p for p in packages if p['name'] == 'agpc-view'] == [package], 'aggregate package inventory mismatch')
    assets = [{'name': p['asset'], 'sha256': p['sha256'],
               'source_tag': VIEW_TAG if p['name'] == 'agpc-view' else BASELINE_TAG} for p in packages]
    aggregate = read_json(files['aggregate-component-release.json'])
    require(set(aggregate) == {'schema', 'tag', 'public_source_commit', 'title', 'notes', 'assets'}
            and aggregate['schema'] == 'reviewed-native-publication/v2' and aggregate['tag'] == AGGREGATE_TAG
            and aggregate['public_source_commit'] == 'GITHUB_SHA'
            and aggregate['title'] == 'AGPC native cohort with View GUI'
            and aggregate['notes'] == 'Preserves every prior native package byte and adds the source-bound View GUI. Runtime readiness remains separately verified.'
            and sorted(aggregate['assets'], key=lambda p: p['name']) == sorted(assets, key=lambda p: p['name']),
            'aggregate/overlay binding mismatch')
    for asset in assets:
        require(re.fullmatch(r'[a-z0-9][a-z0-9.+-]*_[A-Za-z0-9.+~:-]+_(?:all|amd64)\.deb', asset['name']) is not None
                and re.fullmatch(r'[0-9a-f]{64}', asset['sha256']) is not None, 'unsafe aggregate asset')
    return aggregate


def context():
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPO, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': REPO + '/.github/workflows/publish-agpc-view-profiles.yml@refs/heads/main'}
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
        + ':scripts/agpc-view-profile-publication.json'], cwd=ROOT, stderr=subprocess.DEVNULL, timeout=30)
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
                'AGPC Core/All with View GUI' if mode == 'installer' else aggregate['title'],
                '--notes-file', str(notes), '--prerelease', '--latest=false',
                *map(str, sorted(stage.iterdir()))], capture_output=True, text=True, timeout=600)
            require(result.returncode == 0, 'release creation failed; inspect existing tag and assets before recovery')
        except subprocess.TimeoutExpired:
            raise RuntimeError('release creation timed out; inspect existing tag and assets before recovery') from None
    print('Published exact reviewed assets: ' + tag)


def prepare(args):
    require(not args.record_output.exists(), 'publication record already exists')
    pipeline, job = [read_json(p.read_bytes()) for p in (args.pipeline, args.job)]
    entries = list(args.bundle.iterdir())
    require({p.name for p in entries} == FILES and all(p.is_file() and not p.is_symlink() for p in entries),
            'unexpected local artifact inventory')
    files = {p.name: p.read_bytes() for p in entries}
    inputs = args.inputs.read_bytes()
    record = {'schema': 'agpc-view-profile.publication-inputs/v1', 'installer_tag': INSTALLER_TAG,
              'aggregate_tag': AGGREGATE_TAG, 'source_project': 1341, 'source_commit': pipeline['sha'],
              'source_ref': 'main', 'pipeline_id': pipeline['id'], 'job_id': job['id'],
              'input_sha256': sha(inputs), 'assets': {name: {'sha256': sha(data), 'bytes': len(data)}
                                                   for name, data in sorted(files.items())}}
    check_jobs(record, pipeline, job)
    validate_bundle(files, record, inputs)
    args.record_output.write_bytes(encoded(record))
    print('Prepared review record; protected publication revalidates original API inputs and artifacts.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    preparation = commands.add_parser('prepare')
    for name in ('bundle', 'pipeline', 'job', 'inputs', 'record-output'):
        preparation.add_argument('--' + name, type=Path, required=True)
    publication = commands.add_parser('publish')
    publication.add_argument('mode', choices=('installer', 'aggregate'))
    args = parser.parse_args()
    prepare(args) if args.action == 'prepare' else publish(args.mode)


if __name__ == '__main__':
    main()
