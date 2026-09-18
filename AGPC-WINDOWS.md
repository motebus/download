# AGPC on Windows (preview)

| Script | Use |
| --- | --- |
| `agpc-win.ps1` | New Windows PC: install WSL 2 / Ubuntu, create `jujue`, install AGPC, enable Ubuntu startup after Windows boot. |
| `agpc.ps1` | Existing prepared Ubuntu: update AGPC packages. |
| `agpc-win-uninstall.ps1` | Delete one selected Ubuntu and its AGPC tasks; retain WSL and other distributions. |
| `agpc-unistall.ps1` | Remove AGPC packages; retain Ubuntu and owner data. The requested filename spelling is intentional. |
| `agpc.sh` | Native Linux installation and updates. |

Run PowerShell as the Windows account that owns Ubuntu. Download and run are separate steps.

## New Windows PC

```powershell
curl.exe -fL https://motebus.github.io/download/agpc-win.ps1 -o "$env:TEMP\agpc-win.ps1"
& "$env:TEMP\agpc-win.ps1"
```

Setup requests administrator elevation for the same Windows account. It installs WSL 2 and Ubuntu 26.04 by default, creates `jujue`, asks for its Linux password locally, runs the official Linux installer, and registers a task to start Ubuntu after Windows boot. If Windows needs a restart, restart when convenient and sign in to the same account; setup resumes. It never forces a restart.

The host must be x64 Windows build 19041 or newer, with virtualization available, a local administrator account, and 64-bit PowerShell 5.1 or newer. Windows 11 is recommended. Existing execution policies are respected. Managed PCs may need their administrator to approve/sign these scripts.

| Setup option | Meaning |
| --- | --- |
| `-Plan` | Show the plan without changes. |
| `-Distro Ubuntu-26.04` | Default; also accepts `Ubuntu-24.04` and `Ubuntu`. |
| `-UserName jujue` | Default Linux account and AGPC user. |
| `-NoAutoStart` | Skip creating a boot task; keep any existing task. |
| `-SkipPassword` | Set the Linux password later; does not enable passwordless sudo. |

Only the selected Ubuntu distribution is configured. Existing WSL 1 distributions are not converted automatically. If an existing Ubuntu requires systemd activation, setup asks you to save work and restart that distribution.

Ubuntu starts in the background after Windows boot. The task `AGPC-Ubuntu-<Windows SID>-<Distro>` has a startup trigger, a 30-second delay, and S4U logon as its Windows owner. It keeps a WSL client running without storing a Windows password. S4U cannot access encrypted user files or authenticated network shares. Installation continuation uses a separate login task because password entry may be required; that task is removed on completion.

## Update an existing Ubuntu

```powershell
curl.exe -fL https://motebus.github.io/download/agpc.ps1 -o "$env:TEMP\agpc.ps1"
& "$env:TEMP\agpc.ps1"
```

The updater selects the only installed supported Ubuntu distribution. If several exist, select one explicitly:

```powershell
& "$env:TEMP\agpc.ps1" -Distro Ubuntu -UserName jujue
```

Ubuntu must already be WSL 2, Ubuntu 24.04 or 26.04 amd64, with systemd running, curl, Python 3, GnuPG, sudo and the chosen user available. The default user argument is `jujue`. Updates run as Linux root through the owning Windows account; Windows elevation is unnecessary. The updater changes AGPC packages through the official Linux installer. It does not install WSL/Ubuntu, create users, change the default user, configure startup, or restart the distribution. `-Plan` is available.

## Open and inspect

```powershell
wsl -d Ubuntu-26.04
```

Inside Ubuntu, run `sudo agpc-manager`. If password setup was skipped, set it locally with `wsl -d Ubuntu-26.04 -u root -- passwd jujue`.

Setup state and logs: `%LOCALAPPDATA%\AGPC-Win\<Distro>`. Linux package result: `/var/lib/agpc-win/result.json`. Detailed upstream logs: `/var/lib/agpc-install.*/`. On failure, read the error and rerun the same command. Passwords are never saved by these wrappers.

Both scripts call the permanent `https://motebus.github.io/download/agpc.sh` and retain its package, checksum, migration and SSH checks. They perform no Docker operations. Package installation is not full runtime readiness: models, network identities, remote access and end-to-end AGPC operation require separate verification.

## Uninstall

**Deleting Ubuntu deletes all files inside that selected distribution.** Export or copy anything you want to keep first. This command requires an explicit distribution name and confirmation:

```powershell
curl.exe -fL https://motebus.github.io/download/agpc-win-uninstall.ps1 -o "$env:TEMP\agpc-win-uninstall.ps1"
& "$env:TEMP\agpc-win-uninstall.ps1" -Distro Ubuntu-26.04
```

Use `-Plan` or `-WhatIf` to preview. It removes only that distribution and its owner-specific AGPC boot/resume tasks; WSL, other distributions and Windows setup logs remain.

To remove AGPC packages while keeping Ubuntu:

```powershell
curl.exe -fL https://motebus.github.io/download/agpc-unistall.ps1 -o "$env:TEMP\agpc-unistall.ps1"
& "$env:TEMP\agpc-unistall.ps1" -Distro Ubuntu
```

`-Plan` downloads the official Linux removal script and shows its package plan without removing packages or stopping services. Actual removal asks you to type `REMOVE`. Ubuntu and its Windows boot task remain.

The native `uninstall.sh` supports the exact reviewed 28-package `agent-computer-v0.2.0-12` catalog, including partial installations of those versions. It retains Obsidian, OS dependencies, APT registration, models, Vaults, accounts, configuration and topology files. It never purges or automatically removes dependencies. Package-owned topology payloads are retained at their original paths using temporary DPKG metadata diversions with `--no-rename`; their contents are never rewritten. Legacy transport topology ownership, unreviewed versions/hooks, and unrelated reverse dependencies stop removal before the package transaction. Close AGPC desktop applications before removing their packages.

## Validation status

This first Windows release is a preview. Automated checks cover PowerShell parsing, native error propagation, distribution selection, generated Linux syntax, systemd configuration preservation, and the boot task definition with mocked registration. Native removal is tested with a real APT/DPKG transaction in a disposable filesystem and package database, including retained topology payloads. The current installed AGPC was checked in plan-only mode. A clean Windows VM install, restart/resume, actual before-login boot, and full real-machine uninstall acceptance remain unverified.

```powershell
.\scripts\Test-Agpc.ps1
# Windows CI without WSL:
.\scripts\Test-Agpc.ps1 -SkipLinuxChecks
```

Linux CI additionally validates the embedded shell/Python code and configuration preservation.
