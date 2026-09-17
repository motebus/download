#requires -Version 5.1
param([switch]$SkipLinuxChecks)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
. (Join-Path $root 'agpc-win.ps1')
$token=$null;$errors=$null
[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'agpc-win.ps1'),[ref]$token,[ref]$errors) | Out-Null
if ($errors.Count) { throw ($errors | Out-String) }
$ps=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$badExitWasRejected=$false
try { $null=Invoke-Native $ps @('-NoProfile','-Command','exit 17') }
catch { if ($_.Exception.Message -match 'exit code 17') {$badExitWasRejected=$true} else {throw} }
if (-not $badExitWasRejected) { throw 'A failed native command was incorrectly accepted.' }
$allowed=Invoke-Native $ps @('-NoProfile','-Command','exit 42') -Allowed @(0,42)
if ($allowed -ne 42) { throw 'The expected restart signal was not retained.' }
$result=Invoke-Native $ps @('-NoProfile','-Command',"[Console]::Write('jujue')") -Capture
if ($result -ne 'jujue') { throw 'Native output capture changed the selected username.' }
$null=Invoke-Native $ps @('-NoProfile','-File',(Join-Path $root 'agpc-win.ps1'),'-Plan')
$validation=Join-Path $env:TEMP ('agpc-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $validation -Force | Out-Null
Write-Utf8Lf (Join-Path $validation 'prepare.sh') $script:PrepareLinux
Write-Utf8Lf (Join-Path $validation 'install.sh') $script:InstallLinux
if (-not $SkipLinuxChecks) {
$linuxRoot=Invoke-Native 'wsl.exe' @('-d','Ubuntu','--exec','wslpath','-a','-u',$validation) -Capture
foreach($name in @('prepare.sh','install.sh')) {
    $null=Invoke-Native 'wsl.exe' @('-d','Ubuntu','--exec','bash','-n',($linuxRoot.Trim()+'/'+$name))
}
$pythonTest=@'
import ast,pathlib,re,tempfile
root=pathlib.Path(__file__).parent
prepare=(root/'prepare.sh').read_text()
install=(root/'install.sh').read_text()
blocks=[]
for text in (prepare,install):
    blocks.extend(re.findall(r"<<'PY'\n(.*?)\nPY",text,re.S))
for block in blocks:ast.parse(block)
config_code=blocks[0]
cases=[
    ('', '[boot]\nsystemd=true'),
    ('[boot]\nsystemd=false\n[automount]\nenabled=false\n', 'enabled=false'),
    ('# retained\n[boot]\n# option\n[interop]\nenabled=true\n', '# retained'),
    ('[network]\ngenerateHosts=false\n[boot]\nsystemd=false', 'generateHosts=false'),
    ('[boot]\ncommand=echo-ready', 'command=echo-ready'),
]
import configparser
with tempfile.TemporaryDirectory() as folder:
    p=pathlib.Path(folder)/'wsl.conf'
    for source,preserved in cases:
        p.write_text(source)
        code=config_code.replace("p=Path('/etc/wsl.conf')","p=Path("+repr(str(p))+")")
        exec(compile(code,'systemd-config','exec'),{})
        result=p.read_text();parsed=configparser.ConfigParser();parsed.read_string(result)
        assert parsed['boot']['systemd']=='true'
        assert preserved in result
        exec(compile(code,'systemd-config','exec'),{})
        assert p.read_text()==result,'Repeated preparation changed the configuration again.'
assert 'https://motebus.github.io/download/agpc.sh' in install
print('PASS: Bash/Python syntax and systemd configuration preservation/idempotence.')
'@
Write-Utf8Lf (Join-Path $validation 'check.py') $pythonTest
$null=Invoke-Native 'wsl.exe' @('-d','Ubuntu','--exec','python3',($linuxRoot.Trim()+'/check.py'))
}
$source = Get-Content -LiteralPath (Join-Path $root 'agpc-win.ps1') -Raw
if ($source -match '(?i)docker') { throw 'Unexpected Docker operation or option remains in the installer.' }
$bootFunction = (Get-Command Enable-UbuntuStartup).Definition
if ($bootFunction -notmatch '-AtStartup' -or $bootFunction -notmatch '-LogonType S4U' -or $bootFunction -match '-AtLogOn') {
    throw 'Runtime startup is not configured for unattended Windows boot.'
}
# Load the command module before mocks, so module autoload cannot replace them.
Import-Module ScheduledTasks
# Build real task objects, but intercept registration/start so no host task changes.
$script:StateDir=$validation
$script:PowerShellExe=$ps
$script:WslExe=Join-Path $env:SystemRoot 'System32\wsl.exe'
$script:StartupTask='AGPC-Test-Only'
$OwnerSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$Distro='Ubuntu'
$UserName='jujue'
function Register-ScheduledTask {
    param($TaskName,$Action,$Trigger,$Principal,$Settings,$Description,[switch]$Force)
    $script:TaskUnderTest=@{Name=$TaskName;Action=$Action;Trigger=$Trigger;Principal=$Principal;Settings=$Settings}
}
function Start-ScheduledTask { param($TaskName) $script:StartedTestTask=$TaskName }
Enable-UbuntuStartup
if ($script:TaskUnderTest.Trigger.CimClass.CimClassName -ne 'MSFT_TaskBootTrigger') { throw 'A login trigger was used instead of boot.' }
if ([string]$script:TaskUnderTest.Principal.LogonType -ne 'S4U') { throw 'Boot task unexpectedly requires an interactive login or stored password.' }
if ($script:TaskUnderTest.Trigger.Delay -ne 'PT30S' -or $script:TaskUnderTest.Settings.ExecutionTimeLimit -ne 'PT0S') { throw 'Boot delay or keepalive lifetime is wrong.' }
if ($script:StartedTestTask -ne 'AGPC-Test-Only') { throw 'The configured task was not started.' }
$bootTokens=$null;$bootErrors=$null
[Management.Automation.Language.Parser]::ParseFile((Join-Path $validation 'start-ubuntu.ps1'),[ref]$bootTokens,[ref]$bootErrors) | Out-Null
if ($bootErrors.Count) { throw ($bootErrors | Out-String) }
Write-Host 'PASS: Boot trigger, S4U owner context, delay, unlimited lifetime; task registration was mocked.'

Write-Host 'PASS: PowerShell 5.1, native failures/restart signals, read-only plan, generated Linux scripts.'

. (Join-Path $root 'agpc.ps1')
$updateTokens=$null;$updateErrors=$null
[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'agpc.ps1'),[ref]$updateTokens,[ref]$updateErrors) | Out-Null
if ($updateErrors.Count) { throw ($updateErrors | Out-String) }
$null=Invoke-Native $ps @('-NoProfile','-File',(Join-Path $root 'agpc.ps1'),'-Plan')
$one=[pscustomobject]@{DistributionName='Ubuntu';Version=2}
$two=[pscustomobject]@{DistributionName='Ubuntu-24.04';Version=2}
if ((Select-Ubuntu @($one) '') -ne 'Ubuntu') {throw 'Updater failed to select the existing Ubuntu.'}
if ((Select-Ubuntu @($one,$two) 'Ubuntu-24.04') -ne 'Ubuntu-24.04') {throw 'Explicit distribution selection failed.'}
foreach ($case in @(
    @{Records=@();Requested='';Message='No matching'},
    @{Records=@($one,$two);Requested='';Message='Multiple Ubuntu'},
    @{Records=@($one);Requested='Ubuntu-26.04';Message='No matching'},
    @{Records=@([pscustomobject]@{DistributionName='Ubuntu';Version=1});Requested='';Message='WSL 2'}
)) {
    $caught=$false
    try { $null=Select-Ubuntu $case.Records $case.Requested }
    catch { if ($_.Exception.Message -notmatch $case.Message) {throw};$caught=$true }
    if (-not $caught) {throw 'Invalid update target was accepted.'}
}
$updateSource=Get-Content -LiteralPath (Join-Path $root 'agpc.ps1') -Raw
if ($updateSource -match 'Register-ScheduledTask|Start-Process|useradd|usermod|--set-default-user|--install|(?i:docker)') {throw 'Updater unexpectedly provisions Windows or Ubuntu.'}
Write-Utf8Lf (Join-Path $validation 'update.sh') $script:UpdateLinux
if (-not $SkipLinuxChecks) {
    $null=Invoke-Native 'wsl.exe' @('-d','Ubuntu','--exec','bash','-n',($linuxRoot.Trim()+'/update.sh'))
}
Write-Host 'PASS: Standalone updater parsing, read-only plan, distribution selection and invalid target rejection.'

