#!/usr/bin/python3
"""Strict lifecycle observation mock; real deb-systemd-helper owns its state."""
import json,sys
from pathlib import Path
assert Path('/.cx-rename-fixture').exists()
a=sys.argv[1:]
with Path('/tmp/systemctl.log').open('a') as f:f.write(json.dumps(a)+'\n')
ops=[v for v in a if v in ('preset','is-enabled','is-active','stop','start','restart','daemon-reload')]
if len(ops)!=1:raise SystemExit('unexpected systemctl operation: '+repr(a))
op=ops[0];units=[v for v in a if v.endswith('.service')]
for unit in units:
 if unit not in ('cx-node.service','cx-agent.service','cx-mesh.service','agent-exec.service','cx-pivot.service','cx-adapter.service'):raise SystemExit('unexpected unit')
 actual=Path('/lib/systemd/system')/unit
 canonical=actual.resolve().name if actual.exists() else unit
 state=Path('/tmp/active-'+canonical)
 masked=any((Path(base)/unit).is_symlink() and (Path(base)/unit).readlink()==Path('/dev/null') for base in ['/etc/systemd/system','/run/systemd/system'])
 if op=='preset':
  if masked:sys.exit(1)
  for target in ('multi-user.target','moted.service'):
   link=Path('/etc/systemd/system')/(target+'.wants')/unit;link.parent.mkdir(parents=True,exist_ok=True)
   if not link.is_symlink():link.symlink_to('/lib/systemd/system/'+unit)
 elif op=='is-enabled':
  if masked:print('masked');sys.exit(1)
  yes=(Path('/etc/systemd/system/multi-user.target.wants')/unit).is_symlink();print('enabled' if yes else 'disabled');sys.exit(0 if yes else 1)
 elif op=='is-active':sys.exit(0 if state.exists() and state.read_text()=='active' else 3)
 elif op=='stop':state.write_text('inactive')
 elif op in ('start','restart'):
  if masked:sys.exit(1)
  state.write_text('active')
if op!='daemon-reload' and not units:raise SystemExit('missing unit')
