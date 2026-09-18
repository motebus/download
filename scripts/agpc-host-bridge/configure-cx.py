#!/usr/bin/python3
"""Image-build-only adapter configuration; never rewrites MCHAT identity files."""
import re
import sys
import tomllib
from pathlib import Path

COMMAND = '/usr/local/libexec/agpc/codex-stream.py'


def configure(text):
    original = tomllib.loads(text)
    codex = original['codex']
    if codex.get('backend') != 'app-server' or codex.get('mode') != 'managed':
        raise ValueError('expected managed app-server backend')
    if original['exec']['command'] != '/usr/bin/cx-exec':
        raise ValueError('unexpected CX execution boundary')
    section = re.search(r'(?m)^\[codex\][ \t]*\n(?P<body>(?:(?!^\[).|\n)*)', text)
    if not section:
        raise ValueError('missing canonical codex section')
    body = section['body']
    for key, value in (('command', f'"{COMMAND}"'), ('args', '["app-server"]')):
        body, count = re.subn(rf'(?m)^{key}[ \t]*=.*$', f'{key} = {value}', body)
        if count != 1:
            raise ValueError(f'expected one {key} declaration')
    updated = text[:section.start('body')] + body + text[section.end('body'):]
    expected = dict(original, codex=dict(codex, command=COMMAND, args=['app-server']))
    if tomllib.loads(updated) != expected:
        raise ValueError('configuration changed beyond the Codex adapter')
    return updated


if __name__ == '__main__':
    path = Path(sys.argv[1])
    path.write_text(configure(path.read_text()))
