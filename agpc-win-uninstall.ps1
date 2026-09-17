#requires -Version 5.1
<#
.SYNOPSIS
Permanently remove one explicitly selected Ubuntu distribution and its AGPC tasks.
.EXAMPLE
.\agpc-win-uninstall.ps1 -Distro Ubuntu-24.04 -Plan
.EXAMPLE
.\agpc-win-uninstall.ps1 -Distro Ubuntu-24.04
.NOTES
Deletes ALL data in the selected Ubuntu. WSL and other distributions remain installed.
Run under the same Windows account used for installation. Existing setup logs are retained.
#>
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('Ubuntu-24.04','Ubuntu-26.04','Ubuntu')]
    [string]$Distro,
    [switch]$Plan,
    [ValidatePattern('^S-1-[0-9-]+$')]
    [string]$OwnerSid
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:UninstallPath = $PSCommandPath
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
function Get-DistroNames {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (Test-Path $key) {
        Get-ChildItem $key | ForEach-Object {
            $record = Get-ItemProperty $_.PSPath
            if ($record.PSObject.Properties['DistributionName']) { $record.DistributionName }
        }
    }
}
function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Remove-AgpcDistribution {
    [CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
    param([string]$SelectedDistro,[string]$Sid,[string]$Wsl)
    $names = @("AGPC-Ubuntu-$Sid-$SelectedDistro","AGPC-Setup-$Sid-$SelectedDistro")
    $present = $SelectedDistro -in @(Get-DistroNames)
    if (-not $PSCmdlet.ShouldProcess($SelectedDistro, 'PERMANENTLY DELETE all Ubuntu files and remove its AGPC startup/resume tasks')) { return 0 }
    $tasks = @(Get-ScheduledTask | Where-Object { $_.TaskPath -eq '\' -and $_.TaskName -in $names })
    foreach ($task in $tasks) { Stop-ScheduledTask -TaskName $task.TaskName -TaskPath '\' }
    if ($present) {
        $null = Invoke-Native $Wsl @('--unregister',$SelectedDistro)
        if ($SelectedDistro -in @(Get-DistroNames)) { throw 'Ubuntu is still registered. Startup tasks have been retained.' }
    }
    foreach ($task in $tasks) { Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath '\' -Confirm:$false }
    Write-Host "[AGPC] Removed $SelectedDistro and its AGPC tasks. WSL and other distributions are retained."
    Write-Host 'Windows setup logs are retained under LOCALAPPDATA\AGPC-Win.'
    return 0
}
function Invoke-WindowsUninstall {
    if ($Plan) {
        Write-Host "Plan only: permanently delete distribution $Distro and all its files; remove its AGPC startup/resume tasks."
        Write-Host 'Retain WSL, other distributions, and Windows setup logs.'
        return 0
    }
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess) { throw 'Run in 64-bit Windows PowerShell.' }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($OwnerSid -and $OwnerSid -ne $sid) { throw 'Use the original Windows account that owns Ubuntu.' }
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    if (-not (Test-Path $wsl)) { throw 'WSL is unavailable.' }
    if (-not $WhatIfPreference -and -not (Test-Administrator)) {
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $arguments = '-NoProfile -File "{0}" -Distro {1} -OwnerSid {2}' -f $script:UninstallPath,$Distro,$sid
        $child = Start-Process -FilePath $powershell -Verb RunAs -ArgumentList $arguments -Wait -PassThru
        return $child.ExitCode
    }
    return Remove-AgpcDistribution -SelectedDistro $Distro -Sid $sid -Wsl $wsl
}
if ($MyInvocation.InvocationName -ne '.') {
    try { exit (Invoke-WindowsUninstall) }
    catch { Write-Error ("AGPC Windows uninstall stopped: " + $_.Exception.Message) -ErrorAction Continue; exit 1 }
}
