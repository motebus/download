"""Offline publication boundary tests; no credentials or network."""
import copy,hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import publish_agpc_keys as p

def record():
 return {'schema':'agpc.keys.publication-inputs/v1','tag':p.TAG,'candidate_tag':'candidate-'+p.TAG,
 'components':{n:{'source_project':v['project'],'source_commit':'a'*40,'pipeline_id':10+i,'job_id':20+i,'producer_manifest_sha256':'b'*64} for i,(n,v) in enumerate(p.PACKAGES.items())},
 'assets':{n:{'sha256':'c'*64,'bytes':10} for n in p.ASSETS},'notes':'Explicit credential management; runtime verification remains separate.'}

class PublicationTests(unittest.TestCase):
 def test_original_voice_owner_is_reused_without_republication(self):
  self.assertEqual(set(p.PACKAGES),{'agpc-key-manager'})
  self.assertIn('agpc-voice-key-owner (= 0.1.0-1)',p.PACKAGES['agpc-key-manager']['dependencies'])
 def test_record_refuses_extra_payload_and_unreviewed_sources(self):
  r=record();p.validate_record(r)
  for mutate in [lambda r:r.update(extra=True),lambda r:r.update(tag='other'),lambda r:r['assets'].update({'extra.deb':{'sha256':'c'*64,'bytes':1}}),lambda r:r['components']['agpc-key-manager'].update(source_project=1),lambda r:r['components']['agpc-key-manager'].update(job_id=True),lambda r:r['assets']['MANIFEST.json'].update(bytes=True),lambda r:r.update(notes='gitlab private')]:
   value=copy.deepcopy(r);mutate(value)
   with self.assertRaises(ValueError):p.validate_record(value)
 def test_requires_native_main_and_exact_job(self):
  name='agpc-key-manager';c=record()['components'][name]
  pipe={'id':c['pipeline_id'],'sha':c['source_commit'],'ref':'main','status':'success'}
  job={'id':c['job_id'],'name':p.PACKAGES[name]['job'],'status':'success','ref':'main','commit':{'id':c['source_commit']},'allow_failure':False,'pipeline':pipe,'tag_list':['l5','deb','native']}
  p.jobs(c,name,pipe,job)
  for field,value in [('ref','branch'),('status','failed'),('allow_failure',True),('tag_list',['docker']),('name','unrelated')]:
   with self.assertRaises(ValueError):p.jobs(c,name,pipe,{**job,field:value})
 def fresh_fixture(self,mutate=None):
  r=record();responses={}
  for name,c in r['components'].items():
   data=('fixture package '+name).encode();manifest=p.encoded({'sha256':p.sha(data)})
   c['producer_manifest_sha256']=p.sha(manifest);r['assets'][name+'_0.1.0-2_all.deb']={'sha256':p.sha(data),'bytes':len(data)}
   pipeline={'id':c['pipeline_id'],'sha':c['source_commit'],'ref':'main','status':'success'}
   job={'id':c['job_id'],'name':p.PACKAGES[name]['job'],'status':'success','ref':'main','commit':{'id':c['source_commit']},'allow_failure':False,'pipeline':pipeline,'tag_list':['l5','deb','native']}
   prefix='/jobs/'+str(c['job_id'])+'/artifacts/components/'+name+'/dist/'
   evidence={'schema':'agpc.keys.package-lifecycle/v1','package_sha256':p.sha(data),'native_lifecycle':True,'credential_fixture_bytes_and_metadata_preserved':True,'scriptless':True,'host_dpkg_unchanged':True,'force_depends_in_isolated_fixture':True,'clean_target_dependencies_installed':False,'production_credentials_accessed':False,'runtime_acceptance':False}
   responses[c['source_project']]={'/repository/branches/main':p.encoded({'commit':{'id':c['source_commit']}}),'/pipelines/'+str(c['pipeline_id']):p.encoded(pipeline),'/jobs/'+str(c['job_id']):p.encoded(job),prefix+'manifest.json':manifest,prefix+name+'_0.1.0-2_all.deb':data,prefix+'package-evidence.json':p.encoded(evidence)}
  if mutate:mutate(responses)
  with patch.object(p,'api',side_effect=lambda project:lambda path:responses[project][path]),patch.object(p,'run',return_value=json.dumps({'commit':{'sha':'d'*40}})),patch.dict(os.environ,{'GITHUB_SHA':'d'*40}):
   return p.fresh(r)
 def test_exact_original_ci_and_lifecycle_are_required(self):
  self.assertEqual(set(self.fresh_fixture()),set(p.PACKAGES))
  def advanced(r):r[1336]['/repository/branches/main']=p.encoded({'commit':{'id':'e'*40}})
  def package_changed(r):
   key=next(k for k in r[1336] if k.endswith('.deb'));r[1336][key]=b'changed'
  def evidence_changed(r):
   key=next(k for k in r[1336] if k.endswith('package-evidence.json'));value=json.loads(r[1336][key]);value['runtime_acceptance']=True;r[1336][key]=p.encoded(value)
  for mutate in (advanced,package_changed,evidence_changed):
   with self.assertRaises(ValueError):self.fresh_fixture(mutate)
 def fixture(self,root,name,extra=None):
  c=record()['components'][name];spec=p.PACKAGES[name]
  source=b'"""Inert publication fixture, not a runtime."""\n'
  readme=b'No runtime acceptance.\n'
  files={'components/'+name+'/'+f:{'sha256':p.sha(f.encode()),'bytes':len(f)} for f in ('README.md','build.py','test-package.py','src/'+spec['module'],'tests/'+spec['test'])}
  files['components/'+name+'/src/'+spec['module']]={'sha256':p.sha(source),'bytes':len(source)}
  files['components/'+name+'/README.md']={'sha256':p.sha(readme),'bytes':len(readme)}
  proof={'schema':'agpc.keys.build/v1','package':name,'version':'0.1.0-2','architecture':'all','source_project':c['source_project'],'source_commit':c['source_commit'],'source_files':files,'source_date_epoch':1,'release_admitted':False,'runtime_verified':False}
  payload={spec['entry']:(b'#!/usr/bin/python3 -I\n'+source,0o755),f'usr/share/doc/{name}/README.md':(readme,0o644),f'usr/share/doc/{name}/PROVENANCE.json':(p.encoded(proof),0o644)}
  stage=root/'root';stage.mkdir()
  for path,(data,mode) in payload.items():
   f=stage/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data);f.chmod(mode)
  controls=stage/'DEBIAN';controls.mkdir()
  (controls/'control').write_text(f'Package: {name}\nVersion: 0.1.0-2\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\nDescription: Inert fixture\nDepends: '+spec['dependencies']+'\n')
  (controls/'md5sums').write_text(''.join(hashlib.md5(data).hexdigest()+'  '+path+'\n' for path,(data,_) in sorted(payload.items())))
  if extra:
   f=stage/extra;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('#!/bin/sh\nexit 0\n' if extra.startswith('DEBIAN/') else 'unexpected');f.chmod(0o755 if extra.startswith('DEBIAN/') else 0o644)
  for f in stage.rglob('*'):
   if f.is_dir():f.chmod(0o755)
  stage.chmod(0o755)
  deb=root/(name+'_0.1.0-2_all.deb');subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(deb)],check=True,capture_output=True)
  build={**proof,'filename':deb.name,'sha256':p.sha(deb.read_bytes()),'bytes':deb.stat().st_size,'dependencies':spec['dependencies'],'files':{path:{'sha256':p.sha(data),'bytes':len(data),'mode':format(mode,'04o'),'uid':0,'gid':0} for path,(data,mode) in payload.items()}}
  return deb,c,build
 def test_exact_scriptless_packages_and_source_binding(self):
  for name in p.PACKAGES:
   with tempfile.TemporaryDirectory() as folder:
    deb,c,build=self.fixture(Path(folder),name);p.validate_package(deb,name,c,build)
    for field,value in [('source_commit','e'*40),('architecture','amd64'),('dependencies','python3'),('runtime_verified',True)]:
     with self.assertRaises(ValueError):p.validate_package(deb,name,c,{**build,field:value})
 def test_hooks_and_credentials_are_never_packaged(self):
  for extra in ('DEBIAN/postinst','etc/agpc-voice/credentials/openai-api-key','usr/bin/unreviewed'):
   with tempfile.TemporaryDirectory() as folder:
    name='agpc-key-manager';deb,c,build=self.fixture(Path(folder),name,extra)
    with self.assertRaises(ValueError):p.validate_package(deb,name,c,build)
 def test_unreviewed_context_cannot_touch_signer_or_network(self):
  with patch.dict(os.environ,{},clear=True),patch.object(p,'api') as api,patch.object(p,'run') as run:
   with self.assertRaises(ValueError):p.publish()
  api.assert_not_called();run.assert_not_called()

if __name__=='__main__':unittest.main()
