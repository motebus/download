#!/usr/bin/env python3
"""Sign exact reviewed main-CI key-management packages; never build or install."""
import argparse,hashlib,io,json,os,re,subprocess,tarfile,tempfile,urllib.parse,urllib.request
from pathlib import Path,PurePosixPath
from publish_agpc_view import SameOriginRedirect,encoded,read_json,require,run,sha
ROOT=Path(__file__).resolve().parents[1]
REPO='motebus/download'
TAG='agpc-key-management-v0.1.0-1'
FINGERPRINT='AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0'
LIMIT=2*1024*1024
PACKAGES={
 'agpc-key-manager':{'project':1336,'job':'agpc-key-manager-native','entry':'usr/bin/agpc-key-manager',
  'dependencies':'python3 (>= 3.10), ca-certificates, sudo, openssh-client, glab, zenity, agpc-voice-key-owner (= 0.1.0-1)','module':'manager.py','test':'test_manager.py'},
 'agpc-voice-key-owner':{'project':1348,'job':'voice-key-owner-native','entry':'usr/libexec/agpc-voice-key-owner',
  'dependencies':'python3 (>= 3.10), ca-certificates, agpc-voice (= 0.1.5~dialplan.20261030.1)','module':'owner.py','test':'test_owner.py'},
}
ASSETS={*(p+'_0.1.0-1_all.deb' for p in PACKAGES),'MANIFEST.json','SHA256SUMS'}

def validate_record(v):
 require(set(v)=={'schema','tag','candidate_tag','components','assets','notes'},'unexpected release fields')
 require(v['schema']=='agpc.keys.publication-inputs/v1' and v['tag']==TAG and v['candidate_tag']=='candidate-'+TAG,'wrong release identity')
 require(set(v['components'])==set(PACKAGES) and set(v['assets'])==ASSETS,'unexpected package/asset inventory')
 for name,c in v['components'].items():
  require(set(c)=={'source_project','source_commit','pipeline_id','job_id','producer_manifest_sha256'},'unexpected producer fields')
  require(c['source_project']==PACKAGES[name]['project'] and re.fullmatch('[a-f0-9]{40}',c['source_commit']) and re.fullmatch('[a-f0-9]{64}',c['producer_manifest_sha256']),'source binding differs')
  require(all(type(c[k]) is int and c[k]>0 for k in ('pipeline_id','job_id')),'invalid producer IDs')
 for pin in v['assets'].values():
  require(set(pin)=={'sha256','bytes'} and re.fullmatch('[a-f0-9]{64}',pin['sha256']) and type(pin['bytes']) is int and 0<pin['bytes']<=LIMIT,'invalid asset pin')
 require(isinstance(v['notes'],str) and 0<len(v['notes'])<10000 and 'gitlab' not in encoded(v).decode().lower(),'private/unbounded release metadata')

def api(project):
 source=urllib.parse.urlsplit(os.environ['AGPC_GITLAB_SOURCE_URL'])
 require(source.scheme=='https' and source.netloc=='gitlab.ypcloud.com' and source.path=='/codex/codex-agpc/agpc-download-source.git' and not source.query and not source.fragment,'unexpected source origin')
 opener=urllib.request.build_opener(SameOriginRedirect())
 def get(path):
  request=urllib.request.Request(source.scheme+'://'+source.netloc+'/api/v4/projects/'+str(project)+path,headers={'PRIVATE-TOKEN':os.environ['AGPC_GITLAB_READ_TOKEN']})
  try:
   with opener.open(request,timeout=30) as response:data=response.read(LIMIT+1)
  except Exception:raise RuntimeError('canonical source request failed') from None
  require(len(data)<=LIMIT,'oversized producer response');return data
 return get

def jobs(c,name,pipeline,job):
 require(pipeline['id']==c['pipeline_id'] and pipeline['status']=='success' and pipeline['ref']=='main' and pipeline['sha']==c['source_commit'],'successful main pipeline required')
 require(job['id']==c['job_id'] and job['name']==PACKAGES[name]['job'] and job['status']=='success' and job['ref']=='main' and job['commit']['id']==c['source_commit'] and job['allow_failure'] is False and job['pipeline']['id']==c['pipeline_id'] and job['pipeline']['sha']==c['source_commit'] and job['pipeline']['ref']=='main' and {'l5','deb','native'}<=set(job['tag_list']),'successful native main job required')

