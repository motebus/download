#!/usr/bin/env python3
"""Prepare fixed shared directories and the observed disposable Noble log parent.

The reviewed workflow and its root invocation authorize this operation. GitHub
environment strings do not authorize it. This is not a production-host repair
tool. The CLI accepts no target override and preserves all existing children.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import struct
import sys


PREPARATION_TARGETS = ((Path('/opt'), 'agpc'), (Path('/usr/share'), None),
                       (Path('/usr/share/doc'), 'agpc-voice'))
PREPARATION_ANCESTORS = (Path('/'), Path('/usr'), Path('/usr/lib'))
PROTECTED_PATHS = (Path('/opt/agpc'), Path('/usr/lib/agpc-voice'),
                   Path('/usr/share/doc/agpc-voice'))
LOG_PARENT = Path('/var/log')
LOG_ANCESTORS = (Path('/'), Path('/var'))
LOG_PARENT_GID = 102  # Exact observed numeric group; no NSS name or ownership change.
SHARED_ANCESTORS = tuple(Path(name) for name in (
    '/', '/lib', '/lib/systemd', '/lib/systemd/system', '/opt', '/usr',
    '/usr/bin', '/usr/lib', '/usr/sbin', '/usr/share', '/usr/share/doc',
    '/var', '/var/log', '/var/log/dpkg.log', '/var/lib', '/var/lib/dpkg',
    '/var/lib/dpkg/info'))
ACL_NAMES = ('system.posix_acl_access', 'system.posix_acl_default')
ACL_LIMIT = 4096
ACL_UNDEFINED_ID = 0xffffffff


class PreparationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise PreparationError(message)


def metadata(info):
    return dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid,
                gid=info.st_gid, mode=format(stat.S_IMODE(info.st_mode), '04o'),
                directory=stat.S_ISDIR(info.st_mode), symlink=stat.S_ISLNK(info.st_mode))


def identity(info):
    return info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IFMT(info.st_mode)


def trusted_directory(info, allowed_modes):
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_gid == 0,
            'Expected a real root-owned root-group directory')
    require(stat.S_IMODE(info.st_mode) in allowed_modes, 'Unexpected directory permissions')


def acl_entries(raw):
    """Validate the bounded Linux POSIX ACL xattr v2 representation, without NSS."""
    require(type(raw) is bytes and 28 <= len(raw) <= ACL_LIMIT and (len(raw) - 4) % 8 == 0,
            'Malformed or oversized POSIX ACL')
    require(struct.unpack_from('<I', raw)[0] == 2, 'Unsupported POSIX ACL version')
    entries = list(struct.iter_unpack('<HHI', raw[4:]))
    require(all(perm <= 7 for _, perm, _ in entries), 'Invalid POSIX ACL permissions')
    index = 0

    def base(tag):
        nonlocal index
        require(index < len(entries) and entries[index][0] == tag
                and entries[index][2] == ACL_UNDEFINED_ID, 'Invalid POSIX ACL base entry')
        index += 1

    def named(tag):
        nonlocal index
        previous = -1
        while index < len(entries) and entries[index][0] == tag:
            identifier = entries[index][2]
            require(previous < identifier < ACL_UNDEFINED_ID, 'Invalid or duplicate POSIX ACL identifier')
            previous = identifier
            index += 1
        return previous >= 0

    base(1)  # ACL_USER_OBJ
    has_users = named(2)
    base(4)  # ACL_GROUP_OBJ
    has_groups = named(8)
    if index < len(entries) and entries[index][0] == 16:
        base(16)  # ACL_MASK
    else:
        require(not has_users and not has_groups, 'Named POSIX ACL requires a mask')
    base(32)  # ACL_OTHER
    require(index == len(entries), 'Unexpected POSIX ACL entry')
    return entries


def acl_mode(entries):
    permissions = {tag: perm for tag, perm, _ in entries if tag in (1, 4, 16, 32)}
    return (permissions[1] << 6) | (permissions.get(16, permissions[4]) << 3) | permissions[32]


def clamped_access_acl(raw):
    entries = acl_entries(raw)
    has_mask = any(tag == 16 for tag, _, _ in entries)
    permissions = {1: 7, 32: 5, 16 if has_mask else 4: 5}
    return struct.pack('<I', 2) + b''.join(
        struct.pack('<HHI', tag, permissions.get(tag, perm), identifier)
        for tag, perm, identifier in entries)


def observe_xattrs(fd):
    names = set(os.listxattr(fd))
    forbidden = sorted(name for name in names if name not in ACL_NAMES and (
        name.startswith(('system.posix_acl_', 'security.capability'))
        or name.startswith(('system.', 'security.', 'trusted.')) and 'acl' in name.lower()))
    require(not forbidden, 'Unsupported access attribute: ' + json.dumps(forbidden))
    acls = {}
    for name in ACL_NAMES:
        if name in names:
            raw = os.getxattr(fd, name)
            require(len(raw) <= ACL_LIMIT, 'Oversized POSIX ACL: ' + name)
            acls[name] = raw
    require(set(os.listxattr(fd)) == names, 'Attribute names changed during observation')
    return acls, sorted(names - set(ACL_NAMES))


def acl_metadata(acls):
    return {name: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), hex=raw.hex())
            for name, raw in acls.items()}


def no_child(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise PreparationError(name + ' path already exists')


def path_matches(path, expected, allowed_modes):
    current = os.stat(path, follow_symlinks=False)
    trusted_directory(current, allowed_modes)
    require(identity(current) == identity(expected), 'Directory path identity changed')
    return current


def emit_json(record):
    print(json.dumps(record, sort_keys=True), flush=True)


def observe_shared_ancestors(*, emit=emit_json):
    """Read fixed ancestor metadata only; observations never admit or repair it."""
    def typed_metadata(info):
        kind = ('symlink' if stat.S_ISLNK(info.st_mode) else
                'directory' if stat.S_ISDIR(info.st_mode) else
                'regular' if stat.S_ISREG(info.st_mode) else 'other')
        return dict(metadata(info), type=kind, links=info.st_nlink)

    for path in SHARED_ANCESTORS:
        record = dict(schema='agpc.voice-native-shared-ancestor-observation/v1',
                      event='shared-ancestor', path=str(path), errors={})

        def observe(key, reader):
            try:
                record[key] = reader()
            except OSError as error:
                record['errors'][key] = dict(type=type(error).__name__, errno=error.errno)

        observe('lstat', lambda: typed_metadata(os.stat(path, follow_symlinks=False)))
        if record.get('lstat', {}).get('symlink'):
            observe('link_target', lambda: os.readlink(path))
        observe('lstat_xattr_names', lambda: sorted(os.listxattr(path, follow_symlinks=False)))
        # Follow the same fixed path to report the effective target metadata.
        # Read no payload or attribute values and enumerate no child paths.
        observe('resolved', lambda: typed_metadata(os.stat(path, follow_symlinks=True)))
        observe('resolved_xattr_names', lambda: sorted(os.listxattr(path, follow_symlinks=True)))
        emit(record)


def prepare_directory(path, *, protected_name='agpc', guard=None, emit=emit_json):
    """Internal injection is for offline fixtures; prepare_host supplies fixed targets."""
    def check_protected(fd):
        paths = []
        if protected_name is not None:
            no_child(fd, protected_name)
            paths.append(str(path / protected_name))
        if guard is not None:
            paths.extend(guard())
        return sorted(set(paths))

    require(os.geteuid() == 0, 'Root execution required')
    before = os.stat(path, follow_symlinks=False)
    emit(dict(schema='agpc.voice-native-host-preparation/v1', event='before',
              path=str(path), metadata=metadata(before)))
    trusted_directory(before, (0o755, 0o777))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags)
    changed = False
    accepted = False
    mutation_attempted = False
    chmod_completed = False
    original_acls = None
    original_other = None
    removed = []
    absent_after_chmod = []
    try:
        opened = os.fstat(fd)
        trusted_directory(opened, (0o755, 0o777))
        require(identity(opened) == identity(before)
                and opened.st_mode == before.st_mode, 'Directory changed while opening')
        original_acls, original_other = observe_xattrs(fd)
        emit(dict(schema='agpc.voice-native-host-preparation/v1', event='acl-before',
                  path=str(path), acls=acl_metadata(original_acls), other_xattr_names=original_other))
        for name, raw in original_acls.items():
            entries = acl_entries(raw)
            if name == ACL_NAMES[0]:
                require(acl_mode(entries) == stat.S_IMODE(opened.st_mode), 'Access ACL differs from mode')
        check_protected(fd)
        current = path_matches(path, opened, (0o755, 0o777))
        require(current.st_mode == opened.st_mode, 'Directory permissions changed before preparation')
        require(observe_xattrs(fd) == (original_acls, original_other), 'Attributes changed before preparation')
        if stat.S_IMODE(opened.st_mode) == 0o777:
            check_protected(fd)
            mutation_attempted = True
            os.fchmod(fd, 0o755)
            chmod_completed = True
            changed = True
            path_matches(path, opened, (0o755,))
            check_protected(fd)
        # Clamp the access mask before removing named entries. No window with
        # 0777 permissions is introduced by deleting a restrictive named ACL.
        clamped, other = observe_xattrs(fd)
        require(other == original_other, 'Unrelated attribute names changed')
        for name in ACL_NAMES:
            expected = original_acls.get(name)
            if expected is not None and name == ACL_NAMES[0]:
                expected = clamped_access_acl(expected)
                # A mode-equivalent access ACL may collapse into basic mode
                # bits. Never infer an explicit removexattr call from absence.
                if (chmod_completed and name not in clamped
                        and not any(t in (2, 8) for t, _, _ in acl_entries(expected))):
                    absent_after_chmod.append(name)
                    continue
            require(clamped.get(name) == expected, 'ACL changed unexpectedly during chmod')
        clamped_info = os.fstat(fd)
        trusted_directory(clamped_info, (0o755,))
        require(identity(clamped_info) == identity(opened), 'Open directory identity changed')
        path_matches(path, clamped_info, (0o755,))
        check_protected(fd)
        for name in ACL_NAMES:
            if name not in clamped:
                continue
            path_matches(path, clamped_info, (0o755,))
            check_protected(fd)
            require(os.getxattr(fd, name) == clamped[name], 'ACL changed before removal')
            mutation_attempted = True
            os.removexattr(fd, name)
            removed.append(name)
            changed = True
            path_matches(path, clamped_info, (0o755,))
            check_protected(fd)
        after = os.fstat(fd)
        trusted_directory(after, (0o755,))
        require(identity(after) == identity(opened), 'Open directory identity changed')
        after_acls, other = observe_xattrs(fd)
        require(not after_acls, 'POSIX ACL remains or reappeared')
        require(other == original_other, 'Unrelated attribute names changed')
        path_matches(path, after, (0o755,))
        # A child may have been created while the original directory was 0777.
        # Tighten first, then reject any such child without deleting it or
        # reopening permissions. This includes a dangling protected symlink.
        protected_paths = check_protected(fd)
        path_matches(path, after, (0o755,))
        accepted = True
        return dict(schema='agpc.voice-native-host-preparation/v1', path=str(path),
                    before=metadata(before), after=metadata(after), changed=changed,
                    acls_before=acl_metadata(original_acls), removed_acl_names=removed,
                    acl_names_absent_after_chmod=absent_after_chmod, other_xattr_names=other,
                    protected_paths_absent=protected_paths, production_admission=False)
    finally:
        try:
            after_info = os.fstat(fd)
            final = dict(schema='agpc.voice-native-host-preparation/v1', event='after',
                         path=str(path), metadata=metadata(after_info), changed=changed,
                         accepted=accepted, removed_acl_names=list(removed),
                         acl_names_absent_after_chmod=list(absent_after_chmod))
            try:
                if accepted:
                    trusted_directory(after_info, (0o755,))
                    require(identity(after_info) == identity(opened), 'Final directory identity changed')
                    path_matches(path, after_info, (0o755,))
                    final['protected_paths_absent'] = check_protected(fd)
                final_acls, final_other = observe_xattrs(fd)
                final.update(acls=acl_metadata(final_acls), other_xattr_names=final_other)
                if original_acls is not None:
                    final['changed'] = changed or after_info.st_mode != before.st_mode or final_acls != original_acls
                if accepted and (final_acls or final_other != original_other):
                    final['accepted'] = False
                    raise PreparationError('Final attribute observation changed')
            except (OSError, PreparationError) as error:
                final['xattr_observation_error'] = type(error).__name__
                final['changed'] = (True if changed or after_info.st_mode != before.st_mode
                                    else None if mutation_attempted else False)
                if accepted:
                    final['accepted'] = False
                    emit(final)
                    raise PreparationError('Final preparation observation is unobservable or changed') from None
            emit(final)
        finally:
            os.close(fd)


def prepare_log_parent(*, guard, emit=emit_json):
    """Clamp only the fixed observed log parent; never read or modify log contents."""
    require(os.geteuid() == 0, 'Root execution required')
    parent_fd = leaf_fd = None
    before = None
    changed = attempted = accepted = False
    protected_paths = None

    def parent_ok(info, modes):
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                and info.st_gid == LOG_PARENT_GID and stat.S_IMODE(info.st_mode) in modes,
                'Unexpected fixed log parent ownership, type or permissions')

    def leaf_ok(info):
        require(stat.S_ISREG(info.st_mode) and info.st_uid == info.st_gid == 0
                and stat.S_IMODE(info.st_mode) == 0o644 and info.st_nlink == 1,
                'Unexpected fixed dpkg log ownership, type, permissions or links')

    def leaf_identity(info):
        return (*identity(info), info.st_mode, info.st_nlink, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)

    def log_metadata(info):
        return dict(metadata(info), links=info.st_nlink, bytes=info.st_size,
                    mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)

    try:
        ancestry = {}
        for path in LOG_ANCESTORS:
            info = os.stat(path, follow_symlinks=False)
            trusted_directory(info, (0o755,))
            require(not os.listxattr(path, follow_symlinks=False), 'Unexpected log ancestry attributes')
            ancestry[path] = info
        guard()
        before = os.stat(LOG_PARENT, follow_symlinks=False)
        emit(dict(schema='agpc.voice-native-host-preparation/v1', event='log-parent-before',
                  path=str(LOG_PARENT), metadata=metadata(before)))
        parent_ok(before, (0o755, 0o775))
        parent_fd = os.open(LOG_PARENT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        require(identity(os.fstat(parent_fd)) == identity(before), 'Log parent changed while opening')
        leaf_before = os.stat('dpkg.log', dir_fd=parent_fd, follow_symlinks=False)
        leaf_ok(leaf_before)
        leaf_fd = os.open('dpkg.log', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                          dir_fd=parent_fd)
        emit(dict(schema='agpc.voice-native-host-preparation/v1', event='log-leaf-before',
                  path=str(LOG_PARENT / 'dpkg.log'), metadata=log_metadata(leaf_before)))

        def check(modes):
            guard()
            for path, original in ancestry.items():
                path_matches(path, original, (0o755,))
                require(not os.listxattr(path, follow_symlinks=False), 'Unexpected log ancestry attributes')
            current = os.fstat(parent_fd)
            parent_ok(current, modes)
            at_path = os.stat(LOG_PARENT, follow_symlinks=False)
            parent_ok(at_path, modes)
            require(identity(current) == identity(at_path) == identity(before), 'Log parent identity changed')
            require(not os.listxattr(parent_fd), 'Unexpected log parent attributes')
            current_leaf = os.fstat(leaf_fd)
            at_leaf = os.stat('dpkg.log', dir_fd=parent_fd, follow_symlinks=False)
            leaf_ok(current_leaf); leaf_ok(at_leaf)
            require(leaf_identity(current_leaf) == leaf_identity(at_leaf) == leaf_identity(leaf_before),
                    'Dpkg log identity or metadata changed')
            require(not os.listxattr(leaf_fd), 'Unexpected dpkg log attributes')
            return guard()

        check((stat.S_IMODE(before.st_mode),))
        if stat.S_IMODE(before.st_mode) == 0o775:
            attempted = True
            os.fchmod(parent_fd, 0o755)
            changed = True
        protected_paths = check((0o755,))
        accepted = True
        return dict(schema='agpc.voice-native-host-preparation/v1', path=str(LOG_PARENT),
                    before=metadata(before), after=metadata(os.fstat(parent_fd)), changed=changed,
                    protected_paths_absent=protected_paths, production_admission=False)
    finally:
        final = dict(schema='agpc.voice-native-host-preparation/v1', event='log-parent-after',
                     path=str(LOG_PARENT), accepted=accepted, changed=changed,
                     protected_paths_absent=protected_paths if accepted else None,
                     production_admission=False)
        try:
            if parent_fd is not None:
                observed = os.fstat(parent_fd)
                final['metadata'] = metadata(observed)
                final['changed'] = changed or before.st_mode != observed.st_mode
            if leaf_fd is not None:
                final['leaf_metadata'] = log_metadata(os.fstat(leaf_fd))
            if accepted:
                final['protected_paths_absent'] = check((0o755,))
        except (OSError, PreparationError) as error:
            final.update(accepted=False, protected_paths_absent=None,
                         observation_error=type(error).__name__)
            if 'metadata' not in final:
                final['changed'] = True if changed else None if attempted else False
            if accepted:
                raise PreparationError('Final log preparation observation changed or failed') from None
        finally:
            try:
                emit(final)
            finally:
                try:
                    if leaf_fd is not None:
                        os.close(leaf_fd)
                finally:
                    if parent_fd is not None:
                        os.close(parent_fd)


def prepare_host(*, emit=emit_json):
    """Prepare only the fixed parent-before-child sequence; never restore loosened modes."""
    require(os.geteuid() == 0, 'Root execution required')
    snapshots, completed, results = {}, [], []
    active = None
    accepted = False
    protected_paths = None
    targets = {path for path, _ in PREPARATION_TARGETS}

    def guard():
        for path, original in snapshots.items():
            if path == active:
                modes = (stat.S_IMODE(original.st_mode), 0o755)
            elif path in completed:
                modes = (0o755,)
            else:
                modes = (stat.S_IMODE(original.st_mode),)
            path_matches(path, original, modes)
        for path in PROTECTED_PATHS:
            try:
                os.stat(path, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise PreparationError('Protected package path already exists: ' + str(path))
        # Bind the absence observation to unchanged directory identities.
        for path, original in snapshots.items():
            require(identity(os.stat(path, follow_symlinks=False)) == identity(original),
                    'Protected package ancestry changed')
        return list(map(str, PROTECTED_PATHS))

    try:
        for path in (*PREPARATION_ANCESTORS, *(path for path, _ in PREPARATION_TARGETS)):
            info = os.stat(path, follow_symlinks=False)
            trusted_directory(info, (0o755, 0o777) if path in targets else (0o755,))
            snapshots[path] = info
        guard()  # Refuse existing payloads before changing any directory.
        for path, name in PREPARATION_TARGETS:
            active = path
            guard()
            results.append(prepare_directory(path, protected_name=name, guard=guard, emit=emit))
            completed.append(path)
            active = None
            guard()
        results.append(prepare_log_parent(guard=guard, emit=emit))
        completed.append(LOG_PARENT)
        # Earlier directories must still have the exact completed metadata;
        # a later target cannot conceal an ACL or attribute race on its parent.
        for (path, _), result in zip(PREPARATION_TARGETS, results):
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                info = os.fstat(fd)
                trusted_directory(info, (0o755,))
                require(identity(info) == identity(snapshots[path]), 'Completed directory identity changed')
                require(observe_xattrs(fd) == ({}, result['other_xattr_names']),
                        'Completed directory attributes changed')
                path_matches(path, info, (0o755,))
            finally:
                os.close(fd)
        protected_paths = guard()
        accepted = True
        return results
    finally:
        emit(dict(schema='agpc.voice-native-host-preparation/v1', event='host-after',
                  accepted=accepted, completed_paths=list(map(str, completed)),
                  protected_paths_absent=protected_paths, production_admission=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    require(os.geteuid() == 0, 'Root execution required')
    release = platform.freedesktop_os_release()
    require(release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04'
            and platform.machine() == 'x86_64', 'Disposable Ubuntu 24.04 amd64 target required')
    observe_shared_ancestors()
    return prepare_host()


if __name__ == '__main__':
    try:
        main()
    except (PreparationError, OSError, ValueError) as error:
        print('Native host preparation refused: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
