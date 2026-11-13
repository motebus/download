# AGPC Ready for macOS

This preview installs the native Apple Silicon controller and B-channel SSH
proxy. It can provision mbStack and DC in a dedicated Linux amd64 UTM guest.
macOS starts the proxy at system boot. At the installing user's graphical
login, UTM starts the guest and hides its window. The guest starts mbStack
and then DC via systemd. No Docker or OCI runtime is required.

Use UTM 5.0.8, a registered Linux amd64 guest with Node.js 22, and a Mac
administrator account. The guest needs a QEMU emulated network with guest IP
`10.0.2.15` and host loopback forwarding `127.0.0.1:6262` to guest TCP
6262. Leave the UTM display configured. Find the VM UUID with
`/Applications/UTM.app/Contents/MacOS/utmctl list`.

Verify the downloaded shell installer using its detached signature and the
[MEdge archive key](https://motebus.github.io/download/medge-archive-keyring.gpg)
before running it. The keyring's SHA-256 is
`756fc2632c307509b8e5ece665ced7f4d1a58636ac935aefc1e017f7dcfcbfbd`.

```sh
gpgv --keyring "$PWD/medge-archive-keyring.gpg" agpc-ready-mac.sh.asc agpc-ready-mac.sh
bash agpc-ready-mac.sh --verify
bash agpc-ready-mac.sh --install --utm-app /Applications/UTM.app --vm-id VM_UUID
```

The short install command assumes the guest already starts mbStack and DC.
For a guest without those services, add
`--guest-ssh-dir /absolute/path/to/guest-trust --upstreams 'HOST1;HOST2'`.
Use the upstream hosts assigned to this deployment. Configure a second
loopback forward from Mac TCP 22242 to guest TCP 22. Set up the guest's
`agpcbuild` user with key authentication and noninteractive sudo for the
guest installer. The trust directory must contain `guest-ssh-key` (private,
mode 0600) and `guest-known-hosts` with the trusted guest key for
`[127.0.0.1]:22242`. Obtain that key from the trusted guest console. To
provision from the guest console instead, run
`sudo bash install-sphere-guest.sh --install 'HOST1;HOST2'` there first.

Allow the macOS Automation prompt to control UTM and enter the administrator
password for proxy setup. Log out and back in if needed to pick up membership
in the proxy socket group. To verify B-channel access, use
`/Library/AGPC/mote-proxy/bin/mote-ssh -l SSH_USER PEER.mote -- hostname`
with a registered peer and its authorized SSH key. Existing OpenSSH settings
are preserved.

On the configured M4, a real reboot brought up UTM, both guest services,
and the B-channel proxy, and strict passwordless SSH reached the registered
test peer. The new package is a preview for an operator-provided UTM guest;
it does not include a VM image or enable macOS automatic login. The proxy
is an M4 development build with archive signature verification, not a
Developer ID notarized package.
