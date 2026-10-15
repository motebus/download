#!/usr/bin/env python3
"""Prepare only /opt in the reviewed disposable Noble Voice CI job.

The reviewed workflow and its root invocation authorize this operation. GitHub
environment strings do not authorize it. This is not a production-host repair
tool. The CLI accepts no target override and never creates /opt/agpc.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import stat
import sys


TARGET = Path('/opt')


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


def no_special_attributes(fd):
    names = os.listxattr(fd)
    require(not any(name.startswith('system.posix_acl_') or name == 'security.capability'
                    for name in names), 'ACL or capability attribute present')


def no_agpc(fd):
    try:
        os.stat('agpc', dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise PreparationError('agpc path already exists')


def path_matches(path, expected, allowed_modes):
    current = os.stat(path, follow_symlinks=False)
    trusted_directory(current, allowed_modes)
    require(identity(current) == identity(expected), 'Directory path identity changed')
    return current


def emit_json(record):
    print(json.dumps(record, sort_keys=True), flush=True)


def prepare_directory(path, *, emit=emit_json):
    """Internal path injection is for offline fixtures; main always supplies /opt."""
    require(os.geteuid() == 0, 'Root execution required')
    before = os.stat(path, follow_symlinks=False)
    emit(dict(schema='agpc.voice-native-host-preparation/v1', event='before',
              path=str(path), metadata=metadata(before)))
    trusted_directory(before, (0o755, 0o777))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags)
    changed = False
    accepted = False
    try:
        opened = os.fstat(fd)
        trusted_directory(opened, (0o755, 0o777))
        require(identity(opened) == identity(before)
                and opened.st_mode == before.st_mode, 'Directory changed while opening')
        no_special_attributes(fd)
        no_agpc(fd)
        current = path_matches(path, opened, (0o755, 0o777))
        require(current.st_mode == opened.st_mode, 'Directory permissions changed before preparation')
        if stat.S_IMODE(opened.st_mode) == 0o777:
            os.fchmod(fd, 0o755)
            changed = True
        after = os.fstat(fd)
        trusted_directory(after, (0o755,))
        require(identity(after) == identity(opened), 'Open directory identity changed')
        no_special_attributes(fd)
        path_matches(path, after, (0o755,))
        # A child may have been created while the original directory was 0777.
        # Tighten first, then reject any such child without deleting it or
        # reopening permissions. This includes a dangling symlink named agpc.
        no_agpc(fd)
        path_matches(path, after, (0o755,))
        accepted = True
        return dict(schema='agpc.voice-native-host-preparation/v1', path=str(path),
                    before=metadata(before), after=metadata(after), changed=changed,
                    agpc_absent=True, production_admission=False)
    finally:
        try:
            emit(dict(schema='agpc.voice-native-host-preparation/v1', event='after',
                      path=str(path), metadata=metadata(os.fstat(fd)), changed=changed,
                      accepted=accepted))
        finally:
            os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    require(os.geteuid() == 0, 'Root execution required')
    release = platform.freedesktop_os_release()
    require(release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04'
            and platform.machine() == 'x86_64', 'Disposable Ubuntu 24.04 amd64 target required')
    return prepare_directory(TARGET)


if __name__ == '__main__':
    try:
        main()
    except (PreparationError, OSError, ValueError) as error:
        print('Native host preparation refused: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
