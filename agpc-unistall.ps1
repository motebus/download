#requires -Version 5.1
<#
.SYNOPSIS
Remove AGPC packages from an existing Ubuntu while retaining Ubuntu and owner data.
.EXAMPLE
.\agpc-unistall.ps1 -Distro Ubuntu -Plan
.EXAMPLE
.\agpc-unistall.ps1 -Distro Ubuntu
.NOTES
The filename preserves the requested "unistall" spelling.
Runs the official Linux uninstall.sh. It does not remove Ubuntu or Windows startup tasks.
#>
[CmdletBinding()]
param(
    [ValidateSet('Ubuntu-24.04','Ubuntu-26.04','Ubuntu')]
    [string]$Distro,
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
$script:UninstallLinux = @'
#!/usr/bin/env bash
set -euo pipefail
stage=$(mktemp -d /tmp/agpc-uninstall-download.XXXXXXXX)
trap 'rm -f -- "$stage/uninstall.sh"; rmdir -- "$stage"' EXIT
curl -fsSL --retry 3 --connect-timeout 20 --max-time 180 \
    https://motebus.github.io/download/uninstall.sh -o "$stage/uninstall.sh"
bash -n "$stage/uninstall.sh"
bash "$stage/uninstall.sh" "$1"
'@
function Invoke-AgpcUninstall {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess) { throw 'Run in 64-bit Windows PowerShell.' }
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    if (-not (Test-Path $wsl)) { throw 'WSL is unavailable.' }
    $selected = Select-Ubuntu @(Get-UbuntuRecords) $Distro
    if (-not $Plan) {
        Write-Host "Remove AGPC packages in $selected; retain Ubuntu, user data, models, Vaults and configuration."
        if ((Read-Host 'Type REMOVE to continue') -cne 'REMOVE') { throw 'Removal cancelled.' }
    }
    $stage = Join-Path $env:TEMP ('agpc-uninstall-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    $path = Join-Path $stage 'uninstall.sh'
    Write-Utf8Lf $path $script:UninstallLinux
    $linuxPath = Invoke-Native $wsl @('-d',$selected,'-u','root','--exec','wslpath','-a','-u',$path) -Capture
    if (-not $linuxPath.Trim().StartsWith('/')) { throw 'Could not resolve the Ubuntu uninstall path.' }
    $mode = if ($Plan) { '--plan' } else { '--yes' }
    $null = Invoke-Native $wsl @('-d',$selected,'-u','root','--exec','bash',$linuxPath.Trim(),$mode)
    Remove-Item -LiteralPath $path
    Remove-Item -LiteralPath $stage
    if (-not $Plan) { Write-Host '[AGPC] Package removal completed; Ubuntu and its startup configuration were retained.' }
    return 0
}
if ($MyInvocation.InvocationName -ne '.') {
    try { exit (Invoke-AgpcUninstall) }
    catch { Write-Error ("AGPC uninstall stopped: " + $_.Exception.Message) -ErrorAction Continue; exit 1 }
}
