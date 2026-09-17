#requires -Version 5.1
<#
.SYNOPSIS
Update AGPC in an existing, prepared Ubuntu WSL 2 distribution.
.EXAMPLE
.\agpc.ps1
.EXAMPLE
.\agpc.ps1 -Distro Ubuntu -UserName jujue
.NOTES
Run as the Windows account that owns Ubuntu. No Windows elevation is needed.
Use agpc-win.ps1 to install WSL/Ubuntu or configure boot startup on a new PC.
#>
[CmdletBinding()]
param(
    [ValidateSet('Ubuntu-24.04','Ubuntu-26.04','Ubuntu')]
    [string]$Distro,
    [ValidatePattern('^[a-z_][a-z0-9_-]{0,31}$')]
    [string]$UserName = 'jujue',
    [switch]$Plan
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
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
function Write-Utf8Lf {
    param([string]$Path, [string]$Content)
    [IO.File]::WriteAllText($Path, $Content.Replace("$([char]13)$([char]10)", "$([char]10)"), (New-Object Text.UTF8Encoding($false)))
}
function Get-UbuntuRecords {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (Test-Path $key) {
        Get-ChildItem $key | ForEach-Object {
            $record = Get-ItemProperty $_.PSPath
            if ($record.PSObject.Properties['DistributionName'] -and $record.DistributionName -in @('Ubuntu','Ubuntu-24.04','Ubuntu-26.04')) { $record }
        }
    }
}
function Select-Ubuntu {
    param([object[]]$Records, [string]$Requested)
    if ($Requested) { $selected = @($Records | Where-Object { $_.DistributionName -eq $Requested }) }
    else { $selected = @($Records) }
    if ($selected.Count -eq 0) { throw 'No matching Ubuntu installation. Run agpc-win.ps1 to set up a new PC.' }
    if ($selected.Count -gt 1) { throw 'Multiple Ubuntu distributions exist. Select one with -Distro Ubuntu (or its exact distribution name).' }
    if ($selected[0].Version -ne 2) { throw 'The selected Ubuntu must already use WSL 2. Update stopped.' }
    return [string]$selected[0].DistributionName
}
$script:UpdateLinux = @'
#!/usr/bin/env bash
set -euo pipefail
user=$1
# Require a prepared Ubuntu; this updater never provisions the operating system.
. /etc/os-release
case "$ID:$VERSION_ID:$(dpkg --print-architecture)" in
    ubuntu:24.04:amd64|ubuntu:26.04:amd64) ;;
    *) echo 'AGPC requires Ubuntu 24.04 or 26.04 amd64.' >&2; exit 1 ;;
esac
[[ $(ps -p 1 -o comm=) == systemd ]] || { echo 'Ubuntu systemd must already be running. Use agpc-win.ps1 for setup.' >&2; exit 1; }
for tool in curl python3 gpg sudo; do command -v "$tool" >/dev/null || { echo "Missing Ubuntu prerequisite: $tool" >&2; exit 1; }; done
python3 - "$user" <<'PY'
import pwd,sys
u=pwd.getpwnam(sys.argv[1])
assert 1000<=u.pw_uid<65534 and not u.pw_shell.endswith(('nologin','/false')), 'An existing ordinary login account is required.'
PY
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
function Invoke-AgpcUpdate {
    if ($Plan) {
        $target = if ($Distro) { $Distro } else { 'the single installed Ubuntu distribution' }
        Write-Host "AGPC update plan (no changes): $target; existing user $UserName."
        Write-Host 'Check Ubuntu/systemd, run the official agpc.sh, then verify installed packages.'
        return 0
    }
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess) { throw 'Run in 64-bit Windows PowerShell.' }
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    if (-not (Test-Path $wsl)) { throw 'WSL is not installed. Run agpc-win.ps1 first.' }
    $selected = Select-Ubuntu @(Get-UbuntuRecords) $Distro
    $stage = Join-Path $env:TEMP ('agpc-update-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    $path = Join-Path $stage 'update.sh'
    Write-Utf8Lf $path $script:UpdateLinux
    $linuxPath = Invoke-Native $wsl @('-d',$selected,'-u','root','--exec','wslpath','-a','-u',$path) -Capture
    if (-not $linuxPath.Trim().StartsWith('/')) { throw 'Could not resolve the Ubuntu update path.' }
    Write-Host "[AGPC] Updating packages in $selected for $UserName. Downloads can take time."
    $null = Invoke-Native $wsl @('-d',$selected,'-u','root','--exec','bash',$linuxPath.Trim(),$UserName)
    Remove-Item -LiteralPath $path
    Remove-Item -LiteralPath $stage
    Write-Host '[AGPC] Package update completed. Report: /var/lib/agpc-win/result.json'
    Write-Host 'Full runtime readiness and remote connectivity need separate verification.'
    return 0
}
if ($MyInvocation.InvocationName -ne '.') {
    try { exit (Invoke-AgpcUpdate) }
    catch {
        Write-Error ("AGPC update stopped: " + $_.Exception.Message) -ErrorAction Continue
        exit 1
    }
}
