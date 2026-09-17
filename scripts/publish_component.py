#!/usr/bin/env python3
"""Publish exact reviewed native package assets through the release environment.

Candidates stay drafts until this job verifies every source-pinned digest.
No build, package install, model invocation or host deployment is performed.
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = 'motebus/download'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def validate(record, tag):
    assert re.fullmatch(r'(cx-mesh|agent-computer)-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]+', tag), 'invalid release tag'
    assert set(record) == {'schema', 'tag', 'public_source_commit', 'title', 'notes', 'assets'}
    assert record['schema'] == 'reviewed-native-publication/v1' and record['tag'] == tag
    assert re.fullmatch(r'[0-9a-f]{40}', record['public_source_commit'])
    assert isinstance(record['assets'], list) and record['assets']
    names = set()
    for item in record['assets']:
        assert set(item) == {'name', 'sha256', 'source_tag'}
        assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', item['name'])
        assert item['name'] not in names and item['name'] != 'release-notes.txt', 'duplicate or reserved asset'
        names.add(item['name'])
        assert re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
        assert re.fullmatch(r'(?:candidate-)?[A-Za-z0-9][A-Za-z0-9_.+-]*', item['source_tag'])
        assert item['source_tag'] != tag, 'self-referential release'
    assert any(name.endswith('.deb') for name in names)


def main(tag):
    assert re.fullmatch(r'(cx-mesh|agent-computer)-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]+', tag)
    record = json.loads((ROOT / 'scripts/component-releases' / (tag + '.json')).read_text())
    validate(record, tag)
    # Publication is serialized and immutable. Never replace a release or tag.
    releases = json.loads(run('gh', 'api', f'repos/{REPO}/releases?per_page=100'))
    assert all(r['tag_name'] != tag for r in releases), 'release already exists'
    ref = subprocess.run(['gh','api',f'repos/{REPO}/git/ref/tags/{tag}'],capture_output=True,text=True)
    assert ref.returncode != 0 and 'HTTP 404' in ref.stderr, 'tag exists or could not verify tag absence'
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        for item in record['assets']:
            run('gh', 'release', 'download', item['source_tag'], '--repo', REPO,
                '--pattern', item['name'], '--dir', temporary)
            path = stage / item['name']
            assert path.is_file() and not path.is_symlink()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], item['name']
        from publish_apt import validate_no_gitlab_urls
        validate_no_gitlab_urls(stage)
        notes = stage / 'release-notes.txt'
        notes.write_text(record['notes'])
        run('gh', 'release', 'create', tag, '--repo', REPO, '--target', record['public_source_commit'],
            '--title', record['title'], '--notes-file', str(notes), '--prerelease', '--latest=false',
            *[str(stage / item['name']) for item in record['assets']])
        print('Published exact reviewed asset bytes: ' + tag)


if __name__ == '__main__':
    main(sys.argv[1])
