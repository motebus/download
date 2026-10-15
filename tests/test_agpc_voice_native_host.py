"""Offline /opt-preparation checks; all filesystem effects stay in temporary fixtures."""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import stat
import struct
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


def acl(*entries):
    return struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in entries)


UNDEFINED = 0xffffffff
FIXTURE_UID = os.getuid()  # Valid even when the test user namespace maps only this UID.
BASE_ACL = acl((1, 7, UNDEFINED), (4, 5, UNDEFINED), (32, 5, UNDEFINED))
EXTENDED_ACL = acl((1, 7, UNDEFINED), (2, 7, FIXTURE_UID), (4, 5, UNDEFINED),
                   (16, 7, UNDEFINED), (32, 7, UNDEFINED))


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
        self.listxattr = os.listxattr
        self.getxattr = os.getxattr
        self.removexattr = os.removexattr
        self.setxattr = os.setxattr
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
        self.assertEqual([r['event'] for r in self.logs], ['before', 'acl-before', 'after'])
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

    def test_unknown_acl_and_capability_names_are_rejected_before_mutation(self):
        self.path.chmod(0o777)
        for name in ('system.posix_acl_future', 'system.nfs4_acl', 'security.NTACL',
                     'security.capability', 'security.capability_future'):
            with self.subTest(name=name), patch.object(host.os, 'fchmod') as chmod:
                with self.assertRaisesRegex(host.PreparationError, 'Unsupported access attribute'):
                    self.run_prepare(listxattr=lambda fd: [name])
                chmod.assert_not_called()
                self.assertFalse(self.logs[-1]['accepted'])
                self.assertIs(self.logs[-1]['changed'], False)
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
        attributes = {}
        def add_after_tightening(fd, mode):
            self.fchmod(fd, mode)
            attributes[host.ACL_NAMES[0]] = BASE_ACL
        with patch.object(host.os, 'fchmod', side_effect=add_after_tightening):
            with self.assertRaisesRegex(host.PreparationError, 'ACL changed unexpectedly'):
                self.run_prepare(listxattr=lambda fd: list(attributes), getxattr=lambda fd, name: attributes[name])
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

    def install_acl_fixture(self, *, access=True, default=True):
        # Only this test-owned temporary directory receives actual Linux ACLs.
        # Production /opt, system accounts and other host paths are never used.
        if access:
            self.setxattr(self.path, host.ACL_NAMES[0], EXTENDED_ACL)
        if default:
            self.setxattr(self.path, host.ACL_NAMES[1], EXTENDED_ACL)

    def test_actual_linux_access_and_default_acls_are_captured_then_removed(self):
        child = self.path / 'existing'
        child.write_bytes(b'preserved child')
        child.chmod(0o640)
        self.setxattr(self.path, 'user.fixture', b'preserved attribute')
        self.install_acl_fixture()
        calls = []
        def remove_after_clamp(fd, name):
            calls.append(name)
            self.assertIsInstance(fd, int)
            self.assertEqual(stat.S_IMODE(self.fstat(fd).st_mode), 0o755)
            return self.removexattr(fd, name)
        result = self.run_prepare(listxattr=self.listxattr, removexattr=remove_after_clamp)
        self.assertEqual(calls, list(host.ACL_NAMES))
        self.assertEqual(result['removed_acl_names'], calls)
        self.assertEqual(result['acls_before'][host.ACL_NAMES[0]]['hex'], EXTENDED_ACL.hex())
        self.assertEqual(result['acls_before'][host.ACL_NAMES[1]]['hex'], EXTENDED_ACL.hex())
        self.assertEqual(self.logs[1]['acls'], result['acls_before'])
        self.assertEqual(self.listxattr(self.path), ['user.fixture'])
        self.assertEqual(self.getxattr(self.path, 'user.fixture'), b'preserved attribute')
        self.assertEqual(child.read_bytes(), b'preserved child')
        self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o640)
        self.assertEqual(self.listxattr(child), [])
        self.assertEqual(self.logs[-1]['acls'], {})
        self.assertTrue(result['changed'])
        self.assert_closed()

    def test_default_acl_on_0755_is_removed_without_unneeded_chmod(self):
        self.install_acl_fixture(access=False)
        with patch.object(host.os, 'fchmod', side_effect=AssertionError('Mode already clamped')):
            result = self.run_prepare(listxattr=self.listxattr)
        self.assertTrue(result['changed'])
        self.assertEqual(result['removed_acl_names'], [host.ACL_NAMES[1]])
        self.assertEqual(result['before']['mode'], '0755')
        self.assertEqual(result['after']['mode'], '0755')

    def test_malformed_acl_refuses_before_any_mutation(self):
        invalid = [b'', b'\x00' * 28, struct.pack('<I', 3) + BASE_ACL[4:],
                   EXTENDED_ACL[:-1], b'x' * (host.ACL_LIMIT + 1),
                   acl((1, 8, UNDEFINED), (4, 5, UNDEFINED), (32, 5, UNDEFINED)),
                   acl((1, 7, 0), (4, 5, UNDEFINED), (32, 5, UNDEFINED)),
                   acl((1, 7, UNDEFINED), (2, 7, 42), (4, 5, UNDEFINED), (32, 5, UNDEFINED)),
                   acl((1, 7, UNDEFINED), (2, 7, 42), (2, 5, 42), (4, 5, UNDEFINED),
                       (16, 7, UNDEFINED), (32, 5, UNDEFINED)),
                   acl((1, 7, UNDEFINED), (4, 5, UNDEFINED), (64, 5, UNDEFINED))]
        for raw in invalid:
            with self.subTest(raw=raw[:12]), patch.object(host.os, 'fchmod') as chmod, \
                    patch.object(host.os, 'removexattr') as remove:
                with self.assertRaises(host.PreparationError):
                    self.run_prepare(listxattr=lambda fd: [host.ACL_NAMES[0]],
                                     getxattr=lambda fd, name: raw)
                chmod.assert_not_called()
                remove.assert_not_called()
                self.assertIs(self.logs[-1]['changed'], False)

    def test_access_acl_must_match_observed_mode(self):
        with patch.object(host.os, 'fchmod') as chmod, patch.object(host.os, 'removexattr') as remove:
            with self.assertRaisesRegex(host.PreparationError, 'differs from mode'):
                self.run_prepare(listxattr=lambda fd: [host.ACL_NAMES[0]],
                                 getxattr=lambda fd, name: EXTENDED_ACL)
        chmod.assert_not_called()
        remove.assert_not_called()

    def test_partial_removal_reports_retained_default_and_never_restores_permissions(self):
        self.install_acl_fixture()
        def fail_second(fd, name):
            if name == host.ACL_NAMES[1]:
                raise PermissionError('synthetic default ACL removal failure')
            self.removexattr(fd, name)
        with self.assertRaises(PermissionError):
            self.run_prepare(listxattr=self.listxattr, removexattr=fail_second)
        final = self.logs[-1]
        self.assertIs(final['accepted'], False)
        self.assertIs(final['changed'], True)
        self.assertEqual(final['removed_acl_names'], [host.ACL_NAMES[0]])
        self.assertEqual(set(final['acls']), {host.ACL_NAMES[1]})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o755)
        self.assert_closed()

    def test_post_removal_exception_still_reports_observed_change(self):
        self.install_acl_fixture(access=False)
        def remove_then_fail(fd, name):
            self.removexattr(fd, name)
            raise OSError('synthetic failure after syscall')
        with self.assertRaises(OSError):
            self.run_prepare(listxattr=self.listxattr, removexattr=remove_then_fail)
        self.assertIs(self.logs[-1]['changed'], True)
        self.assertFalse(self.logs[-1]['accepted'])
        self.assertEqual(self.logs[-1]['acls'], {})
        self.assertEqual(self.logs[-1]['removed_acl_names'], [])  # No completed Python call claimed.

    def test_unexpected_acl_content_change_during_chmod_is_not_removed(self):
        self.install_acl_fixture()
        changed_acl = acl((1, 7, UNDEFINED), (2, 0, FIXTURE_UID), (4, 5, UNDEFINED),
                          (16, 5, UNDEFINED), (32, 5, UNDEFINED))
        def alter_acl(fd, mode):
            self.fchmod(fd, mode)
            self.setxattr(fd, host.ACL_NAMES[0], changed_acl)
        with patch.object(host.os, 'fchmod', side_effect=alter_acl), \
                patch.object(host.os, 'removexattr') as remove:
            with self.assertRaisesRegex(host.PreparationError, 'ACL changed unexpectedly'):
                self.run_prepare(listxattr=self.listxattr)
        remove.assert_not_called()
        self.assertEqual(self.getxattr(self.path, host.ACL_NAMES[0]), changed_acl)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o755)

    def test_acl_reappearing_after_removal_refuses_without_repeated_removal(self):
        self.install_acl_fixture()
        calls = []
        def remove_and_reintroduce(fd, name):
            calls.append(name)
            self.removexattr(fd, name)
            if name == host.ACL_NAMES[0]:
                self.setxattr(fd, name, host.clamped_access_acl(EXTENDED_ACL))
        with self.assertRaisesRegex(host.PreparationError, 'remains or reappeared'):
            self.run_prepare(listxattr=self.listxattr, removexattr=remove_and_reintroduce)
        self.assertEqual(calls, list(host.ACL_NAMES))
        self.assertIn(host.ACL_NAMES[0], self.listxattr(self.path))
        self.assertFalse(self.logs[-1]['accepted'])

    def test_agpc_created_during_acl_removal_is_preserved_and_refused(self):
        self.install_acl_fixture(access=False)
        def remove_and_create(fd, name):
            self.removexattr(fd, name)
            (self.path / 'agpc').mkdir()
        with self.assertRaisesRegex(host.PreparationError, 'agpc path already exists'):
            self.run_prepare(listxattr=self.listxattr, removexattr=remove_and_create)
        self.assertTrue((self.path / 'agpc').is_dir())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o755)
        self.assertFalse(self.logs[-1]['accepted'])

    def test_unrelated_attribute_name_change_refuses_before_acl_removal(self):
        self.install_acl_fixture()
        def add_attribute(fd, mode):
            self.fchmod(fd, mode)
            self.setxattr(fd, 'user.new-fixture', b'preserve this value')
        with patch.object(host.os, 'fchmod', side_effect=add_attribute), \
                patch.object(host.os, 'removexattr') as remove:
            with self.assertRaisesRegex(host.PreparationError, 'Unrelated attribute names changed'):
                self.run_prepare(listxattr=self.listxattr)
        remove.assert_not_called()
        self.assertEqual(self.getxattr(self.path, 'user.new-fixture'), b'preserve this value')

    def test_missing_attribute_during_capture_refuses_without_mutation(self):
        def missing(fd, name):
            raise OSError('synthetic xattr disappeared')
        with patch.object(host.os, 'fchmod') as chmod, patch.object(host.os, 'removexattr') as remove:
            with self.assertRaises(OSError):
                self.run_prepare(listxattr=lambda fd: [host.ACL_NAMES[1]], getxattr=missing)
        chmod.assert_not_called()
        remove.assert_not_called()
        self.assertIs(self.logs[-1]['changed'], False)