foreach ($name in @('agpc-win-uninstall.ps1','agpc-unistall.ps1')) {
    $uninstallTokens=$null;$uninstallErrors=$null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path $root $name),[ref]$uninstallTokens,[ref]$uninstallErrors) | Out-Null
    if ($uninstallErrors.Count) {throw ($uninstallErrors | Out-String)}
}
$null=Invoke-Native $ps @('-NoProfile','-File',(Join-Path $root 'agpc-win-uninstall.ps1'),'-Distro','Ubuntu','-Plan')
. (Join-Path $root 'agpc-win-uninstall.ps1') -Distro Ubuntu
$script:FixtureDistros=@('Ubuntu','Debian')
$script:RemovedTasks=@()
$script:StoppedTasks=@()
$script:WslCalls=0
$fixtureSid='S-1-5-21-1234'
function Get-DistroNames { $script:FixtureDistros }
function Get-ScheduledTask {
    @(
        [pscustomobject]@{TaskName="AGPC-Ubuntu-$fixtureSid-Ubuntu";TaskPath='\'},
        [pscustomobject]@{TaskName="AGPC-Setup-$fixtureSid-Ubuntu";TaskPath='\'},
        [pscustomobject]@{TaskName="AGPC-Ubuntu-$fixtureSid-Debian";TaskPath='\'},
        [pscustomobject]@{TaskName='Unrelated';TaskPath='\'}
    )
}
function Stop-ScheduledTask { param($TaskName,$TaskPath) $script:StoppedTasks+=,$TaskName }
function Unregister-ScheduledTask { param($TaskName,$TaskPath,[switch]$Confirm) $script:RemovedTasks+=,$TaskName }
function Invoke-Native {
    param($File,[string[]]$Arguments)
    if ($Arguments.Count -ne 2 -or $Arguments[0] -ne '--unregister' -or $Arguments[1] -ne 'Ubuntu') {throw 'Unexpected distribution removal.'}
    $script:WslCalls++
    $script:FixtureDistros=@('Debian')
    return 0
}
$null=Remove-AgpcDistribution -SelectedDistro Ubuntu -Sid $fixtureSid -Wsl 'fixture-wsl' -WhatIf
if ($script:WslCalls -or $script:RemovedTasks.Count -or $script:StoppedTasks.Count) {throw 'WhatIf changed the system.'}
$null=Remove-AgpcDistribution -SelectedDistro Ubuntu -Sid $fixtureSid -Wsl 'fixture-wsl' -Confirm:$false
if ($script:WslCalls -ne 1 -or $script:RemovedTasks.Count -ne 2 -or $script:FixtureDistros[0] -ne 'Debian') {throw 'Distribution/task removal escaped its selected scope.'}
if ($script:RemovedTasks -contains 'Unrelated' -or ($script:RemovedTasks -match 'Debian').Count) {throw 'Unrelated startup tasks were removed.'}
$script:FixtureDistros=@('Ubuntu','Debian')
$script:RemovedTasks=@()
function Invoke-Native { param($File,[string[]]$Arguments) throw 'fixture unregister failure' }
$refused=$false
try {$null=Remove-AgpcDistribution -SelectedDistro Ubuntu -Sid $fixtureSid -Wsl 'fixture-wsl' -Confirm:$false}
catch {if ($_.Exception.Message -notmatch 'fixture unregister failure') {throw};$refused=$true}
if (-not $refused -or $script:RemovedTasks.Count) {throw 'Failed unregistration incorrectly removed task definitions.'}
Write-Host 'PASS: Windows uninstall scope, WhatIf and failure handling with mocked WSL/tasks.'
