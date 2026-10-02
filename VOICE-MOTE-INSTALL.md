# Voice-Mote bootstrap installer

Version: `0.1.0-bootstrap.3`. APT package: `voice-mote`.

## Install the published preview on medge-tv

The explicit `--preview` mode installs the released `0.1.0~preview.3` control runtime on an existing Ubuntu 24.04 amd64 AGPC. It requires an installed `agpc-manager`, existing machine identity, systemd and healthy package state. Full AGPC acceptance is not asserted or required for this limited preview installation. medge-tv currently has AGPC installed but has not passed full live readiness.

Download and authenticate before running:

```sh
mkdir -p ~/voice-mote-install
cd ~/voice-mote-install
for file in voice-mote.sh voice-mote.sh.asc voice-mote.source.json voice-mote.source.json.asc; do
    curl --fail --show-error --location --proto '=https' --proto-redir '=https' \
        "https://motebus.github.io/download/$file" -o "$file" || exit 1
done
gpgv --keyring /etc/apt/keyrings/medge-archive-keyring.gpg voice-mote.sh.asc voice-mote.sh || exit 1
gpgv --keyring /etc/apt/keyrings/medge-archive-keyring.gpg voice-mote.source.json.asc voice-mote.source.json || exit 1
python3 -c 'import hashlib,json; from pathlib import Path; r=json.loads(Path("voice-mote.source.json").read_text()); assert hashlib.sha256(Path("voice-mote.sh").read_bytes()).hexdigest()==r["files"]["voice-mote.sh"]["sha256"]' || exit 1
sudo bash ./voice-mote.sh --preview --check
sudo bash ./voice-mote.sh --preview --yes
voice-mote status
```

Use the independently trusted MoteBus archive key established by AGPC installation; a newly downloaded same-origin key alone does not establish trust. If the trusted key is stored elsewhere, use its established path.

Preview downloads the fixed GitHub release asset from [preview.3](https://github.com/motebus/download/releases/tag/voice-mote-v0.1.0-preview.3). Its SHA-256 is pinned inside this signed bootstrap:

`3c8c5514637c6fdc23dff5173556796190546f47afe49948502e784bf36fac93`

The installer checks package name/version/architecture and refuses to downgrade a newer installed version. APT simulates and installs the verified local package, retaining authenticated configured repositories for dependencies. This does not promote the package into production APT. Future preview upgrades require a reviewed installer revision; production lifecycle remains with APT.

Exit zero means the exact preview package is installed and `voice-moted` is running. It does **not** mean Voice-Mote Ready. SIP, media, Voice Dots, model access, policy and real phone acceptance need separate setup. `voice-mote verify` remains nonzero until full capability is implemented and verified. The opt-in voice agent is not enabled by this installer. No kiosk configuration, credentials, SIP accounts or machine identity are copied. Map is not an installation dependency.

## Production APT mode

Without `--preview`, the existing strict contract is unchanged: require full AGPC Ready, install `voice-mote` from configured trusted APT repositories and require successful capability verification. The runtime preview is not yet promoted to that repository.

The default check is `/usr/bin/agpc-manager ready --json`: `state=ready`, `live_verified=true`, and scope other than `local-precheck`. An approved full acceptance checker can be supplied with `--agpc-verify /absolute/path`. It takes no arguments, must be root-owned with non-writable, non-symlink ancestors, and must return zero only on full live acceptance. A constant-success checker is not valid. This option cannot be combined with `--preview`.

## Operations

`--help` and `--version` need no privilege. `--check` checks prerequisites and simulates with cached APT indexes; preview also downloads and authenticates the package into a temporary directory which is removed on exit. It does not install or update packages. `--yes` accepts the installation transaction. Normal installation refreshes configured APT indexes and stops on update failures.

Both modes reject broken dpkg state and package removals, disable unauthenticated/insecure repository options and automatic downgrades, and preserve existing sources and keys. Failure preserves installed packages for diagnosis. Production capability failure remains a nonzero exit; preview reports its limited installation outcome explicitly.

See [Voice-Mote Specification v0.1](VOICE-MOTE-SPEC-v0.1.md).
