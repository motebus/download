# Voice-Mote bootstrap installer

Version: `0.1.0-bootstrap.1`. APT package: `voice-mote`.

`voice-mote.sh` bootstraps Voice-Mote on an existing Ubuntu AGPC. It checks the platform, requires full AGPC Ready evidence, checks package state, previews the APT transaction, installs `voice-mote`, and runs `/usr/bin/voice-mote verify`. Package scripts own configuration and service lifecycle. The bootstrap does not create a second machine identity.

This release contains the bootstrap only. It does not include `voice-moted`, SIP/media adapters or a realtime AI runtime. At release preparation, the authenticated public APT index did not contain `voice-mote`; installation remains blocked until that runtime package is published. Publishing this installer does not establish Voice-Mote Ready.

## Download and authenticate

Download `voice-mote.sh`, `voice-mote.sh.asc`, `voice-mote.source.json` and `voice-mote.source.json.asc` from `https://motebus.github.io/download/`. Verify both signatures with the independently trusted MoteBus archive key, then match the script SHA-256 to `files["voice-mote.sh"].sha256` in the signed source record. The record identifies the GitHub source commit.

On a host whose AGPC installation has already established the archive key trust:

```sh
gpgv --keyring /etc/apt/keyrings/medge-archive-keyring.gpg voice-mote.sh.asc voice-mote.sh
gpgv --keyring /etc/apt/keyrings/medge-archive-keyring.gpg voice-mote.source.json.asc voice-mote.source.json
python3 -c 'import hashlib,json; from pathlib import Path; r=json.loads(Path("voice-mote.source.json").read_text()); assert hashlib.sha256(Path("voice-mote.sh").read_bytes()).hexdigest()==r["files"]["voice-mote.sh"]["sha256"]'
bash ./voice-mote.sh --help
sudo bash ./voice-mote.sh
```

Do not treat a newly downloaded same-origin key as independent trust. The bootstrap preserves existing APT sources and keys; trusted repositories must already be configured without signature-bypass options such as `trusted=yes`.

## AGPC acceptance

By default the bootstrap invokes `/usr/bin/agpc-manager ready --json` and requires `state=ready`, `live_verified=true`, and a scope other than `local-precheck`. The currently observed local-precheck contract does not meet this gate. A completed AGPC acceptance workflow can supply its approved checker:

```sh
sudo bash ./voice-mote.sh --agpc-verify /absolute/path/to/agpc-ready-check
```

The checker takes no arguments, must verify full live readiness and return zero only on success. It and its parent directories must be root-owned, non-writable by others and not symlinks. It runs with a 120-second timeout. This is an integration interface, not an assertion that AGPC already ships such a checker. A constant-success script is not a readiness check.

## Operations and failure behavior

`--version` and `--help` require no privilege. `--check` checks prerequisites and simulates installation using cached APT indexes; it does not install packages or establish Voice-Mote capability. `--yes` accepts the APT transaction for an authorized noninteractive installation.

Missing prerequisites, failed or incomplete AGPC acceptance, package unavailability, incomplete dpkg state, APT errors or transactions requiring removals stop the bootstrap. Installation does not permit unauthenticated packages or automatic downgrades. If installation succeeds but Voice-Mote verification fails, it returns a nonzero exit code and preserves installed packages for diagnosis. SIP, model, policy and tool configuration must be completed through the runtime's supported interfaces.

See [Voice-Mote Specification v0.1](VOICE-MOTE-SPEC-v0.1.md) for the product contract.
