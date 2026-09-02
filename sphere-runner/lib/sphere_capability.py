import base64
import datetime as dt
import errno
import hashlib
import json
import os
import re
import stat
import subprocess


TOKEN_SCHEMA = "install-sphere-capability-token/v1"
CLAIM_KEYS = {
    "aud",
    "correlation_id",
    "exp",
    "iat",
    "iss",
    "jti",
    "key_id",
    "operation",
    "release",
    "runner_sha256",
    "target",
}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
OPERATION_RE = re.compile(r"^[a-z0-9][a-z0-9.:-]{0,127}$")


class CapabilityError(ValueError):
    pass


def _no_duplicate_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CapabilityError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_token(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 16384:
        raise CapabilityError("token frame is empty or overlong")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CapabilityError("token frame is not UTF-8") from error
    try:
        token = json.loads(text, object_pairs_hook=_no_duplicate_object)
    except (json.JSONDecodeError, TypeError) as error:
        raise CapabilityError("token frame is malformed JSON") from error
    if not isinstance(token, dict) or set(token) != {"schema", "claims", "signature"}:
        raise CapabilityError("token envelope fields are invalid")
    if token["schema"] != TOKEN_SCHEMA:
        raise CapabilityError("token schema mismatch")
    claims = token["claims"]
    signature = token["signature"]
    if not isinstance(claims, dict) or set(claims) != CLAIM_KEYS:
        raise CapabilityError("token claim fields are invalid")
    if not isinstance(signature, dict) or set(signature) != {"algorithm", "key_id", "value"}:
        raise CapabilityError("token signature fields are invalid")
    if signature["algorithm"] != "Ed25519":
        raise CapabilityError("token signature algorithm mismatch")
    if signature["key_id"] != claims["key_id"]:
        raise CapabilityError("token signature key identity mismatch")
    return token


def canonical_payload(token):
    return json.dumps(
        {"claims": token["claims"], "schema": token["schema"]},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _base64url_decode(value):
    if not isinstance(value, str) or not value or "=" in value:
        raise CapabilityError("token signature encoding is invalid")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise CapabilityError("token signature encoding is invalid") from error


def _run_openssl(args, payload, signature=None):
    payload_fd = os.memfd_create("sphere-capability-payload", os.MFD_CLOEXEC)
    signature_fd = None
    try:
        os.write(payload_fd, payload)
        os.lseek(payload_fd, 0, os.SEEK_SET)
        pass_fds = [payload_fd]
        expanded = [item.replace("{payload}", f"/proc/self/fd/{payload_fd}") for item in args]
        if signature is not None:
            signature_fd = os.memfd_create("sphere-capability-signature", os.MFD_CLOEXEC)
            os.write(signature_fd, signature)
            os.lseek(signature_fd, 0, os.SEEK_SET)
            pass_fds.append(signature_fd)
            expanded = [
                item.replace("{signature}", f"/proc/self/fd/{signature_fd}")
                for item in expanded
            ]
        return subprocess.run(
            expanded,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=tuple(pass_fds),
        )
    finally:
        os.close(payload_fd)
        if signature_fd is not None:
            os.close(signature_fd)


def public_key_sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def sign_token(claims, private_key_path, openssl_path="/usr/bin/openssl"):
    token = {
        "schema": TOKEN_SCHEMA,
        "claims": claims,
        "signature": {"algorithm": "Ed25519", "key_id": claims["key_id"], "value": "pending"},
    }
    result = _run_openssl(
        [
            openssl_path,
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            str(private_key_path),
            "-in",
            "{payload}",
        ],
        canonical_payload(token),
    )
    if result.returncode != 0:
        raise CapabilityError("token signing failed")
    token["signature"]["value"] = base64.urlsafe_b64encode(result.stdout).rstrip(b"=").decode("ascii")
    return json.dumps(token, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _validate_claims(claims, expected, now):
    for field in ("iss", "aud", "target", "release", "operation", "runner_sha256", "key_id"):
        if claims.get(field) != expected[field]:
            raise CapabilityError(f"token {field} mismatch")
    if not KEY_ID_RE.fullmatch(claims["key_id"]):
        raise CapabilityError("token key identity is invalid")
    if not OPERATION_RE.fullmatch(claims["operation"]):
        raise CapabilityError("token operation is invalid")
    if not SHA256_RE.fullmatch(claims["runner_sha256"]):
        raise CapabilityError("token runner digest is invalid")
    if not UUID_RE.fullmatch(claims.get("jti", "")):
        raise CapabilityError("token unique ID is invalid")
    if not UUID_RE.fullmatch(claims.get("correlation_id", "")):
        raise CapabilityError("token correlation ID is invalid")
    iat = claims.get("iat")
    exp = claims.get("exp")
    if not isinstance(iat, int) or isinstance(iat, bool) or not isinstance(exp, int) or isinstance(exp, bool):
        raise CapabilityError("token time claims are invalid")
    if exp <= iat or exp - iat > expected["max_ttl_seconds"]:
        raise CapabilityError("token lifetime is invalid")
    if iat > now + expected.get("clock_skew_seconds", 30):
        raise CapabilityError("token is not yet valid")
    if exp < now:
        raise CapabilityError("token is expired")


def _verify_signature(token, public_key_path, openssl_path):
    signature = _base64url_decode(token["signature"]["value"])
    result = _run_openssl(
        [
            openssl_path,
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(public_key_path),
            "-rawin",
            "-in",
            "{payload}",
            "-sigfile",
            "{signature}",
        ],
        canonical_payload(token),
        signature,
    )
    if result.returncode != 0:
        raise CapabilityError("token signature verification failed")


def _consume_replay(claims, replay_dir, now):
    replay_path = os.path.abspath(replay_dir)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    try:
        directory_fd = os.open(replay_path, directory_flags)
    except OSError as error:
        raise CapabilityError("replay directory is unavailable") from error
    try:
        item = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(item.st_mode)
            or item.st_uid != os.geteuid()
            or item.st_gid != os.getegid()
            or stat_mode_unsafe(item.st_mode)
        ):
            raise CapabilityError("replay directory mode is unsafe")
        token_id_hash = hashlib.sha256(claims["jti"].encode("ascii")).hexdigest()
        record_name = token_id_hash + ".json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(record_name, flags, 0o600, dir_fd=directory_fd)
        except OSError as error:
            if error.errno == errno.EEXIST:
                raise CapabilityError("token replay detected") from error
            raise
        record = {
            "schema": "install-sphere-capability-replay/v1",
            "token_id_sha256": token_id_hash,
            "correlation_id": claims["correlation_id"],
            "issuer_key_id": claims["key_id"],
            "target": claims["target"],
            "release": claims["release"],
            "operation": claims["operation"],
            "issued_at": claims["iat"],
            "expires_at": claims["exp"],
            "consumed_at": now,
            "decision": "allow",
        }
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.unlink(record_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(directory_fd)
    return record


def stat_mode_unsafe(mode):
    return bool(mode & 0o022)


def verify_and_consume(
    raw,
    public_key_path,
    public_key_digest,
    expected,
    replay_dir,
    now=None,
    openssl_path="/usr/bin/openssl",
):
    token = parse_token(raw)
    claims = token["claims"]
    current_time = int(dt.datetime.now(dt.timezone.utc).timestamp()) if now is None else int(now)
    _validate_claims(claims, expected, current_time)
    if public_key_sha256(public_key_path) != public_key_digest:
        raise CapabilityError("token verifier public-key digest mismatch")
    _verify_signature(token, public_key_path, openssl_path)
    return _consume_replay(claims, replay_dir, current_time)

