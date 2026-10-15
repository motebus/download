"""Offline /opt-preparation checks; all filesystem effects stay in temporary fixtures."""
from contextlib import ExitStack
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_agpc_voice_native_host as host


def owned(info, uid=0, gid=0):
    values = list(info)
    values[4:6] = uid, gid
    return os.stat_result(values)


class NativeHostPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.path = self.base / 'opt'
        self.path.mkdir(mode=0o755)
        self.logs = []
        self.stat = os.stat
        self.fstat = os.fstat
        self.fchmod = os.fchmod
        self.open = os.open
        self.fds = []

    def open_recorded(self, path, flags):
        self.assertTrue(flags & os.O_NOFOLLOW)
        self.assertTrue(flags & os.O_DIRECTORY)
        fd = self.open(path, flags)
        self.fds.append(fd)
        return fd

    def run_prepare(self, **overrides):
        # Real temporary directory operations exercise inode/path races and
        # chmod. Only root identity and xattr observations are fixture inputs.
        mocks = dict(geteuid=lambda: 0,
                     stat=lambda *a, **kw: owned(self.stat(*a, **kw)),
                     fstat=lambda fd: owned(self.fstat(fd)),
                     listxattr=lambda fd: [], open=self.open_recorded)
        mocks.update(overrides)
        with ExitStack() as stack:
            for name, replacement in mocks.items():
                stack.enter_context(patch.object(host.os, name, side_effect=replacement))
            return host.prepare_directory(self.path, emit=self.logs.append)

    def assert_closed(self):
        self.assertTrue(self.fds)
        for fd in self.fds:
            with self.assertRaises(OSError):
                self.fstat(fd)

    def test_tightens_only_directory_and_reports_actual_before_after(self):
        self.path.chmod(0o777)
        other = self.path / 'unrelated'
        other.write_bytes(b'unchanged payload')
        other.chmod(0o640)
        result = self.run_prepare()
        self.assertTrue(result['changed'])
        self.assertEqual(result['before']['mode'], '0777')
        self.assertEqual(result['after']['mode'], '0755')
        self.assertEqual(result['before']['inode'], result['after']['inode'])
        self.assertIs(result['production_admission'], False)
        self.assertTrue(result['agpc_absent'])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(other.stat().st_mode), 0o640)
        self.assertEqual(other.read_bytes(), b'unchanged payload')
        self.assertEqual([r['event'] for r in self.logs], ['before', 'after'])
        self.assertIs(self.logs[-1]['accepted'], True)
        self.assert_closed()

    def test_already_0755_is_idempotent_without_chmod(self):
        with patch.object(host.os, 'fchmod', side_effect=AssertionError('Unneeded chmod')):
            result = self.run_prepare()
        self.assertFalse(result['changed'])
        self.assertEqual(result['before'], result['after'])
        self.assert_closed()

    def test_other_permissions_are_rejected_without_open_or_chmod(self):
        for mode in (0o775, 0o700, 0o1777, 0o2755):
            with self.subTest(mode=oct(mode)):
                self.path.chmod(mode)
                with patch.object(host.os, 'fchmod') as chmod:
                    with self.assertRaisesRegex(host.PreparationError, 'permissions'):
                        self.run_prepare()
                chmod.assert_not_called()
                self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), mode)
        self.assertEqual(self.fds, [])

    def test_nonroot_owner_or_group_is_rejected(self):
        for uid, gid in ((1000, 0), (0, 1000)):
            with self.subTest(uid=uid, gid=gid):
                with self.assertRaisesRegex(host.PreparationError, 'root-owned'):
                    self.run_prepare(stat=lambda *a, **kw: owned(self.stat(*a, **kw), uid, gid))
        self.assertEqual(self.fds, [])

    def test_symlink_and_regular_file_are_rejected(self):
        self.path.rmdir()
        target = self.base / 'other'
        target.mkdir()
        self.path.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(host.PreparationError, 'real root-owned'):
            self.run_prepare()
        self.path.unlink()
        self.path.write_text('not a directory')
        with self.assertRaisesRegex(host.PreparationError, 'real root-owned'):
            self.run_prepare()
        self.assertEqual(self.fds, [])

    def test_acl_and_capability_names_are_rejected_before_chmod(self):
        self.path.chmod(0o777)
        for name in ('system.posix_acl_access', 'system.posix_acl_default',
                     'system.posix_acl_future', 'security.capability'):
            with self.subTest(name=name), patch.object(host.os, 'fchmod') as chmod:
                with self.assertRaisesRegex(host.PreparationError, 'ACL or capability'):
                    self.run_prepare(listxattr=lambda fd: [name])
                chmod.assert_not_called()
                self.assertFalse(self.logs[-1]['accepted'])
        self.assert_closed()

    def test_xattr_observation_failure_refuses_without_chmod(self):
        def unavailable(fd):
            raise OSError('xattr observation unavailable')
        with patch.object(host.os, 'fchmod') as chmod:
            with self.assertRaisesRegex(OSError, 'xattr observation'):
                self.run_prepare(listxattr=unavailable)
            chmod.assert_not_called()
        self.assert_closed()

    def test_existing_agpc_including_dangling_symlink_is_preserved_and_rejected(self):
        self.path.chmod(0o777)
        child = self.path / 'agpc'
        for kind in ('directory', 'file', 'dangling-symlink'):
            with self.subTest(kind=kind):
                if kind == 'directory':
                    child.mkdir()
                elif kind == 'file':
                    child.write_text('preserve')
                else:
                    child.symlink_to(self.base / 'missing')
                with patch.object(host.os, 'fchmod') as chmod:
                    with self.assertRaisesRegex(host.PreparationError, 'agpc path already exists'):
                        self.run_prepare()
                    chmod.assert_not_called()
                self.assertTrue(child.is_symlink() or child.exists())
                self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o777)
                child.rmdir() if kind == 'directory' else child.unlink()

    def test_inode_substitution_between_stat_and_open_is_rejected(self):
        self.path.chmod(0o777)
        displaced = self.base / 'displaced'
        def replace(path, flags):
            self.path.rename(displaced)
            self.path.mkdir()
            self.path.chmod(0o777)
            return self.open_recorded(path, flags)
        with self.assertRaisesRegex(host.PreparationError, 'changed while opening'):
            self.run_prepare(open=replace)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o777)
        self.assertEqual(stat.S_IMODE(displaced.stat().st_mode), 0o777)
        self.assert_closed()

    def test_symlink_substitution_before_open_cannot_follow_target(self):
        displaced = self.base / 'displaced'
        def replace(path, flags):
            self.path.rename(displaced)
            self.path.symlink_to(displaced, target_is_directory=True)
            return self.open_recorded(path, flags)
        with self.assertRaises(OSError):
            self.run_prepare(open=replace)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(self.fds, [])

    def test_child_created_during_tightening_is_rejected_without_removal_or_reopening(self):
        self.path.chmod(0o777)
        child = self.path / 'agpc'
        def create_then_tighten(fd, mode):
            child.mkdir()
            self.fchmod(fd, mode)
        with patch.object(host.os, 'fchmod', side_effect=create_then_tighten):
            with self.assertRaisesRegex(host.PreparationError, 'agpc path already exists'):
                self.run_prepare()
        self.assertTrue(child.is_dir())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o755)
        self.assertTrue(self.logs[-1]['changed'])
        self.assertFalse(self.logs[-1]['accepted'])
        self.assert_closed()

    def test_final_path_replacement_is_rejected(self):
        self.path.chmod(0o777)
        displaced = self.base / 'displaced'
        def replace_after_tightening(fd, mode):
            self.fchmod(fd, mode)
            self.path.rename(displaced)
            self.path.mkdir(mode=0o755)
        with patch.object(host.os, 'fchmod', side_effect=replace_after_tightening):
            with self.assertRaisesRegex(host.PreparationError, 'path identity changed'):
                self.run_prepare()
        self.assertFalse(self.logs[-1]['accepted'])
        self.assert_closed()

    def test_new_acl_after_tightening_is_rejected(self):
        self.path.chmod(0o777)
        observations = iter(([], ['system.posix_acl_access']))
        with self.assertRaisesRegex(host.PreparationError, 'ACL or capability'):
            self.run_prepare(listxattr=lambda fd: next(observations))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o755)
        self.assertFalse(self.logs[-1]['accepted'])
        self.assert_closed()

    def test_failed_chmod_reports_refusal_and_closes_fd(self):
        self.path.chmod(0o777)
        with patch.object(host.os, 'fchmod', side_effect=PermissionError('refused')):
            with self.assertRaises(PermissionError):
                self.run_prepare()
        self.assertEqual(self.logs[-1]['metadata']['mode'], '0777')
        self.assertFalse(self.logs[-1]['accepted'])
        self.assert_closed()


