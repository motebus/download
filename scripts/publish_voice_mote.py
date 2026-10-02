#!/usr/bin/env python3
"""Sign the Voice-Mote bootstrap without changing any other download."""
import argparse
import json
from pathlib import Path
import re
import subprocess

import publish_native as native

VERSION = '0.1.0-bootstrap.2'
FILES = {'voice-mote.sh', 'voice-mote.source.json', 'VOICE-MOTE-SPEC-v0.1.md', 'VOICE-MOTE-INSTALL.md'}
ALLOWED = FILES | {name + '.asc' for name in FILES}


def overlay(root, site, evidence, base=None):
    before = native.snapshot(site)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    native.require(re.fullmatch(r'[0-9a-f]{40}', commit), 'invalid source commit')
    files = {name: (root / name).read_bytes() for name in FILES - {'voice-mote.source.json'}}
    record = {
        'schema': 'voice-mote.bootstrap-source/v1',
        'version': VERSION,
        'repository': 'https://github.com/motebus/download',
        'source_commit': commit,
        'package': 'voice-mote',
        'scope': 'bootstrap-only',
        'runtime_included': False,
        'voice_mote_ready': False,
        'files': {name: {'sha256': native.digest(data), 'bytes': len(data)} for name, data in sorted(files.items())},
    }
    files['voice-mote.source.json'] = (json.dumps(record, indent=2) + '\n').encode()
    for name, data in files.items():
        (site / name).write_bytes(data)
        (site / name).chmod(0o755 if name.endswith('.sh') else 0o644)
    native.sign_files(root, site, FILES)
    after = native.snapshot(site)
    native.verify_preservation(before, after, ALLOWED)
    evidence.write_text(json.dumps({
        'schema': 'voice-mote.publication-evidence/v1', 'base': base,
        'source': record, 'preserved_files': len(set(before) - ALLOWED),
        'published_sha256': {name: after[name] for name in sorted(ALLOWED)},
    }, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('site', type=Path)
    p.add_argument('--restore', action='store_true')
    p.add_argument('--evidence', type=Path, required=True)
    args = p.parse_args()
    base = native.restore_current(args.site) if args.restore else None
    overlay(args.root, args.site, args.evidence, base)
    if base is not None:
        native.require(native.current_pages() == base, 'Pages deployment changed while staging')


if __name__ == '__main__':
    main()
