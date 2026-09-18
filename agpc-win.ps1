#requires -Version 5.1
<#
.SYNOPSIS
Install AGPC through WSL 2, Ubuntu and the official Linux agpc.sh.
.EXAMPLE
.\agpc-win.ps1
.EXAMPLE
.\agpc-win.ps1 -Distro Ubuntu
.EXAMPLE
.\agpc-win.ps1 -Distro Ubuntu -Plan
.NOTES
Requests administrator elevation. Never reboots automatically.
Passwords are entered locally and never saved by this script.
#>
[CmdletBinding()]
param(
    [ValidateSet('Ubuntu-24.04','Ubuntu-26.04','Ubuntu')]
    [string]$Distro = 'Ubuntu-26.04',
    [ValidatePattern('^[a-z_][a-z0-9_-]{0,31}$')]
    [string]$UserName = 'jujue',
    [switch]$NoAutoStart,
    [switch]$SkipPassword,
    [switch]$Plan,
    [switch]$Resume,
    [ValidatePattern('^S-1-[0-9-]+$')]
    [string]$OwnerSid
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:InstallerPath = $PSCommandPath
function Invoke-Native {
    param([string]$File, [string[]]$Arguments, [switch]$Capture, [int[]]$Allowed = @(0))
    if ($Capture) {
        $lines = @(& $File @Arguments)
        $code = $LASTEXITCODE
        $output = ($lines -join [Environment]::NewLine).Replace([string][char]0, '')
    } else {
        & $File @Arguments | Out-Host
        $code = $LASTEXITCODE
    }
    if ($code -notin $Allowed) { throw "$File failed with exit code $code. Setup did not complete." }
    if ($Capture) { return $output }
    return $code
}
function Write-Step {
    param([string]$Message)
    Write-Host ("[AGPC] " + $Message) -ForegroundColor Cyan
    if ($script:LogPath) {
        Add-Content -LiteralPath $script:LogPath -Value ("{0:o} {1}" -f (Get-Date), $Message) -Encoding UTF8
    }
}
function Write-Utf8Lf {
    param([string]$Path, [string]$Content)
    [IO.File]::WriteAllText($Path, $Content.Replace("$([char]13)$([char]10)", "$([char]10)"), (New-Object Text.UTF8Encoding($false)))
}
function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Save-State {
    param([string]$Phase)
    $script:State.Phase = $Phase
    $temporary = Join-Path $script:StateDir 'state.next.json'
    Write-Utf8Lf $temporary ($script:State | ConvertTo-Json)
    Move-Item -LiteralPath $temporary -Destination $script:StatePath -Force
}
function Get-DistroNames {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (Test-Path $key) {
        Get-ChildItem $key | ForEach-Object {
            $record = Get-ItemProperty $_.PSPath
            if ($record.PSObject.Properties['DistributionName']) { $record.DistributionName }
        }
    }
}
function Register-Resume {
    $retained = Join-Path $script:StateDir 'agpc-win.ps1'
    if ([IO.Path]::GetFullPath($script:InstallerPath) -ne [IO.Path]::GetFullPath($retained)) {
        Copy-Item -LiteralPath $script:InstallerPath -Destination $retained -Force
    }
    $arguments = '-NoProfile -File "{0}" -Resume -Distro {1} -OwnerSid {2}' -f $retained, $Distro, $OwnerSid
    $action = New-ScheduledTaskAction -Execute $script:PowerShellExe -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $OwnerSid
    $principal = New-ScheduledTaskPrincipal -UserId $OwnerSid -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $script:ResumeTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Resume requested AGPC setup at the next Windows login.' -Force | Out-Null
}
function Invoke-LinuxFile {
    param([string]$Name, [string]$Content, [string[]]$Arguments = @(), [int[]]$Allowed = @(0))
    $path = Join-Path $script:StateDir $Name
    Write-Utf8Lf $path $Content
    $linuxPath = Invoke-Native $script:WslExe @('-d',$Distro,'-u','root','--exec','wslpath','-a','-u',$path) -Capture
    if (-not $linuxPath.Trim().StartsWith('/')) { throw 'Could not resolve the Ubuntu bootstrap path.' }
    return Invoke-Native $script:WslExe (@('-d',$Distro,'-u','root','--exec','bash',$linuxPath.Trim()) + $Arguments) -Allowed $Allowed
}
function Enable-UbuntuStartup {
    $path = Join-Path $script:StateDir 'start-ubuntu.ps1'
    $content = "& '$script:WslExe' -d '$Distro' -u '$UserName' --exec /bin/sleep infinity" + [char]10 + 'exit $LASTEXITCODE' + [char]10
    Write-Utf8Lf $path $content
    $action = New-ScheduledTaskAction -Execute $script:PowerShellExe -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f $path)
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT30S'
    $principal = New-ScheduledTaskPrincipal -UserId $OwnerSid -LogonType S4U -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $script:StartupTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Start AGPC Ubuntu after Windows boot under its registered owner, without an interactive login.' -Force | Out-Null
    Start-ScheduledTask -TaskName $script:StartupTask
}
$script:PrepareLinux = @'
#!/usr/bin/env bash
set -euo pipefail
user=$1
. /etc/os-release
case "$ID:$VERSION_ID:$(dpkg --print-architecture)" in
    ubuntu:24.04:amd64|ubuntu:26.04:amd64) ;;
    *) echo 'AGPC requires Ubuntu 24.04 or 26.04 amd64.' >&2; exit 1 ;;