class NativeSharedAncestorObservationTests(unittest.TestCase):
    def test_inventory_is_the_exact_fixed_shared_ancestor_set(self):
        self.assertEqual(tuple(map(str, host.SHARED_ANCESTORS)), (
            '/', '/lib', '/lib/systemd', '/lib/systemd/system', '/opt', '/usr',
            '/usr/bin', '/usr/lib', '/usr/sbin', '/usr/share', '/usr/share/doc'))

    def test_temporary_projection_reports_links_and_target_metadata_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('usr/lib/systemd/system', 'opt', 'usr/bin', 'usr/sbin', 'usr/share/doc'):
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / 'lib').symlink_to('usr/lib', target_is_directory=True)
            (root / 'opt').chmod(0o777)
            (root / 'usr/share').chmod(0o775)
            os.setxattr(root / 'usr/lib', 'user.fixture', b'value must not be read by inventory')
            paths = tuple(root / str(path).lstrip('/') for path in host.SHARED_ANCESTORS)
            before = {path: path.lstat() for path in paths}
            records = []
            with ExitStack() as stack:
                stack.enter_context(patch.object(host, 'SHARED_ANCESTORS', paths))
                for name in ('open', 'getxattr', 'chmod', 'fchmod', 'chown', 'unlink',
                             'removexattr', 'setxattr'):
                    stack.enter_context(patch.object(host.os, name, side_effect=AssertionError(name)))
                host.observe_shared_ancestors(emit=records.append)
            self.assertEqual({path: path.lstat() for path in paths}, before)
            self.assertEqual(os.readlink(root / 'lib'), 'usr/lib')
            self.assertEqual(os.getxattr(root / 'usr/lib', 'user.fixture'),
                             b'value must not be read by inventory')
            self.assertEqual([r['path'] for r in records], list(map(str, paths)))
            by_path = {r['path']: r for r in records}
            link = by_path[str(root / 'lib')]
            self.assertEqual(link['lstat']['type'], 'symlink')
            self.assertEqual(link['link_target'], 'usr/lib')
            self.assertEqual(link['resolved']['type'], 'directory')
            self.assertEqual(link['resolved']['inode'], (root / 'usr/lib').stat().st_ino)
            self.assertEqual(link['resolved_xattr_names'], ['user.fixture'])
            self.assertEqual(link['lstat_xattr_names'], [])
            self.assertEqual(by_path[str(root / 'opt')]['resolved']['mode'], '0777')
            self.assertEqual(by_path[str(root / 'usr/share')]['resolved']['mode'], '0775')
            self.assertTrue(all(not r['errors'] and 'accepted' not in r for r in records))
            self.assertNotIn('value must not be read', json.dumps(records))

    def test_read_errors_are_sanitized_and_do_not_skip_remaining_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / 'broken'
            broken.symlink_to('missing')
            records = []
            real_listxattr = os.listxattr
            def fail_one(path, **kwargs):
                if path == root and not kwargs['follow_symlinks']:
                    raise PermissionError(13, 'do not log arbitrary exception text')
                return real_listxattr(path, **kwargs)
            with patch.object(host, 'SHARED_ANCESTORS', (broken, root)), \
                    patch.object(host.os, 'listxattr', side_effect=fail_one):
                host.observe_shared_ancestors(emit=records.append)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]['link_target'], 'missing')
            self.assertEqual(records[0]['errors']['resolved'],
                             {'type': 'FileNotFoundError', 'errno': 2})
            self.assertEqual(records[1]['errors']['lstat_xattr_names'],
                             {'type': 'PermissionError', 'errno': 13})
            self.assertEqual(records[1]['resolved']['type'], 'directory')
            self.assertNotIn('arbitrary exception text', json.dumps(records))
            self.assertTrue(broken.is_symlink())


class NativeHostCLITests(unittest.TestCase):
    def test_cli_has_only_fixed_opt_target(self):
        order = []
        with patch.object(host.os, 'geteuid', return_value=0), \
                patch.object(host.platform, 'freedesktop_os_release',
                             return_value={'ID': 'ubuntu', 'VERSION_ID': '24.04'}), \
                patch.object(host.platform, 'machine', return_value='x86_64'), \
                patch.object(host, 'observe_shared_ancestors',
                             side_effect=lambda: order.append('observe')) as observe, \
                patch.object(host, 'prepare_directory',
                             side_effect=lambda path: order.append('prepare') or {}) as prepare:
            host.main([])
        observe.assert_called_once_with()
        prepare.assert_called_once_with(Path('/opt'))
        self.assertEqual(order, ['observe', 'prepare'])

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
