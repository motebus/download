"""Publisher input bounds for the reviewed callback999 Debian version; no I/O."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_agpc_voice as voice

class VoiceVersionLengthTests(unittest.TestCase):
    def record(self, version):
        return dict(schema='agpc.voice-publication-inputs/v1', version=version,
            source_commit='a'*40, ci_job=1, archive_sha256='b'*64, archive_bytes=1,
            install_review=97, disclosure_review=dict(project=1341, iid=97))

    def test_reviewed_zhtw_version_is_accepted(self):
        version='0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1'
        self.assertEqual(len(version), 84)
        self.assertEqual(voice.validate_inputs(self.record(version))['version'], version)

    def test_version_remains_bounded(self):
        version='0.1.0+'+'x'*104
        self.assertEqual(len(version), 110)
        self.assertEqual(voice.validate_inputs(self.record(version))['version'], version)
        with self.assertRaisesRegex(ValueError, 'invalid Voice version'):
            voice.validate_inputs(self.record(version+'x'))

    def test_reviewed_callback999_version_is_accepted(self):
        version='0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1+callback999.1'
        self.assertEqual(len(version), 110)
        self.assertEqual(voice.validate_inputs(self.record(version))['version'], version)

    def test_path_and_control_characters_remain_rejected(self):
        for suffix in ('/x', '\\x', '%2fx', '..', ' x', '\n', '?x', '#x', '\x00'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'invalid Voice version'):
                voice.validate_inputs(self.record('0.1.0'+suffix))

if __name__ == '__main__': unittest.main()
