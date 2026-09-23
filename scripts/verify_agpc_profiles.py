#!/usr/bin/env python3
"""Exercise signed standard/full installers on a disposable native Actions VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import urllib.request
import uuid


def run(*args, capture=False):
    print('+', *args, flush=True)
    result = subprocess.run(args, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None, timeout=2400)
    return result.stdout.strip() if capture else None


def installed(name):
    result = subprocess.run(['dpkg-query', '-W', '-f=${Status}\t${Version}', name],
                            capture_output=True, text=True)
    if result.returncode or not result.stdout.startswith('install ok installed\t'):
        return None
    return result.stdout.split('\t')[1]


def containers():
    result = subprocess.run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'],
                            capture_output=True, text=True, check=True).stdout
    prefixes = ('docker', 'containerd', 'podman', 'runc', 'buildah')
    return sorted(line for line in result.splitlines() if line.split('\t')[0].startswith(prefixes))


def installer_diagnostics():
    """Keep the failed detached job's service evidence in the Actions log."""
    debug_setup = (
        "from pathlib import Path\n"
        "import sys\n"
        "source=Path('/usr/libexec/uchat/setup-default.py').read_text()\n"
        "source=source.replace(\"        p.exit(1, 'uChat setup failed; inspect account, configuration and service status. Existing configuration was retained or restored.\\\\n')\", \"        import traceback; traceback.print_exc(); raise\")\n"
        "sys.argv=['setup-default.py','--user','runner']\n"
        "exec(compile(source, '/usr/libexec/uchat/setup-default.py', 'exec'), {'__name__':'__main__'})\n"
    )
    for command in (
        ('sudo', 'python3', '-c', debug_setup),
        ('sudo', 'id', 'runner'),
        ('sudo', 'getent', 'group', 'uchat'),
        ('sudo', 'cat', '/etc/uchatd/uchatd.json'),
        ('sudo', 'runuser', '-u', 'runner', '--', '/usr/bin/uchat', 'uname', '--json'),
        ('sudo', 'systemctl', 'status', 'uchatd.service', '--no-pager'),
        ('sudo', 'journalctl', '-u', 'uchatd.service', '-n', '80', '--no-pager'),
        ('sudo', 'stat', '-c', '%n %u:%g %a', '/var/lib/uchatd',
         '/var/lib/uchatd/store.identity.json', '/var/lib/uchatd-redis',
         '/run/uchatd-store/redis.sock'),
        ('sudo', 'find', '/var/lib', '-maxdepth', '1', '-type', 'd', '-name', 'agpc-install.*',
         '-exec', 'sh', '-c', 'for d do test -f "$d/install.log" && { echo "--- $d/install.log"; tail -n 120 "$d/install.log"; }; done', 'sh', '{}', '+'),
    ):
        print('+', *command, flush=True)
        subprocess.run(command, check=False, text=True, timeout=120)