esac
if [[ $(ps -p 1 -o comm=) != systemd ]]; then
    python3 - <<'PY'
from pathlib import Path
import configparser,re
p=Path('/etc/wsl.conf')
text=p.read_text() if p.exists() else ''
check=configparser.ConfigParser(strict=True)
check.read_string(text)
lines=text.splitlines(keepends=True)
section=None;boot_start=None;boot_end=len(lines);key=None
for i,line in enumerate(lines):
    match=re.match(r'\s*\[([^]]+)\]',line)
    if match:
        if section=='boot':boot_end=i
        section=match[1].strip()
        if section=='boot':boot_start=i
    elif section=='boot' and re.match(r'\s*systemd\s*=',line):key=i
if key is not None:lines[key]='systemd=true\n'
elif boot_start is not None:
    if boot_end and not lines[boot_end-1].endswith('\n'):lines[boot_end-1]+='\n'
    lines.insert(boot_end,'systemd=true\n')
else:lines.append('\n[boot]\nsystemd=true\n')
p.write_text(''.join(lines))
PY
    echo 'systemd configured; the selected Ubuntu distribution needs a restart.'
    exit 42
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates gnupg python3 sudo
if ! id "$user" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash --groups sudo "$user"
fi
python3 - "$user" <<'PY'
import pwd,sys
u=pwd.getpwnam(sys.argv[1])
assert 1000<=u.pw_uid<65534 and not u.pw_shell.endswith(('nologin','/false')), 'An ordinary login account is required.'
PY
usermod -aG sudo "$user"
'@
$script:InstallLinux = @'
#!/usr/bin/env bash
set -euo pipefail
user=$1
stage=/var/lib/agpc-win
mkdir -p "$stage"
curl --fail --silent --show-error --location --retry 3 --connect-timeout 20 \
    --max-time 180 --output "$stage/agpc.download.sh" \
    https://motebus.github.io/download/agpc.sh
bash -n "$stage/agpc.download.sh"
mv "$stage/agpc.download.sh" "$stage/agpc.sh"
bash "$stage/agpc.sh" --yes --user "$user"
apt-get check
audit=$(dpkg --audit)
[[ -z $audit ]] || { printf '%s\n' "$audit" >&2; exit 1; }
python3 - "$stage/result.json" "$user" <<'PY'
import json,subprocess,sys
packages={}
query=chr(36)+'{Status}\n'+chr(36)+'{Version}'
for name in ('agent-sphere','agent-ultra','agpc-manager','agent-apps'):
    raw=subprocess.check_output(['dpkg-query','-W','-f='+query,name],text=True).splitlines()
    assert len(raw)==2 and raw[0]=='install ok installed',name+' is not fully configured'
    packages[name]=raw[1]
