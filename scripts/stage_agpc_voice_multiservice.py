#!/usr/bin/env python3
"""Stage the reviewed original main multiservice fixture bundle without executing it."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import zipfile

import publish_agpc_voice as voice

require = voice.native.require
LIMIT = 5 * 1024 * 1024


def unpack(raw, record):
    require(type(record['bytes']) is int and 0 < record['bytes'] <= LIMIT
            and len(raw) == record['bytes']
            and hashlib.sha256(raw).hexdigest() == record['sha256'], 'Multiservice archive differs')
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(len(archive.infolist()) <= 100, 'Multiservice archive inventory exceeds limit')
        total = 0
        for entry in archive.infolist():
            name, mode = entry.filename, entry.external_attr >> 16
            allowed = name == 'SOURCE.json' or re.fullmatch(
                r'src/agpc_voice/[a-z_][a-z0-9_]*\.py|tests/test_(?:multiservice_config|multiservice_dots|multiservice_operations|multiservice_route|radio_binding|rtpengine_13_observation|time_agent_binding|time_binding|time_runtime|transport|utilities|utility_maintenance)\.py|tests/fixtures/(?:multiservice-owned-segments|rtpengine-13-interfaces)\.json', name)
            require(allowed and name not in files and not entry.flag_bits & 1
                    and stat.S_IFMT(mode) in (0, stat.S_IFREG) and not entry.is_dir(), 'Unsafe multiservice member')
            total += entry.file_size
            require(0 < entry.file_size <= LIMIT and total <= LIMIT, 'Multiservice expansion exceeds limit')
            files[name] = archive.read(entry)
    require('SOURCE.json' in files, 'Multiservice manifest missing')
    manifest = voice.load_json(files['SOURCE.json'])
    require(set(manifest) == {'schema', 'source_commit', 'version', 'files'}
            and manifest['schema'] == 'agpc-voice.multiservice-native-inputs/v1'
            and manifest['source_commit'] == record['voice_commit']
            and manifest['version'] == record['version'], 'Multiservice source identity differs')
    rows = manifest['files']
    require(isinstance(rows, list) and len(rows) == len(files) - 1
            and all(isinstance(r, dict) and set(r) == {'path', 'bytes', 'sha256'} for r in rows)
            and {r['path'] for r in rows} == set(files) - {'SOURCE.json'}, 'Multiservice file inventory differs')
    for row in rows:
        data = files[row['path']]
        require(type(row['bytes']) is int and row['bytes'] == len(data)
                and row['sha256'] == hashlib.sha256(data).hexdigest(), 'Multiservice file bytes differ')
    require({'tests/test_multiservice_operations.py','tests/test_multiservice_route.py',
             'tests/test_utility_maintenance.py','tests/fixtures/multiservice-owned-segments.json',
             'src/agpc_voice/multiservice_operations.py'} <= set(files), 'Required multiservice inputs missing')
    return files


def stage(record, output, get_json=voice.api_json, get_bytes=voice.api_bytes):
    require(set(record) == {'schema', 'voice_commit', 'voice_job', 'voice_pipeline',
                           'voice_review', 'reviewed_head', 'version', 'bytes', 'sha256'}
            and record['schema'] == 'agpc-voice.multiservice-native-public-inputs/v1'
            and re.fullmatch('[a-f0-9]{40}', record['voice_commit'])
            and re.fullmatch('[a-f0-9]{40}', record['reviewed_head'])
            and re.fullmatch('[a-f0-9]{64}', record['sha256'])
            and all(type(record[k]) is int and record[k] > 0 for k in ('voice_job', 'voice_pipeline', 'voice_review')),
            'Exact multiservice source pins required')
    observations = {}
    def observed(path):
        result = get_json(path); observations[path] = result; return result
    voice.verify_job(1348, record['voice_job'], record['voice_commit'], observed)
    job = observations[f"projects/1348/jobs/{record['voice_job']}"]
    require(job['name'] == 'voice-source-cohort' and job['pipeline']['id'] == record['voice_pipeline'], 'Multiservice producer differs')
    voice.verify_review(record['voice_review'], 1348, record['voice_commit'], observed)
    review = observations[f"projects/1348/merge_requests/{record['voice_review']}"]
    require(review['sha'] == record['reviewed_head'] and review.get('squash_commit_sha') is None, 'Reviewed multiservice head differs')
    raw = get_bytes(f"projects/1348/jobs/{record['voice_job']}/artifacts/components/agpc-voice/dist/multiservice-native-inputs.zip")
    files = unpack(raw, record)
    require(not output.exists() and not output.is_symlink()
            and not any(p.is_symlink() for p in output.parents), 'Multiservice output already exists or is unsafe')
    output.mkdir(parents=True)
    for name, data in files.items():
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data); path.chmod(0o644)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    stage(voice.load_json(args.inputs.read_bytes()), args.output)
