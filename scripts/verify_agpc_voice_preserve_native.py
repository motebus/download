#!/usr/bin/env python3
"""Observe real systemd masks/state preservation on a disposable fresh CI host.

Only unit names/receipt root are redirected to uniquely named fixture units.
The source's mask, inode, preservation, stop/start and refusal logic is original.
Package lifecycle is independently exercised by the completed canonical entry.
This is not the public upgrade entry or a production-host/telephone acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import verify_agpc_voice_decoder_native as admitted

SCRIPT=Path('/var/lib/agpc-voice-native-host-prep/preserve.py')


def main():
    require=admitted.require
    require(Path(__file__).resolve()==SCRIPT and sys.argv[1:]==['--disposable-fresh'],
            'Fixed explicit disposable native fixture required')
    admitted.trusted(SCRIPT)
    keys=('GITHUB_ACTIONS','RUNNER_ENVIRONMENT','GITHUB_REPOSITORY','GITHUB_REF',
          'GITHUB_WORKFLOW_REF','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')
    context={k:os.environ.get(k,'') for k in keys}
    decoder,manifest,previous=admitted.source(context)
    import native_voice as voice
    import native_voice_preserve as preserve
    require(not voice.INSTALL_CONTRACT_ADMITTED,'Production gate must remain closed')
    original_units=voice.UNITS
    suffix=secrets.token_hex(8)
    mapping={name:'agpc-voice-ci-'+suffix+'-'+str(i)+'.service'
             for i,name in enumerate((*voice.UNITS,*preserve.SHARED))}
    units=tuple(mapping.values())
    root=Path('/var/lib')/('agpc-voice-preserve-ci-'+suffix)
    root.mkdir(mode=0o700)
    preserve.ROOT=root
    voice.UNITS=tuple(mapping[n] for n in voice.UNITS)
    preserve.AGENTS=tuple(mapping[n] for n in preserve.AGENTS)
    preserve.RESTART=tuple(mapping[n] for n in preserve.RESTART)
    preserve.SHARED=tuple(mapping[n] for n in preserve.SHARED)
    created=[]
    command=decoder.core.run
    try:
        for name in units:
            path=Path('/usr/lib/systemd/system')/name
            require(not os.path.lexists(path),'Fixture unit must be new')
            admitted.trusted(path.parent,directory=True)
            with path.open('x') as out:
                out.write('[Unit]\nDescription=Disposable Voice state fixture\n[Service]\n'
                    'Type=oneshot\nRemainAfterExit=yes\nExecStart=/usr/bin/true\n'
                    '[Install]\nWantedBy=multi-user.target\n')
            path.chmod(0o644);created.append(path)
        command(['/usr/bin/systemctl','daemon-reload'])
        command(['/usr/bin/systemctl','enable',*units])
        command(['/usr/bin/systemctl','start',*preserve.RESTART,*preserve.SHARED])
        baseline=preserve.snapshot()
        stage=root/('agpc-voice-package-'+secrets.token_hex(16));stage.mkdir(mode=0o700)
        preserve.mask(stage,baseline)
        masked={name:preserve.show(name) for name in voice.UNITS}
        require(all(v['UnitFileState']=='masked' and v['ActiveState']=='inactive'
                    for v in masked.values()),'Every owned unit must remain masked and stopped')
        preserve.preserved(baseline)
        # A changed final mask must refuse before ANY previous mask is removed.
        selected=voice.UNITS[-1];mask=preserve.MASK_ROOT/selected;retained=stage/'retained-mask'
        mask.rename(retained);mask.symlink_to('/dev/null')
        foreign_refused=False
        try: preserve.restore(stage,baseline)
        except decoder.core.OwnerInspectionHeld: foreign_refused=True
        require(foreign_refused and all(os.path.islink(preserve.MASK_ROOT/name) for name in voice.UNITS),
                'Foreign mask must leave the entire hold intact')
        mask.unlink();retained.rename(mask)
        preserve.restore(stage,baseline)
        final={name:preserve.show(name) for name in (*voice.UNITS,*preserve.SHARED)}
        require(all(final[name]['ActiveState']=='inactive' and final[name]['UnitFileState']=='enabled'
                    for name in preserve.AGENTS),'Idle enabled agents must not activate')
        require(not any(os.path.lexists(preserve.MASK_ROOT/name) for name in voice.UNITS),
                'Completed fixture masks must be removed')
        print(json.dumps(dict(schema='agpc-voice.preserve-native-fixture/v1',github=context,
            source_commit=manifest['installer_commit'],
            source_manifest_sha256=hashlib.sha256(admitted.trusted(admitted.PACKET/'SOURCE.json').read_bytes()).hexdigest(),
            script_sha256=hashlib.sha256(admitted.trusted(SCRIPT).read_bytes()).hexdigest(),
            lifecycle_result_sha256=hashlib.sha256(admitted.trusted(previous).read_bytes()).hexdigest(),
            fixture_unit_map=mapping,baseline=baseline,masked=masked,final=final,
            foreign_mask_refused_before_unlink=foreign_refused,native_service_preservation_passed=True,
            normal_entry_acceptance=False,production_host_acceptance=False,telephone_acceptance=False),sort_keys=True))
    finally:
        # Only these new disposable fixtures may be cleaned up. Production
        # failure handling never takes this cleanup path.
        for name in units:
            path=preserve.MASK_ROOT/name
            if path.is_symlink() and os.readlink(path)=='/dev/null':path.unlink()
        command(['/usr/bin/systemctl','daemon-reload'])
        command(['/usr/bin/systemctl','stop',*units])
        command(['/usr/bin/systemctl','disable',*units])
        for path in created:path.unlink()
        command(['/usr/bin/systemctl','daemon-reload'])
        voice.UNITS=original_units


if __name__=='__main__':main()
