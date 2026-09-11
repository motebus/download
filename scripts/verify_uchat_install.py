#!/usr/bin/env python3
"""Exercise installed uChat binaries in a disposable AGPC verification container."""
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import subprocess
import tempfile
import time
import uuid


def connect(path):
    end = time.monotonic() + 10
    while True:
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(10)
        try:
            sock.connect(str(path))
            return sock
        except OSError:
            sock.close()
            if time.monotonic() >= end:
                raise
            time.sleep(.05)


class Session:
    def __init__(self, path, address):
        self.sock = connect(path)
        self.reader = self.sock.makefile('rb')
        self.address = address
        self.events = []

    def call(self, op, error=None, **fields):
        request = dict(schema='uchat/v1', request_id=str(uuid.uuid4()),
                       address=self.address, op=op, **fields)
        self.sock.sendall(json.dumps(request).encode() + b'\n')
        while True:
            result = json.loads(self.reader.readline())
            if result['schema'] == 'uchat.event/v1':
                self.events.append(result)
                continue
            assert result['request_id'] == request['request_id'], result
            if error is not None:
                assert not result['ok'] and result['error']['code'] == error, result
            else:
                assert result['ok'], result
            return result

    def message(self, inbox_id):
        while True:
            for index, event in enumerate(self.events):
                if event.get('event') == 'MSG' and event['delivery']['item']['id'] == inbox_id:
                    return self.events.pop(index)['delivery']
            self.events.append(json.loads(self.reader.readline()))

    def close(self):
        self.reader.close()
        self.sock.close()


