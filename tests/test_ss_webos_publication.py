import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ss_pub', Path(__file__).resolve().parents[1] / 'scripts/publish_ss_webos.py')
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


class PublicationAdmission(unittest.TestCase):
    def check(self, status='success', ref='main', commit='a' * 40, job_commit=None):
        record = {'source_commit': 'a' * 40, 'pipeline_id': 1, 'job_id': 2}
        pipeline = {'status': status, 'ref': ref, 'sha': commit}
        job = {'status': 'success', 'name': 'ss-webos-native', 'pipeline': {'id': 1}, 'commit': {'id': job_commit or commit}}
        environment = {'AGPC_GITLAB_SOURCE_URL': 'https://private.invalid/group/agpc-download-source.git', 'AGPC_GITLAB_READ_USER': 'reader', 'AGPC_GITLAB_READ_TOKEN': 'test-token', 'GITHUB_SHA': 'b' * 40}
        with patch.dict(os.environ, environment), patch.object(pub, 'run', side_effect=['a' * 40 + '\trefs/heads/main', json.dumps({'commit': {'sha': 'b' * 40}})]), patch.object(pub.urllib.request, 'urlopen', side_effect=[io.StringIO(json.dumps(pipeline)), io.StringIO(json.dumps(job))]), contextlib.redirect_stdout(io.StringIO()):
            pub.fresh_main(record)

    def test_exact_successful_main_native_job_is_admitted(self):
        self.check()

    def test_failed_pipeline_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.check(status='failed')

    def test_branch_artifact_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.check(ref='feature')

    def test_wrong_source_commit_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.check(commit='c' * 40)

    def test_mismatched_job_source_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.check(job_commit='c' * 40)

    def test_command_failure_does_not_disclose_credentials(self):
        failure = subprocess.CalledProcessError(1, ['git', 'secret-token'], stderr='private-url')
        with patch.object(pub.subprocess, 'check_output', side_effect=failure), self.assertRaises(RuntimeError) as result:
            pub.run('git', 'secret-token')
        self.assertEqual(str(result.exception), 'publication command failed: git')


if __name__ == '__main__':
    unittest.main()
