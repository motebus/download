#!/usr/bin/env python3
"""Prepublication consumer acceptance using exact reviewed historical archives."""
import hashlib,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INPUTS={
 'baseline.deb':('agent-computer-v0.2.0-4','cx-mesh_1.1.0-1_amd64.deb','5c8de2c9ff7fe2143514be6069c8a7c10fe83da8cab8bee30731c360324c8746'),
 'historical.deb':('deb-v2026.08.25-2','cx-node_0.3.1-4_amd64.deb','06a2507ea7e66d0efc41241e38f94ecf91f930b4bdb48ae34c3f7f3bb82ef020'),
 'old1.deb':('medge-v5.7.0-5','cx-node_0.3.3-1_amd64.deb','23be77845703665634e82760bf6add620eeb12014b982d91e503caa8e5947d88'),
 'old6.deb':('medge-v5.10.0-1','cx-node_0.3.3-6_amd64.deb','6aba1df2ebd5e5f844ee7f1ad4383580e26a1f0403cbb50d458ee9c5e6e01397'),
 'old-mesh.deb':('agent-computer-v0.1.0-3','codex-mesh_1.0.0-1_amd64.deb','79ea8390ba64a462e2be9df5550969b6a917f4b13bc7ea3ab9c06eb532a55a38'),
 'consolidated.deb':('agent-computer-v0.2.0-7','cx-mesh_1.2.0-1_amd64.deb','caa078bdd810580dc8b35380d2fe8abbda6ff6c4338f2a8c8dbbba3051d02af0')}

def main(package):
    package=Path(package).resolve()
    assert subprocess.check_output(['dpkg-deb','-f',str(package),'Package','Version'],text=True)=='Package: cx-mesh\nVersion: 2.0.0-1\n'
    with tempfile.TemporaryDirectory() as temp:
        stage=Path(temp)
        for name,(tag,asset,digest) in INPUTS.items():
            path=stage/name
            subprocess.run(['curl','-fsSL','--proto','=https','--proto-redir','=https','--retry','2','--max-time','120',f'https://github.com/motebus/download/releases/download/{tag}/{asset}','-o',str(path)],check=True)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
        (stage/'new.deb').write_bytes(package.read_bytes())
        image='cx-mesh-consumer-acceptance'
        subprocess.run(['docker','build','-t',image,str(ROOT/'tests/cx-mesh-upgrade')],check=True)
        for scenario in ['old1','old6']:
            subprocess.run(['docker','run','--rm','--network','none','--memory','768m','--memory-swap','768m','--cpus','1','-v',str(ROOT)+':/source:ro','-v',str(stage)+':/packages:ro',image,'python3','/source/tests/cx-mesh-upgrade/run.py',scenario],check=True)

if __name__=='__main__':main(sys.argv[1])
