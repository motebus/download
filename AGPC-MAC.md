# AGPC controller preview for Apple Silicon

This installer uses the published ARM64 controller from AGPC Native
[0.1.0-preview.21](https://github.com/motebus/download/releases/tag/agpc-native-v0.1.0-preview.21).
It requires a native Apple Silicon macOS shell and GnuPG's `gpgv`.
Run as your normal Mac user.

```sh
curl -fL https://motebus.github.io/download/agpc-mac.sh -o agpc-mac.sh
bash agpc-mac.sh --plan
bash agpc-mac.sh --verify
bash agpc-mac.sh --install
```

The installer verifies the versioned archive, controller checksum and embedded
OpenPGP signature. It installs the controller to `~/.local/bin/agpc` and stops
if a different executable already occupies that path.

This preview contains the controller only. Runtime setup and acceptance are
separate. The controller has no Apple Developer ID signature or notarization.

[Installer signature](agpc-mac.sh.asc) · [Source record](agpc.mac.source.json) ·
[Source record signature](agpc.mac.source.json.asc)
