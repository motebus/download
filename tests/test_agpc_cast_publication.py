"""Cast preview preservation and archive boundaries; no signing credentials."""
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import publish_agpc_cast as cast
import publish_native as native


class CastPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.site = self.root / 'site'; self.site.mkdir()
        self.bundle = self.root / 'bundle'; self.bundle.mkdir()
        (self.site / 'agpc.sh').write_bytes(b'unchanged Core')
        (self.site / 'agpc-voice.sh').write_bytes(b'unchanged Voice')
        self.record = cast.inputs(ROOT)
        for name in cast.ASSETS:
            (self.bundle / name).write_bytes(name.encode())

    def sign(self, root, site, names):
        for name in names:
            (site / (name + '.asc')).write_bytes(b'fixture signature')

    def overlay(self):
        with patch.object(native, 'sign_files', side_effect=self.sign), patch.object(cast, 'verify_signature'):
            cast.overlay(ROOT, self.site, self.bundle, self.record, {}, 'a' * 40, self.root / 'evidence.json')

    def test_preview_preserves_other_downloads_and_binds_alias(self):
        self.overlay()
        self.assertEqual((self.site / 'agpc.sh').read_bytes(), b'unchanged Core')
        self.assertEqual((self.site / 'agpc-voice.sh').read_bytes(), b'unchanged Voice')
        prefix = self.site / 'agpc-cast' / self.record['version']
        self.assertEqual((self.site / 'agpc-cast.sh').read_bytes(), (prefix / 'agpc-cast.sh').read_bytes())
        receipt = json.loads((self.site / 'agpc-cast.source.json').read_text())
        self.assertFalse(receipt['production_ready'])
        self.assertFalse(receipt['dpkg_registered_by_installer'])
        self.assertEqual(receipt['source']['canonical_runtime_repository'], None)

    def test_versioned_files_cannot_be_replaced(self):
        self.overlay()
        before = native.snapshot(self.site)
        (self.bundle / 'agpc-cast.sh').write_bytes(b'different installer')
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.overlay()
        self.assertEqual(native.snapshot(self.site), before)

    def test_unknown_previous_publication_is_preserved(self):
        (self.site / 'agpc-cast.source.json').write_text('{}')
        before = native.snapshot(self.site)
        with self.assertRaisesRegex(ValueError, 'unrecognized previous'):
            self.overlay()
        self.assertEqual(native.snapshot(self.site), before)

    def test_changed_asset_fails_before_execution(self):
        with self.assertRaisesRegex(ValueError, 'digest/size mismatch'):
            cast.validate_bundle(self.bundle, self.record, test=True)

    def test_source_archive_rejects_escape_and_links(self):
        for name, kind in [('cast-cli-source/../escape.py', tarfile.REGTYPE),
                           ('cast-cli-source/link.py', tarfile.SYMTYPE)]:
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                item = tarfile.TarInfo(name); item.type = kind
                archive.addfile(item)
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                cast.source_files(stream.getvalue())


if __name__ == '__main__':
    unittest.main()
