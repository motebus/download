# Sphere 5.2.0-3 restricted runner

This directory is the public-source contract for the separately signed
`sphere-runner-v5.2.0-3-7` corrective bootstrap publication. It retains the
exact four-operation `sphere-runner-v5.2.0-3-1` routine runner surface and
adds only a signed SSH Match policy for the dedicated principals. The immutable `-2`
publication remains failed corrective evidence because it treated a trailing
blank SSH public-key record as identity data. The immutable `-3` publication
fixed key identity but exposed Ubuntu's locked-account rejection before
public-key evaluation. Immutable `-4` is failed evidence because an isolated
chroot cannot reload the host SSH daemon. The `-5` bootstrap accepts only the
exact consumed `-3` L1 marker, validates and installs a public-key-only SSH
Match policy, makes the dedicated principal non-locked, and writes a new
consumed marker. The separately admitted controller performs the exact host
SSH HUP and advertised-auth-method proof. Immutable `-5` left the root-owned
public `authorized_keys` file at mode `0600`, so the service principal could
not read its admitted key. The `-6` bootstrap accepts only the exact consumed
`-5` L1 marker and changes that public file to root-owned mode `0644`; the
principal can read but cannot modify it. Immutable `-6` installed the exact
digest-form sudoers rule under a dotted filename that Ubuntu's `@includedir`
silently ignored. The `-7` bootstrap accepts only the exact consumed `-6` L1
marker, installs the same policy at dotless path
`/etc/sudoers.d/sphere-install-l1-5203`, and requires whole-policy `visudo`
plus `sudo -l -U` enumeration before completion. It does not grant general SSH, sudo, a
shell, package-manager access, or another release operation.

L1 is the controller and canary. Four private keys remain only in the L1
controller directory: distinct L1/L9 SSH keys and distinct L1/L9 Ed25519
capability-signing keys. Only their public halves are publishable. L9 receives
only its restricted SSH public key and capability verifier public key.

The target-side forced dispatcher accepts exactly:

```text
sphere-install:5.2.0-3
sphere-verify:5.2.0-3
sphere-result:5.2.0-3
sphere-maintenance-health:5.2.0-3
```

Each literal maps to one root-owned, no-argument executable. The target
sudoers policy names the executable's absolute path, exact SHA-256 command
digest, explicit empty argument string, `NOPASSWD`, and `NOSETENV`. It does
not admit an interpreter, downloader, package manager, service manager,
wildcard, or `ALL`.

Every invocation also requires a target-, release-, operation-, runner-, and
key-bound Ed25519 token. The L1 same-UID Unix-socket issuer creates tokens with
a maximum admitted lifetime of five minutes; the current client requests 120
seconds. The token travels only in memory and on the forced command's stdin.
The verifier atomically consumes its ID before sudo and persists only a hash
and non-secret correlation/decision metadata.

## One-time bootstrap

`bootstrap-sphere-runner-5.2.0-3` accepts no arguments and maps only the exact
hostnames `medge-home` and `medge-tv` to L1 and L9. Before mutation it verifies
the immutable runner manifest, every artifact digest, every detached
signature, the archive fingerprint, the approved privilege admission,
target identity, validity window, target public keys, and sudoers syntax.

The bootstrap creates one non-human principal with a root-owned restricted
`authorized_keys` file and an exact root-owned SSH Match policy that disables
password, keyboard-interactive, PTY, and forwarding while requiring public
key authentication. After policy validation and reload, it replaces the
locked shadow marker with a random discarded-password hash so Ubuntu does not
reject the account before public-key evaluation. It installs the exact signed
artifacts and writes one root-owned consumed marker. A repeated bootstrap is
denied. It does not change a human password or create general passwordless
administration. The bootstrap file itself must be downloaded and
verified with the same archive key before a desktop-native administrator
authorization executes the local file; downloaded content is never piped
into sudo or a shell.

L1 additionally verifies that its four protected private keys match the
approved public assets by canonical SSH algorithm/key blob and Ed25519 public
DER identity, never by comment or PEM text serialization, then installs the
controller agent/client. The client
uses strict host keys, public-key-only authentication, no PTY or forwarding,
loopback OpenSSH for L1, and the packaged Mote Proxy for
`medge-tv.mote`. It sends one compiled-in operation literal and the token on
stdin.

Rollout is L1 first. L9 may start only after L1 passes signature/digest checks,
the denial matrix, installation, exact-version verification, audit capture,
bootstrap consumption, and repeated-bootstrap denial. A separate native
administrator bootstrap must then run locally on L9; a password may not be
relayed through SSH, chat, argv, environment, stdin, a file, or a log.

The approved routine window ends at the time in
`release/install-sphere-v5.2.0-3.privilege-admission.json`. Expiry never falls
back to a prompt. Renewal, key rotation, privilege expansion, recovery, or a
new release requires a new signed admission and, when target artifacts
change, a new native local bootstrap.

Validate without target mutation:

```bash
./scripts/validate.sh
```