class NativeHostCLITests(unittest.TestCase):
    def test_cli_has_only_fixed_opt_target(self):
        with patch.object(host.os, 'geteuid', return_value=0), \
                patch.object(host.platform, 'freedesktop_os_release',
                             return_value={'ID': 'ubuntu', 'VERSION_ID': '24.04'}), \
                patch.object(host.platform, 'machine', return_value='x86_64'), \
                patch.object(host, 'prepare_directory', return_value={}) as prepare:
            host.main([])
        prepare.assert_called_once_with(Path('/opt'))

    def test_cli_rejects_path_override_before_any_directory_access(self):
        with patch.object(host, 'prepare_directory') as prepare, \
                patch.object(sys, 'stderr', new=io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                host.main(['/tmp/other'])
        self.assertEqual(error.exception.code, 2)
        prepare.assert_not_called()

    def test_environment_strings_cannot_authorize_nonroot_execution(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                                    'GITHUB_REPOSITORY': 'motebus/download',
                                    'GITHUB_REF': 'refs/heads/main'}), \
                patch.object(host.os, 'geteuid', return_value=1000), \
                patch.object(host, 'prepare_directory') as prepare:
            with self.assertRaisesRegex(host.PreparationError, 'Root execution'):
                host.main([])
        prepare.assert_not_called()

    def test_cli_rejects_other_os_version_and_architecture(self):
        for release, arch in (({'ID': 'debian', 'VERSION_ID': '24.04'}, 'x86_64'),
                              ({'ID': 'ubuntu', 'VERSION_ID': '22.04'}, 'x86_64'),
                              ({'ID': 'ubuntu', 'VERSION_ID': '24.04'}, 'aarch64')):
            with self.subTest(release=release, arch=arch), \
                    patch.object(host.os, 'geteuid', return_value=0), \
                    patch.object(host.platform, 'freedesktop_os_release', return_value=release), \
                    patch.object(host.platform, 'machine', return_value=arch), \
                    patch.object(host, 'prepare_directory') as prepare:
                with self.assertRaisesRegex(host.PreparationError, 'Ubuntu 24.04 amd64'):
                    host.main([])
                prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