def fresh(record):
 originals={}
 for name,c in record['components'].items():
  get=api(c['source_project'])
  require(read_json(get('/repository/branches/main'))['commit']['id']==c['source_commit'],'source main advanced')
  jobs(c,name,read_json(get('/pipelines/'+str(c['pipeline_id']))),read_json(get('/jobs/'+str(c['job_id']))))
  prefix='/jobs/'+str(c['job_id'])+'/artifacts/components/'+name+'/dist/'
  manifest=get(prefix+'manifest.json');require(sha(manifest)==c['producer_manifest_sha256'],'original producer manifest differs')
  filename=name+'_0.1.0-1_all.deb';data=get(prefix+filename)
  require({'sha256':sha(data),'bytes':len(data)}==record['assets'][filename],'original package differs')
  evidence=read_json(get(prefix+'package-evidence.json'))
  require(evidence=={'schema':'agpc.keys.package-lifecycle/v1','package_sha256':sha(data),'native_lifecycle':True,'credential_fixture_bytes_and_metadata_preserved':True,'scriptless':True,'host_dpkg_unchanged':True,'force_depends_in_isolated_fixture':True,'clean_target_dependencies_installed':False,'production_credentials_accessed':False,'runtime_acceptance':False},'native lifecycle evidence differs')
  originals[name]=manifest
 require(json.loads(run('gh','api',f'repos/{REPO}/branches/main'))['commit']['sha']==os.environ['GITHUB_SHA'],'publisher main advanced')
 return originals

def archive(package,option,allowed):
 # Decompression has a bounded spool; no archive entry is extracted/executed.
 import resource
 def limit():resource.setrlimit(resource.RLIMIT_FSIZE,(8*LIMIT,8*LIMIT))
 with tempfile.TemporaryFile() as output:
  result=subprocess.run(['dpkg-deb',option,str(package)],stdout=output,stderr=subprocess.DEVNULL,timeout=30,preexec_fn=limit)
  require(result.returncode==0 and output.tell()<=8*LIMIT,'invalid/oversized package archive');output.seek(0)
  files={};seen=set();directories={'.',*(p.as_posix() for n in allowed for p in PurePosixPath(n).parents)}
  with tarfile.open(fileobj=output,mode='r:') as stream:
   for item in stream:
    path=PurePosixPath(item.name);name=path.as_posix().removeprefix('./')
    require(not path.is_absolute() and '..' not in path.parts and name not in seen and item.uid==0 and item.gid==0,'unsafe archive entry');seen.add(name)
    if item.isdir():require(name in directories and item.mode==0o755,'unexpected directory');continue
    require(item.isfile() and name in allowed and 0<item.size<LIMIT,'unexpected payload/hook')
    files[name]=(stream.extractfile(item).read(),item.mode)
  require(set(files)==allowed,'incomplete payload');return files

def validate_package(path,name,c,build):
 expected=PACKAGES[name];filename=name+'_0.1.0-1_all.deb'
 require(set(build)=={'schema','package','version','architecture','source_project','source_commit','source_files','source_date_epoch','release_admitted','runtime_verified','filename','sha256','bytes','dependencies','files'},'unexpected build fields')
 require(build['schema']=='agpc.keys.build/v1' and build['package']==name and build['version']=='0.1.0-1' and build['architecture']=='all' and build['source_project']==c['source_project'] and build['source_commit']==c['source_commit'] and build['filename']==filename and build['sha256']==sha(path.read_bytes()) and build['bytes']==path.stat().st_size and build['dependencies']==expected['dependencies'] and build['release_admitted'] is False and build['runtime_verified'] is False,'package/producer identity differs')
 sources={'components/'+name+'/'+p for p in ('README.md','build.py','test-package.py','src/'+expected['module'],'tests/'+expected['test'])}
 require(set(build['source_files'])==sources,'unexpected source inventory')
 for pin in build['source_files'].values():require(set(pin)=={'sha256','bytes'} and re.fullmatch('[a-f0-9]{64}',pin['sha256']) and type(pin['bytes']) is int and 0<pin['bytes']<LIMIT,'invalid source pin')
 allowed={expected['entry'],f'usr/share/doc/{name}/README.md',f'usr/share/doc/{name}/PROVENANCE.json'}
 controls=archive(path,'--ctrl-tarfile',{'control','md5sums'});data=archive(path,'--fsys-tarfile',allowed)
 require(all(mode==0o644 for _,mode in controls.values()),'control modes differ')
 text=controls['control'][0].decode()
 for key,value in [('Package',name),('Version','0.1.0-1'),('Architecture','all'),('Depends',expected['dependencies'])]:
  require(re.findall('^'+key+': (.*)$',text,re.M)==[value],'control identity differs')
 require(not re.search(r'^(?:Pre-Depends|Conflicts|Breaks|Replaces|Provides|Essential):',text,re.M),'unexpected relationship')
 require(set(build['files'])==allowed,'unexpected file inventory')
 for filename,(body,mode) in data.items():
  expected_mode=0o755 if filename==expected['entry'] else 0o644
  require(mode==expected_mode and build['files'][filename]=={'sha256':sha(body),'bytes':len(body),'mode':format(mode,'04o'),'uid':0,'gid':0},'payload metadata differs')
 require(controls['md5sums'][0].decode()==''.join(hashlib.md5(data[n][0]).hexdigest()+'  '+n+'\n' for n in sorted(data)),'checksums differ')
 provenance={k:v for k,v in build.items() if k not in ('filename','sha256','bytes','dependencies','files')}
 require(read_json(data[f'usr/share/doc/{name}/PROVENANCE.json'][0])==provenance,'embedded provenance differs')
 entry=data[expected['entry']][0];require(entry.startswith(b'#!/usr/bin/python3 -I\n'),'isolated administrative interpreter required')
 raw=entry.split(b'\n',1)[1];source=build['source_files']['components/'+name+'/src/'+expected['module']]
 require(source=={'sha256':sha(raw),'bytes':len(raw)},'installed helper differs from source')
 require(build['source_files']['components/'+name+'/README.md']=={'sha256':sha(data[f'usr/share/doc/{name}/README.md'][0]),'bytes':len(data[f'usr/share/doc/{name}/README.md'][0])},'installed documentation differs')

