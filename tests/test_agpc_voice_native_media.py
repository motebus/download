import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import stage_agpc_voice_native_media as media


class MediaInputsTests(unittest.TestCase):
    def archive(self, extra=None, changed_manifest=False):
        files={name:b'# fixture, never executed\n' for name in (
            'tests/test_overall_media_native.py','tests/test_radio_native.py',
            'tests/radio_fixture_child.py','src/agpc_voice/media_decoder.py')}
        if extra:files.update(extra)
        manifest=dict(schema='agpc-voice.native-media-inputs/v1',source_commit='a'*40,version='test',
            files=[dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in files.items()])
        if changed_manifest:manifest['files'][0]['sha256']='b'*64
        files['SOURCE.json']=json.dumps(manifest).encode()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            for name,raw in files.items():archive.writestr(name,raw)
        raw=stream.getvalue()
        return raw,dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),voice_commit='a'*40,version='test')

    def test_verified_fixture_is_not_executed(self):
        raw,record=self.archive()
        self.assertEqual(len(media.unpack(raw,record)),5)

    def test_original_archive_hash_and_length_required(self):
        raw,record=self.archive()
        for change in (dict(sha256='0'*64),dict(bytes=True),dict(bytes=len(raw)+1)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                media.unpack(raw,dict(record,**change))

    def test_unsafe_and_unrelated_members_rejected(self):
        for name in ('../escape','tests/fixtures/radio909/../../escape','scripts/arbitrary.py','src/agpc_voice/x.py/extra'):
            raw,record=self.archive({name:b'bad'})
            with self.subTest(name=name),self.assertRaises(ValueError):media.unpack(raw,record)

    def test_manifest_and_source_identity_must_match(self):
        raw,record=self.archive(changed_manifest=True)
        with self.assertRaises(ValueError):media.unpack(raw,record)
        raw,record=self.archive()
        with self.assertRaises(ValueError):media.unpack(raw,dict(record,voice_commit='b'*40))


if __name__=='__main__':unittest.main()
