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

    def call(self, op, **fields):
        request = dict(schema='uchat/v1', request_id=str(uuid.uuid4()),
                       address=self.address, op=op, **fields)
        self.sock.sendall(json.dumps(request).encode() + b'\n')
        while True:
            result = json.loads(self.reader.readline())
            if result['schema'] == 'uchat.event/v1':
                self.events.append(result)
                continue
            assert result['request_id'] == request['request_id'] and result['ok'], result
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
    processes, sessions = [], []
    with tempfile.TemporaryDirectory(prefix='agpc-uchat-') as directory:
        root = Path(directory)
        os.chown(root, account.pw_uid, account.pw_gid)
        config = root / 'fixture.json'
        config.write_text(json.dumps(dict(
            socket=str(root / 'u.sock'), redis_socket=str(root / 'r.sock'),
            mesh='fixture', node='fixture', lease_ms=30000, presence_ms=30000,
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
                sent = human.call('SEND', to=['@worker'], type='task', conversation_id='fixture',
                                  thread_id='fixture-thread', content={'text': 'installation fixture'},
                                  reply_policy={'mode': 'auto'})['inbox_id']
                print('AGPC verification: offline message persisted; restarting uChat and Redis', flush=True)
                # Kill both processes before the offline recipient subscribes.
                human.close(); sessions.clear()
                for process in reversed(processes):
                    process.kill(); process.wait(timeout=10)
                processes.clear()
                start('redis-server', '--port', '0', '--unixsocket', str(root / 'r.sock'),
                      '--unixsocketperm', '600', '--dir', str(root), '--appendonly', 'yes',
                      '--appendfsync', 'always', '--save', '', '--maxmemory-policy', 'noeviction')
                connect(root / 'r.sock').close()
                start('uchatd', 'serve', '--config', str(config))
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
                print('Installed uChat: service UID, private Redis, crash persistence, offline delivery and auto reply passed')
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