def main():
    assert Path('/.dockerenv').is_file() and os.getuid() == 0, 'disposable root container required'
    def expired(*_):
        raise TimeoutError('installed uChat smoke check exceeded 60 seconds')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(60)
    print('AGPC verification: starting installed uChat smoke check', flush=True)
    default = json.loads(Path('/etc/uchatd/uchatd.json').read_text())
    assert default['principals'] == [] and default['peers'] == {}
    account = pwd.getpwnam('uchatd')
    assert account.pw_uid != 0
    subprocess.run(['uchatd', 'check-config'], check=True)
    subprocess.run(['uchat', '--version'], check=True)
    subprocess.run(['cx-mesh-network', 'check-config', '--config', '/etc/cx-mesh/network.json'], check=True)
    assert Path('/usr/libexec/uchat/setup-default.py').stat().st_mode & 0o777 == 0o755
    processes, sessions = [], []
    with tempfile.TemporaryDirectory(prefix='agpc-uchat-') as directory:
        root = Path(directory)
        os.chown(root, account.pw_uid, account.pw_gid)
        config = root / 'fixture.json'
        machine = '@' + socket.gethostname().split('.')[0].lower()
        network = root / 'network.json'
        network.write_text(json.dumps(dict(
            schema='cx-mesh.network/v1', mesh_id='fixture', node_id='fixture', registry_node='fixture',
            members={'fixture': dict(machine_name=machine, endpoint='fixture.mote', trust_key_file=None)},
            uchat=dict(enabled=True, name_authority='fixture', chief_node='fixture', conversations=['fixture']))))
        network.chmod(0o644)
        subprocess.run(['cx-mesh-network', 'check-config', '--config', str(network)], check=True)
        config.write_text(json.dumps(dict(
            socket=str(root / 'u.sock'), redis_socket=str(root / 'r.sock'),
            mesh='local', node='local', machine_uid=0, mesh_config=str(network),
            lease_ms=30000, presence_ms=30000,
            principals=[dict(uid=0, addresses=['@human', '@worker'],
                             conversations=['fixture'], send_types=['task', 'result'])],
            groups={}, peers={})))
        config.chmod(0o644)
        prefix = ['setpriv', '--reuid', str(account.pw_uid), '--regid', str(account.pw_gid), '--init-groups']
        with (root / 'process.log').open('wb') as log:
            def start(*command):
                process = subprocess.Popen(prefix + list(command), stdout=log, stderr=log)
                processes.append(process)
                return process
            try:
                start('redis-server', '--port', '0', '--unixsocket', str(root / 'r.sock'),
                      '--unixsocketperm', '600', '--dir', str(root), '--appendonly', 'yes',
                      '--appendfsync', 'always', '--save', '', '--maxmemory-policy', 'noeviction')
                connect(root / 'r.sock').close()
                start('uchatd', 'serve', '--config', str(config))
                human = Session(root / 'u.sock', '@human'); sessions.append(human)
                names = human.call('UNAME_LIST')
                assert names['machine_name'] == machine and names['name_authority'] == 'fixture', names
                assert next(n for n in names['names'] if n['name'] == machine)['protected']
                human.call('UNAME_ADD', name=machine, error='PROTECTED_MACHINE_NAME')
                human.call('UNAME_ADD', name='@chief')
                own = Session(root / 'u.sock', machine); sessions.append(own)
                chief_item = human.call('SEND', to=['@chief'], type='task', conversation_id='fixture',
                                        content={'text': 'independent Inbox fixture'})['inbox_id']
                own.call('GET', inbox_id=chief_item, error='FORBIDDEN')
                assert own.call('LIST')['items'] == []
                sent = human.call('SEND', to=['@worker'], type='task', conversation_id='fixture',
                                  thread_id='fixture-thread', content={'text': 'installation fixture'},
                                  reply_policy={'mode': 'auto'})['inbox_id']
                print('AGPC verification: offline message persisted; restarting uChat and Redis', flush=True)
                # Kill both processes before the offline recipient subscribes.
                for session in sessions:
                    session.close()
                sessions.clear()
                for process in reversed(processes):
                    process.kill(); process.wait(timeout=10)
                processes.clear()
                start('redis-server', '--port', '0', '--unixsocket', str(root / 'r.sock'),
                      '--unixsocketperm', '600', '--dir', str(root), '--appendonly', 'yes',
                      '--appendfsync', 'always', '--save', '', '--maxmemory-policy', 'noeviction')
                connect(root / 'r.sock').close()
                start('uchatd', 'serve', '--config', str(config))
                chief = Session(root / 'u.sock', '@chief'); sessions.append(chief)
                assert chief.call('GET', inbox_id=chief_item)['item']['to'] == ['@chief']
                assert chief.call('REGISTER', agent_id='fixture-chief')['policy'] == 'leader'
                other = Session(root / 'u.sock', '@chief'); sessions.append(other)
                other.call('REGISTER', agent_id='fixture-chief-2', error='CHIEF_ALREADY_ACTIVE')
                chief.call('UNREGISTER')
                assert other.call('REGISTER', agent_id='fixture-chief-2')['leadership_epoch'] == 2
                other.call('UNREGISTER')
                env = dict(os.environ, UCHAT_SOCKET=str(root / 'u.sock'))
                names = json.loads(subprocess.check_output(['uchat', 'uname', '--json'], env=env))
                assert names['active_name'] == machine
                assert '@chief' in [n['name'] for n in names['names']]
                worker = Session(root / 'u.sock', '@worker'); sessions.append(worker)
                worker.call('REGISTER', agent_id='fixture-worker'); worker.call('SUB')
                delivery = worker.message(sent)
                print('AGPC verification: recovered offline delivery; checking automatic reply', flush=True)
                attempt = dict(inbox_id=sent, attempt_id=delivery['attempt_id'])
                worker.call('ACK', **attempt); worker.call('CLAIM', **attempt)
                reply = worker.call('REPLY', **attempt, content={'text': 'fixture completed'})['result_id']
                human = Session(root / 'u.sock', '@human'); sessions.append(human)
                item = human.call('GET', inbox_id=reply)['item']
                assert (item['parent_id'], item['thread_id'], item['content']['text']) == (
                    sent, 'fixture-thread', 'fixture completed')
                assert human.call('GET', inbox_id=sent)['item']['state'] == 'REPLIED'
                print('Installed uChat: shared Mesh profile, protected machine name, independent Inbox, Chief lease, private Redis, crash persistence and auto reply passed')
            except BaseException:
                print((root / 'process.log').read_text())
                raise
            finally:
                for session in sessions:
                    session.close()
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait(timeout=10)


if __name__ == '__main__':
    main()
