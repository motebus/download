import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agpc_profiles as profiles
import publish_agpc_apt as promotion
import publish_apt as apt
import publish_native as native
import native_install_policy


class ProfilePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'; self.root.mkdir()
        self.site = Path(self.temp.name) / 'site'; self.site.mkdir()
        self.records = {}
        for name, kind in [('agpc.sh','standard'), ('agpc-all.sh','full')]:
            data = ('#!/bin/sh\n# '+kind+'\n').encode()
            record = {'schema':'agpc-installer-source/v2','repository':'motebus/agent-sphere-deb',
                      'tag':'v0.3.0-1','source_commit':'a'*40,'asset':name,'sha256':profiles.digest(data),'profile':kind}
            (self.root/name).write_bytes(data)
            (self.root/name.replace('.sh','.source.json')).write_text(json.dumps(record))
            self.records[kind] = record
        for source, alias in [('agpc-all.sh','agent-sphere-apps.sh'),
                              ('agpc-all.source.json','agent-sphere-apps.source.json')]:
            (self.root/alias).write_bytes((self.root/source).read_bytes())
        (self.root/'uninstall.sh').write_bytes(b'#!/bin/sh\n# current uninstaller\n')
        self.manifest = {'schema':'agent-sphere-release/v2', 'source_commit':'a'*40,
                         'source_ref':'refs/heads/main', 'version':'0.3.0-1',
                         'component_baseline':{'pending_native_components':[]},
                         'installer_profiles':{'agpc.sh':'standard','agpc-all.sh':'full',
                                               'agent-sphere-apps.sh':'full-compatibility'},
                         'assets':[{'name':r['asset'],'sha256':r['sha256']} for r in self.records.values()]}
        data = b'fixture-package'
        package = {'name':'contextd','version':'0.1.0-1','architecture':'amd64',
                   'asset':'contextd_0.1.0-1_amd64.deb','sha256':profiles.digest(data)}
        self.config = {'schema':'agent-computer-apt-overlay/v7',
                       'release':{'tag':'agent-computer-v0.3.0-1','packages':[package], 'retention_packages':[]}}
        self.package = self.site/'pool/main/c/contextd'/package['asset']
        self.package.parent.mkdir(parents=True); self.package.write_bytes(data)
        (self.site/'agent-computer-apt-overlay.json').write_text(json.dumps(self.config))
        index = self.site/'dists/stable/main/binary-amd64/Packages'; index.parent.mkdir(parents=True)
        index.write_text('Package: contextd\nVersion: 0.1.0-1\nArchitecture: amd64\nFilename: pool/main/c/contextd/'
                         +package['asset']+'\nSHA256: '+package['sha256']+'\n\n')

    def download(self, record, name):
        return json.dumps(self.manifest).encode() if name == 'release-manifest.json' else (self.root/name).read_bytes()

    def activate(self):
        with patch.object(apt,'validate_agent_apps_installer',return_value=self.records['standard']), \
             patch.object(apt,'load_agent_computer_overlay',return_value=self.config), \
             patch.object(profiles,'download',side_effect=self.download), \
             patch.object(native_install_policy,'audit_deb'), \
             patch.object(profiles.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            return profiles.activated_files(self.root,self.site)

    def test_completed_signed_cohort_binds_distinct_standard_and_full(self):
        record, files = self.activate()
        self.assertEqual(set(files),profiles.PROFILE_FILES)
        self.assertNotEqual(files['agpc.sh'],files['agpc-all.sh'])
        self.assertEqual(files['agpc-all.sh'],files['agent-sphere-apps.sh'])
        self.assertEqual(record['aggregate_tag'],'agent-computer-v0.3.0-1')

    def test_missing_leaf_or_wrong_source_release_cannot_publish_entrypoints(self):
        original = copy.deepcopy(self.manifest)
        for key,value in [('source_ref','refs/heads/draft'),('source_commit','b'*40),
                          ('version','0.2.0-15'),('component_baseline',{'pending_native_components':['contextd']}),
                          ('installer_profiles',{}),('assets',[])]:
            self.manifest = {**copy.deepcopy(original),key:value}
            with self.subTest(key=key), self.assertRaises(ValueError):self.activate()
        self.manifest = original
        self.records['full']['source_commit']='b'*40
        (self.root/'agpc-all.source.json').write_text(json.dumps(self.records['full']))
        with self.assertRaises(ValueError):self.activate()

    def test_stale_index_package_corruption_and_missing_activation_fail(self):
        self.package.write_bytes(b'corrupt')
        with self.assertRaisesRegex((ValueError,apt.PublishError),'payload'):self.activate()
        self.package.write_bytes(b'fixture-package')
        (self.site/'agent-computer-apt-overlay.json').write_text(json.dumps({'schema':'old'}))
        with self.assertRaisesRegex(ValueError,'activated'):self.activate()
        (self.site/'agent-computer-apt-overlay.json').write_text(json.dumps(self.config))
        (self.site/'dists/stable/main/binary-amd64/Packages').write_text('')
        with self.assertRaises(apt.PublishError):self.activate()

    def test_signature_failure_stops_profile_activation(self):
        with patch.object(apt,'validate_agent_apps_installer',return_value=self.records['standard']), \
             patch.object(apt,'load_agent_computer_overlay',return_value=self.config), \
             patch.object(profiles,'download',side_effect=self.download), \
             patch.object(profiles.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['gpgv'])):
            with self.assertRaises(subprocess.CalledProcessError):profiles.activated_files(self.root,self.site)

    def test_existing_pool_and_unrelated_files_are_immutable(self):
        before={'pool/main/c/core/old.deb':'old','index.html':'old','unrelated.txt':'kept'}
        after={**before,'pool/main/c/contextd/new.deb':'new','agpc-all.sh':'full'}
        promotion.verify_preserved(before,after,{'pool/main/c/contextd/new.deb'})
        for changed in [{**after,'pool/main/c/core/old.deb':'changed'},
                        {k:v for k,v in after.items() if k!='unrelated.txt'},
                        {**after,'private.env':'secret'}]:
            with self.assertRaises(apt.PublishError):promotion.verify_preserved(before,changed,{'pool/main/c/contextd/new.deb'})

    def test_future_native_overlay_keeps_new_profiles_instead_of_preview(self):
        (self.root/'scripts').mkdir()
        (self.root/'scripts/native-index.html').write_text('profiles')
        (self.site/'agent-sphere-apps.sh').write_text('old alias')
        files={name:b'old-preview' for name in native.NATIVE_FILES}
        record={'version':'preview','linux_backend_sha256':{'old':'digest'},'files':{}}
        selected={name:(self.root/name).read_bytes() for name in profiles.PROFILE_FILES}
        def sign(root,site,names):
            self.assertIn('agpc-all.sh',names)
            for name in names:(site/(name+'.asc')).write_text('signature fixture')
        before=native.snapshot(self.site)
        with patch.object(native,'assemble',return_value=({},record,files)), \
             patch.object(profiles,'activated_files',return_value=({'aggregate_tag':'new'},selected)), \
             patch.object(native,'sign_files',side_effect=sign):
            native.overlay(self.root,self.site,Path(self.temp.name)/'evidence.json')
        self.assertEqual((self.site/'agpc.sh').read_bytes(),selected['agpc.sh'])
        self.assertEqual((self.site/'agpc-all.sh').read_bytes(),selected['agpc-all.sh'])
        self.assertEqual((self.site/'agent-sphere-apps.sh').read_bytes(),selected['agpc-all.sh'])
        self.assertEqual((self.site/'uninstall.sh').read_bytes(),selected['uninstall.sh'])
        self.assertEqual(profiles.digest(self.package.read_bytes()),before[self.package.relative_to(self.site).as_posix()])
        for line in (self.site/'agpc-native-SHA256SUMS').read_text().splitlines():
            digest,name=line.split('  ')
            self.assertEqual(profiles.digest((self.site/name).read_bytes()),digest)


class WindowsOnlyPagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'; (self.root/'scripts').mkdir(parents=True)
        self.site = Path(self.temp.name) / 'site'; self.site.mkdir()
        self.pin = {'tag':'agpc-windows-v0.1.0-host-access-preview.8',
                    'manifest_sha256':'a'*64}
        (self.root/'scripts/native-pages.json').write_text(json.dumps({'windows_x86_64':self.pin}))
        (self.site/'agpc.sh').write_bytes(b'newer Linux profile')
        (self.site/'agpc.exe').write_bytes(b'old Windows preview')
        (self.site/'agent-computer-apt-overlay.json').write_text(json.dumps({
            'schema':'agent-computer-apt-overlay/v8',
            'release':{'tag':'agent-computer-v0.3.0-69'}}))
        self.record = {'schema':'agpc.native-pages/v2',
                       'linux_profiles':{'aggregate_tag':'agent-computer-v0.3.0-69'},
                       'files':{name:{'sha256':native.file_digest(self.site/name),
                                      'bytes':(self.site/name).stat().st_size}
                                for name in ('agpc.sh','agpc.exe')}}
        (self.site/'agpc-native.source.json').write_text(json.dumps(self.record))
        sums = {name:item['sha256'] for name,item in self.record['files'].items()}
        sums['agpc-native.source.json'] = native.file_digest(self.site/'agpc-native.source.json')
        (self.site/'agpc-native-SHA256SUMS').write_bytes(''.join(
            f"{sha}  {name}\n" for name,sha in sorted(sums.items())).encode())
        for name in ('agpc.sh','agpc.exe','agpc-native.source.json',
                     'agpc-native-SHA256SUMS','agent-computer-apt-overlay.json'):
            (self.site/(name+'.asc')).write_text('signed')
        (self.site/'index.html').write_text('newer landing page')

    def publish(self):
        def sign(root, site, names):
            for name in names:(site/(name+'.asc')).write_text('new signature')
        with patch.object(native.subprocess,'run',return_value=subprocess.CompletedProcess([],0)), \
             patch.object(native,'windows_host_preview',return_value=(b'preview8',{'version':'preview8'})), \
             patch.object(native,'sign_files',side_effect=sign):
            native.overlay_windows(self.root,self.site,Path(self.temp.name)/'evidence.json')

    def test_windows_update_preserves_newer_signed_linux_cohort(self):
        original = native.snapshot(self.site)
        self.publish()
        self.assertEqual((self.site/'agpc.exe').read_bytes(),b'preview8')
        self.assertEqual((self.site/'agpc.sh').read_bytes(),b'newer Linux profile')
        self.assertEqual((self.site/'index.html').read_text(),'newer landing page')
        for name, sha in original.items():
            if name not in {'agpc.exe','agpc.exe.asc','agpc-native.source.json',
                            'agpc-native.source.json.asc','agpc-native-SHA256SUMS',
                            'agpc-native-SHA256SUMS.asc'}:
                self.assertEqual(native.file_digest(self.site/name),sha)
        updated = json.loads((self.site/'agpc-native.source.json').read_text())
        self.assertEqual(updated['files']['agpc.exe']['sha256'],native.digest(b'preview8'))
        self.assertEqual(updated['linux_profiles'],self.record['linux_profiles'])

    def test_unsigned_or_mismatched_existing_site_is_rejected(self):
        (self.site/'agpc.sh').write_bytes(b'corrupt profile')
        with self.assertRaisesRegex(ValueError,'existing native file'):
            self.publish()


if __name__ == '__main__':unittest.main()
