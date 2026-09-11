#!/usr/bin/env python3
"""Verify fresh installed MCP/Loop defaults inside the publication container."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import tomllib


def main():
    assert Path('/.dockerenv').is_file() and os.getuid() == 0, 'disposable root container required'
    config = tomllib.loads(Path('/etc/codex/config.toml').read_text())
    server = config['mcp_servers']['mote-mcpd']
    assert server['command'] == '/usr/bin/mote' and server['args'] == ['mcp', 'serve']
    assert server['enabled'] is True
    assert not {'mote-bridge-mcp', 'motemcp'}.intersection(config['mcp_servers'])
    policy = json.loads(Path('/etc/mote-mcpd/provider-policy.json').read_text())
    assert policy['identities'] == [] and policy['grants'] == []
    process = subprocess.Popen([server['command'], *server['args']], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        for ident, method in enumerate(['initialize', 'tools/list'], 1):
            params = {'protocolVersion': '2025-06-18', 'capabilities': {},
                'clientInfo': {'name': 'agpc-install-verification', 'version': '1'}} if ident == 1 else {}
            process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}) + '\n')
            process.stdin.flush()
            assert selector.select(10), 'MCP response timeout'
            response = json.loads(process.stdout.readline())
            assert response['id'] == ident and 'result' in response
            if ident == 1:
                assert response['result']['serverInfo'] == {'name': 'mote-mcpd', 'version': '3.1.0'}
            else:
                names = {tool['name'] for tool in response['result']['tools']}
                assert not any(name.startswith(('s3_', 'ss_', 'comm_')) for name in names)
                manifest = json.loads(Path('/usr/share/mote-mcp/providers/ultra/manifest.json').read_text())
                assert [module['identity'] for module in manifest['modules']] == ['s3', 'ss', 'comm']
                assert Path(manifest['library']).is_file()
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
            raise
        selector.close()
    assert process.returncode == 0
    for name in ['/usr/bin/cx-loop', '/usr/sbin/cx-loopd']:
        assert os.access(name, os.X_OK)
        subprocess.run([name, '--help'], check=True, capture_output=True, timeout=10)
    loop = Path('/etc/cx-loop/config.yaml').read_text()
    assert 'mesh_contract_enabled: false' in loop and 'principals: []' in loop
    assert not list(Path('/etc/systemd/system').glob('*.wants/cx-loopd.service'))
    assert not list(Path('/etc/systemd/system').glob('*.requires/cx-loopd.service'))
    print('Installed MCP: shared Codex registration, 3.1 handshake and installed Ultra manifest passed; ungranted tools hidden')
    print('Installed CX-Loop: CLI/daemon runnable, service disabled, Mesh dispatch unconfigured')


if __name__ == '__main__':
    main()