def validate_bundle(stage,record,originals=None):
 validate_record(record);require({p.name for p in stage.iterdir()}==ASSETS,'unexpected bundle inventory')
 for name,pin in record['assets'].items():
  p=stage/name;require(p.is_file() and not p.is_symlink() and {'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}==pin,'asset differs')
 manifest=read_json((stage/'MANIFEST.json').read_bytes())
 require(set(manifest)=={'schema','tag','components','builds','runtime_verified','core_all_admitted'} and manifest['schema']=='agpc.keys.release-manifest/v1' and manifest['tag']==TAG and manifest['components']==record['components'] and set(manifest['builds'])==set(PACKAGES) and manifest['runtime_verified'] is False and manifest['core_all_admitted'] is False,'release manifest differs')
 for name,build in manifest['builds'].items():
  if originals is not None:require(build==read_json(originals[name]),'sanitized producer differs')
  validate_package(stage/(name+'_0.1.0-1_all.deb'),name,record['components'][name],build)
 require((stage/'SHA256SUMS').read_text()==''.join(record['assets'][n]['sha256']+'  '+n+'\n' for n in sorted(ASSETS-{'SHA256SUMS'})),'checksum inventory differs')
 from publish_apt import validate_no_gitlab_urls
 validate_no_gitlab_urls(stage)

def absent():
 for endpoint in ('releases/tags/','git/ref/tags/'):
  p=subprocess.run(['gh','api',f'repos/{REPO}/'+endpoint+TAG],capture_output=True,text=True,timeout=30)
  require(p.returncode!=0 and 'HTTP 404' in p.stderr,'release/tag exists or absence unknown')

def publish():
 context={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':REPO,'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_WORKFLOW_REF':REPO+'/.github/workflows/publish-agpc-keys.yml@refs/heads/main'}
 require(all(os.environ.get(k)==v for k,v in context.items()) and re.fullmatch('[a-f0-9]{40}',os.environ.get('GITHUB_SHA','')),'unreviewed publisher context')
 record=read_json((ROOT/'scripts/agpc-keys-release.json').read_bytes());validate_record(record);originals=fresh(record);absent()
 with tempfile.TemporaryDirectory(prefix='agpc-keys-sign-') as directory:
  stage=Path(directory)/'bundle';stage.mkdir()
  for name in sorted(ASSETS):run('gh','release','download',record['candidate_tag'],'--repo',REPO,'--pattern',name,'--dir',str(stage))
  validate_bundle(stage,record,originals)
  keyhome=Path(directory)/'gnupg';keyhome.mkdir(mode=0o700);previous=os.environ.get('GNUPGHOME');os.environ['GNUPGHOME']=str(keyhome)
  try:
   require(''.join((ROOT/'medge-archive-keyring.fingerprint').read_text().split()).upper()==FINGERPRINT,'archive identity changed')
   run('gpg','--batch','--import',input=os.environ['MEDGE_APT_SIGNING_KEY'])
   from publish_native import sign_files
   sign_files(ROOT,stage,{'MANIFEST.json','SHA256SUMS'});fresh(record);absent()
   notes=Path(directory)/'notes.txt';notes.write_text(record['notes'])
   run('gh','release','create',TAG,'--repo',REPO,'--target',os.environ['GITHUB_SHA'],'--title','AGPC API Keys management 0.1.0-1','--notes-file',str(notes),'--latest=false',*map(str,sorted(stage.iterdir())))
  finally:
   if previous is None:os.environ.pop('GNUPGHOME',None)
   else:os.environ['GNUPGHOME']=previous
 print('Published signed '+TAG)

if __name__=='__main__':publish()