body={'schema':'agpc.windows-install/v1','user':sys.argv[2],'packages':packages,
      'installation_verified':True,'remote_reachability':'not-tested','full_runtime_ready':False}
with open(sys.argv[1],'w') as f:json.dump(body,f,indent=2);f.write('\n')
print(json.dumps(body))
PY
'@
function Invoke-AgpcSetup {
    $script:LogPath = $null
    if ($Plan) {
        Write-Host 'AGPC Windows setup plan (no changes):'
        Write-Host "  WSL 2 -> $Distro (Ubuntu 24.04/26.04 amd64) -> user $UserName"
        Write-Host '  Resume at Windows login if a Windows restart is needed.'
        Write-Host '  Install prerequisites, then https://motebus.github.io/download/agpc.sh'
        Write-Host "  Ubuntu boot startup: $(-not $NoAutoStart)"
        Write-Host "  Local password entry skipped: $([bool]$SkipPassword)"
        return 0
    }
    if ($env:OS -ne 'Windows_NT') { throw 'Run agpc-win.ps1 on Windows.' }
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($arch -ne 'AMD64' -or -not [Environment]::Is64BitProcess) { throw 'Use 64-bit PowerShell on an x64 Windows PC.' }
    if ([Environment]::OSVersion.Version.Build -lt 19041) { throw 'Windows build 19041 or newer is required.' }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($OwnerSid -and $OwnerSid -ne $sid) { throw 'Run as the original Windows user; WSL belongs to that account.' }
    if (-not $OwnerSid) { $OwnerSid = $sid }
    $script:PowerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $script:WslExe = Join-Path $env:SystemRoot 'System32\wsl.exe'
    if (-not (Test-Administrator)) {
        $arguments = '-NoProfile -File "{0}" -Distro {1} -UserName {2} -OwnerSid {3}' -f $script:InstallerPath,$Distro,$UserName,$OwnerSid
        foreach ($flag in @('NoAutoStart','SkipPassword','Resume')) {
            if (Get-Variable -Name $flag -ValueOnly) { $arguments += " -$flag" }
        }
        $child = Start-Process -FilePath $script:PowerShellExe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
        return $child.ExitCode
    }
    $script:StateDir = Join-Path $env:LOCALAPPDATA ("AGPC-Win\" + $Distro)
    $script:StatePath = Join-Path $script:StateDir 'state.json'
    $script:ResumeTask = "AGPC-Setup-$OwnerSid-$Distro"
    $script:StartupTask = "AGPC-Ubuntu-$OwnerSid-$Distro"
    New-Item -ItemType Directory -Path $script:StateDir -Force | Out-Null
    $script:LogPath = Join-Path $script:StateDir 'setup.log'
    if ($Resume) {
        $saved = Get-Content -LiteralPath $script:StatePath -Raw | ConvertFrom-Json
        if ($saved.OwnerSid -ne $OwnerSid -or $saved.Distro -ne $Distro -or $saved.UserName -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw 'Saved options do not match this Windows account.' }
        $UserName = [string]$saved.UserName
        $NoAutoStart = [bool]$saved.NoAutoStart
        $SkipPassword = [bool]$saved.SkipPassword
        $script:State = $saved
    } else {
        $script:State = [pscustomobject]@{OwnerSid=$OwnerSid;Distro=$Distro;UserName=$UserName;NoAutoStart=[bool]$NoAutoStart;SkipPassword=[bool]$SkipPassword;Phase='begin'}
    }
    Save-State 'windows'
    Register-Resume
    Write-Step 'Checking WSL prerequisites.'
    $feature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
    & $script:WslExe --version | Out-Host
    $hasWsl = $LASTEXITCODE -eq 0
    if ($feature.State -ne 'Enabled' -or -not $hasWsl) {
        $code = Invoke-Native $script:WslExe @('--install','--no-distribution','--web-download') -Allowed @(0,3010)
        if ($feature.State -ne 'Enabled' -or $code -eq 3010) {
            Save-State 'restart-required'
            Write-Step 'Restart Windows when convenient. Setup resumes after login to this same account.'
            return 3010
        }
    }
    $helpText = Invoke-Native $script:WslExe @('--help') -Capture -Allowed @(0,1)
    if ($helpText -notmatch '--manage') { $null = Invoke-Native $script:WslExe @('--update','--web-download') }
    Save-State 'ubuntu'
    $freshDistro = $Distro -notin @(Get-DistroNames)
    if ($freshDistro) {
        Write-Step "Installing $Distro."
        $code = Invoke-Native $script:WslExe @('--install','-d',$Distro,'--web-download','--no-launch','--version','2') -Allowed @(0,3010)
        if ($code -eq 3010) {
            Save-State 'restart-required'
            Write-Step 'Restart Windows, then log in to resume setup.'
            return 3010
        }
    }
    $distroRecord = Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.PSObject.Properties['DistributionName'] -and $_.DistributionName -eq $Distro }
    if (-not $distroRecord -or $distroRecord.Version -ne 2) { throw "WSL 2 is required. Convert the selected distribution with: wsl --set-version $Distro 2" }
    $null = Invoke-Native $script:WslExe @('-d',$Distro,'-u','root','--exec','true')
    Write-Step "Preparing Ubuntu and user $UserName."
    $code = Invoke-LinuxFile 'prepare.sh' $script:PrepareLinux @($UserName) -Allowed @(0,42)
    if ($code -eq 42) {
        Save-State 'ubuntu-restart-required'
        if (-not $freshDistro) { throw "Save work in $Distro, run 'wsl --terminate $Distro', then rerun this installer to activate systemd." }
        $null = Invoke-Native $script:WslExe @('--terminate',$Distro)
        $null = Invoke-LinuxFile 'prepare.sh' $script:PrepareLinux @($UserName)
    }
    $null = Invoke-Native $script:WslExe @('--manage',$Distro,'--set-default-user',$UserName)
    $passwordState = Invoke-Native $script:WslExe @('-d',$Distro,'-u','root','--exec','passwd','-S',$UserName) -Capture
    if (-not $SkipPassword -and $passwordState -notmatch '^\S+\s+P\s') {
        Write-Step "Set $UserName's Linux password locally. Input is not echoed or saved."
        $null = Invoke-Native $script:WslExe @('-d',$Distro,'-u','root','--exec','passwd',$UserName)
    }
    Save-State 'agpc'
    Write-Step 'Running official agpc.sh. Large package downloads can take time.'
    $null = Invoke-LinuxFile 'install.sh' $script:InstallLinux @($UserName)
    Save-State 'windows-integration'
    if (-not $NoAutoStart) { Enable-UbuntuStartup; Write-Step 'Ubuntu automatic startup enabled after Windows boot.' }
    $actual = Invoke-Native $script:WslExe @('-d',$Distro,'--exec','whoami') -Capture
    if ($actual.Trim() -ne $UserName) { throw 'Ubuntu default user verification failed.' }
    Save-State 'complete'
    Unregister-ScheduledTask -TaskName $script:ResumeTask -Confirm:$false
    Write-Step 'Installation completed. Full runtime readiness and remote connectivity need separate configuration.'
    Write-Host "Open Ubuntu: wsl -d $Distro"
    Write-Host 'Inside Ubuntu: sudo agpc-manager'
    if ($SkipPassword) { Write-Host "Set password: wsl -d $Distro -u root -- passwd $UserName" }
    Write-Host "Setup log: $script:LogPath"
    return 0
}
if ($MyInvocation.InvocationName -ne '.') {
    try { exit (Invoke-AgpcSetup) }
    catch {
        Write-Error ("AGPC setup stopped: " + $_.Exception.Message) -ErrorAction Continue
        Write-Host 'Fix the reported issue and rerun the same command. Existing Ubuntu data is retained.'
        exit 1
    }
}