def context_lifecycle(caller):
    binary = '/usr/sbin/contextd'
    task = 'native-acceptance-' + str(uuid.uuid4())
    ref = json.loads(run('sudo', 'runuser', '-u', 'nobody', '--', binary, 'reference', '--task', task, capture=True))['context_ref']
    def request(owner, operation, revision, args, request_id=None):
        payload = {'schema':'contextd.request/v1', 'request_id':request_id or str(uuid.uuid4()),
                   'operation':operation, 'task_id':task, 'context_ref':ref,
                   'expected_revision':revision, 'args':args}
        command = ['sudo', 'runuser', '-u', owner, '--', binary, 'request', '--socket', '/run/contextd/contextd.sock']
        response = subprocess.run(command, input=json.dumps(payload)+'\n', capture_output=True,
                                  text=True, check=True, timeout=40)
        value = json.loads(response.stdout)
        assert value['request_id'] == payload['request_id']
        return value
    opened = request('nobody', 'context.open', 0, {})
    assert opened['ok'], opened
    revision = opened['result']['revision']
    for owner in ['root', caller]:
        denied = request(owner, 'context.list', revision, {})
        assert denied.get('ok') is False and denied['error']['code'] == 'CONTEXT_ACCESS_DENIED', denied
    mutation = str(uuid.uuid4())
    written = request('nobody', 'context.put', revision, {'key':'result','content':{'saved':True}}, mutation)
    assert written['ok'], written
    assert request('nobody', 'context.put', revision, {'key':'result','content':{'saved':True}}, mutation) == written
    closed = request('nobody', 'context.close', written['result']['revision'], {})
    assert closed['ok'] and closed['result']['closed'] is True, closed
    run('sudo', 'systemctl', 'restart', 'contextd.service')
    run('sudo', 'systemctl', 'is-active', 'contextd.service')
    read = request('nobody', 'context.get', closed['result']['revision'], {'key':'result'})
    assert read['ok'] and read['result']['content'] == {'saved':True}, read
    assert request('nobody', 'context.put', revision, {'key':'result','content':{'saved':True}}, mutation) == written
    return {'real_distinct_uids_tested':True, 'root_bypass_denied':True,
            'closed_state_survived_service_restart':True, 'exact_retry_retained':True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('site', type=Path)
    parser.add_argument('--profile', choices=['standard', 'full', 'upgrade'], required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'motebus/download':
        raise SystemExit('Installation acceptance is restricted to disposable motebus/download Actions VMs.')
    if os.geteuid() == 0 or os.environ.get('RUNNER_OS') != 'Linux':
        raise SystemExit('Run as the unprivileged Actions Linux user with explicit sudo steps.')
    root = Path(__file__).resolve().parents[1]
    site = args.site.resolve()
    overlay = json.loads((site / 'agent-computer-apt-overlay.json').read_text())
    assert overlay['schema'] == 'agent-computer-apt-overlay/v7'
    approved = {p['name']: p for p in overlay['release']['packages'] + overlay['release']['retention_packages']}
    key = root / 'medge-archive-keyring.gpg'
    run('gpgv', '--keyring', str(key), str(site / 'dists/stable/InRelease'))
    for name in ['agent-computer-apt-overlay.json', 'agpc.sh', 'agpc-all.sh']:
        run('gpgv', '--keyring', str(key), str(site / (name+'.asc')), str(site / name))
    before_containers = containers()
    for name in ['agent-sphere', 'agpc-apps', 'agent-apps', 'contextd', 'uchatd']:
        assert installed(name) is None, 'Acceptance requires a fresh disposable VM: '+name
    user = pwd.getpwuid(os.getuid()).pw_name
    with tempfile.TemporaryDirectory(prefix='agpc-native-acceptance-') as folder:
        temp = Path(folder)
        source = temp / 'agpc-acceptance.sources'
        source.write_text('Types: deb\nURIs: '+site.as_uri()+'\nSuites: stable\nComponents: main\n'
                          'Architectures: amd64\nSigned-By: /usr/share/keyrings/agpc-acceptance.gpg\n')
        run('sudo', 'install', '-m', '0644', str(key), '/usr/share/keyrings/agpc-acceptance.gpg')
        run('sudo', 'install', '-m', '0644', str(source), '/etc/apt/sources.list.d/agpc-acceptance.sources')
        if args.profile == 'upgrade':
            run('sudo', 'apt-get', 'update')
            filename = 'agent-apps_0.2.0-4_all.deb'
            url = 'https://github.com/motebus/download/releases/download/agent-computer-v0.2.0-15/'+filename
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(2*1024*1024)
            assert hashlib.sha256(data).hexdigest() == 'e8b2cb48e831f8a0149323900b966bdb8baf62706f950c2da3df6fb6895d0703'
            legacy = temp / filename; legacy.write_bytes(data)
            # The old transition package intentionally has dependencies that are
            # supplied by the target profile (including the external Obsidian
            # prerequisite). Seed only its dpkg state; the reviewed installer
            # repairs the dependency graph during the actual upgrade.
            run('sudo', 'dpkg', '--force-depends', '--install', str(legacy))
            assert installed('agent-apps') == '0.2.0-4'
        entry = 'agpc.sh' if args.profile == 'standard' else 'agpc-all.sh'
        try:
            run('sudo', 'bash', str(site / entry), '--yes', '--user', user)
        except subprocess.CalledProcessError:
            installer_diagnostics()
            raise
        expected = {'agent-sphere', 'agent-ultra', 'agpc-manager', 'contextd', 'uchatd'}
        if args.profile != 'standard': expected.add('agpc-apps')
        if args.profile == 'upgrade': expected.add('agent-apps')
        versions = {name: installed(name) for name in sorted(expected)}
        assert all(versions[name] == approved[name]['version'] for name in expected), versions
        if args.profile == 'standard':
            assert installed('agpc-apps') is None and installed('agent-apps') is None
        elif args.profile == 'full':
            assert installed('agent-apps') is None, 'Fresh full installation must not add the compatibility transition.'
        assert run('sudo', 'dpkg', '--audit', capture=True) == ''
        assert containers() == before_containers, 'Native installation changed container runtime packages.'
        service = run('sudo', 'python3', str(root/'scripts/verify_contextd_service.py'), capture=True)
        lifecycle = context_lifecycle(user)
        # Reinstall through the same shipped entrypoint to verify idempotent selection.
        run('sudo', 'bash', str(site / entry), '--yes', '--user', user)
        assert {name: installed(name) for name in expected} == versions
        assert containers() == before_containers
        evidence = {'schema':'agpc.native-installer-acceptance/v1', 'profile':args.profile,
                    'entrypoint':entry, 'entrypoint_sha256':hashlib.sha256((site/entry).read_bytes()).hexdigest(),
                    'aggregate_tag':overlay['release']['tag'], 'installed':versions,
                    'container_packages_unchanged':True, 'reinstallation_passed':True,
                    'contextd_service':json.loads(service), 'contextd_lifecycle':lifecycle,
                    'global_runtime_ready':False}
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence,indent=2))


if __name__ == '__main__':
    main()
