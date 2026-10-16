"""Voice publication failure gates and preservation; no real keys or runtime."""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_agpc_voice as voice
import publish_native as native


class VoicePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "agpc.sh").write_bytes(b"preserved core")
        (self.site / "InRelease").write_bytes(b"preserved signed index")
        self.inputs = dict(schema="agpc.voice-publication-inputs/v1", version="0.1.0~candidate.6",
                           source_commit="a" * 40, ci_job=1, archive_sha256="f" * 64, archive_bytes=1,
                           install_review=80,
                           disclosure_review=dict(project=1341, iid=80))
        self.sources = dict(schema="agpc.voice-component-main-ci/v1", voice_commit="b" * 40, voice_ci_job=2,
                            voice_review=2)
        self.packages = []
        for name, version, arch in [("agpc-voice", self.inputs["version"], "all"),
                                    ("agpc-freeswitch-core", "1.11.3+agpc1", "amd64")]:
            stage = self.root / name
            (stage / "DEBIAN").mkdir(parents=True)
            (stage / "DEBIAN/control").write_text(f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\n"
                                                  "Maintainer: Test <test@example.invalid>\nDepends: libc6\nDescription: fixture\n")
            filename = f"{name}_{version}_{arch}.deb"
            path = self.bundle / "packages" / filename
            path.parent.mkdir(exist_ok=True)
            subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(path)],
                           capture_output=True, check=True)
            self.packages.append(dict(name=name, version=version, architecture=arch, depends="libc6",
                                      sha256=native.file_digest(path),
                                      url=voice.PUBLIC + "/agpc-voice/" + self.inputs["version"] + "/packages/" + filename))
        self.receipt = dict(schema="agpc.voice-standalone-build/v1", mode="release-staging",
                            source_commit="a" * 40, source_admitted=True, committed_runtime_verified=True,
                            runtime_package_binding_verified=True, ready=False, package_pins=self.packages)
        self.runtime(True)

    def runtime(self, gate):
        sources = {"native_voice": f"INSTALL_CONTRACT_ADMITTED = {gate}\n"}
        payload = base64.b64encode(gzip.compress(json.dumps(sources).encode(), mtime=0)).decode()
        script = ("#!/bin/bash\npython3 - <<'AGPC_VOICE_PACKAGED_RUNTIME'\n"
                  + "payload = base64.b64decode(" + repr(payload) + ", validate=True)\n"
                  + "AGPC_VOICE_PACKAGED_RUNTIME\n").encode()
        (self.bundle / "agpc-voice.sh").write_bytes(script)
        self.receipt["installer_sha256"] = native.digest(script)
        self.receipt["runtime_sha256"] = {name + ".py": native.digest(data.encode()) for name, data in sources.items()}
        self.save()

    def save(self):
        (self.bundle / "BUILD-RECEIPT.json").write_text(json.dumps(self.receipt))
        (self.bundle / "SOURCE-RELEASE.json").write_text(json.dumps(self.sources))
        files = [p for p in self.bundle.rglob("*") if p.is_file() and p.name not in ("SHA256SUMS", "SOURCE-RELEASE.json")]
        (self.bundle / "SHA256SUMS").write_text("\n".join(native.file_digest(p) + "  " + p.relative_to(self.bundle).as_posix()
                                                     for p in sorted(files)) + "\n")

    def api(self, endpoint):
        project = int(endpoint.split("/")[1])
        commit = "a" * 40 if project == 1341 else "b" * 40
        if "/members/all/" in endpoint:
            return dict(access_level=40)
        if endpoint.endswith("/approvals"):
            return dict(approved=True, approved_by=[dict(user=dict(id=34))])
        if "/merge_requests/" in endpoint:
            return dict(state="merged", target_branch="main", merge_commit_sha=commit)
        if "/pipelines/" in endpoint:
            return dict(id=project, status="success", ref="main", sha=commit)
        job = int(endpoint.rsplit("/", 1)[1])
        return dict(id=job, status="success", ref="main", tag=False, commit=dict(id=commit),
                    pipeline=dict(id=project, sha=commit, ref="main"))

    def component(self, endpoint):
        return next((self.bundle / "packages").glob("agpc-voice_*.deb")).read_bytes()

    def sign(self, root, site, names):
        for name in names:
            (site / (name + ".asc")).write_bytes(b"fixture signature")

    def overlay(self, get_json=None, get_bytes=None, verify=None):
        with patch.object(native, "sign_files", side_effect=self.sign), patch.object(voice, "verify_signature", side_effect=verify):
            voice.overlay(ROOT, self.site, self.inputs, self.bundle, self.root / "evidence.json",
                          get_json=get_json or self.api, get_bytes=get_bytes or self.component)

    def reject(self, message, **kwargs):
        before = native.snapshot(self.site)
        with self.assertRaisesRegex(ValueError, message):
            self.overlay(**kwargs)
        self.assertEqual(native.snapshot(self.site), before)

    def test_signed_versioned_overlay_preserves_unrelated_site(self):
        self.overlay()
        self.assertEqual((self.site / "agpc.sh").read_bytes(), b"preserved core")
        self.assertEqual((self.site / "InRelease").read_bytes(), b"preserved signed index")
        record = json.loads((self.site / "agpc-voice.source.json").read_text())
        self.assertEqual(record["schema"], "agpc.voice-install-source/v1")
        self.assertNotIn("installer_revision", record)
        self.assertFalse(record["runtime_ready"])
        self.assertEqual(record["source"]["commit"], "a" * 40)
        self.assertEqual(record["voice_source"]["commit"], "b" * 40)
        self.assertEqual(len(list((self.site / "agpc-voice" / self.inputs["version"] / "packages").glob("*.deb.asc"))), 2)
        self.assertEqual(json.loads((self.root / "evidence.json").read_text())["preserved_files"], 2)

    def test_false_embedded_gate_rejected_even_with_true_receipt(self):
        self.runtime(False)
        self.reject("source-owned install gate remains closed")

    def test_candidate_receipt_or_unverified_commit_rejected(self):
        self.receipt["committed_runtime_verified"] = False
        self.save()
        self.reject("release admission missing")

    def test_component_deb_must_match_original_main_ci_artifact(self):
        self.reject("differs from component main CI", get_bytes=lambda path: b"different component artifact")

    def test_feature_ci_and_unapproved_review_cannot_publish(self):
        def branch(path):
            obj = self.api(path)
            if "/jobs/" in path:
                obj["ref"] = "feature"
            return obj
        self.reject("successful exact main CI", get_json=branch)
        def tag(path):
            obj = self.api(path)
            if "/jobs/" in path:
                obj["tag"] = True
            return obj
        self.reject("successful exact main CI", get_json=tag)
        def unapproved(path):
            return dict(approved=False, approved_by=[]) if path.endswith("/approvals") else self.api(path)
        self.reject("source review approval missing", get_json=unapproved)

    def test_component_review_must_bind_exact_main_commit(self):
        def wrong(path):
            obj = self.api(path)
            if "/merge_requests/" in path and not path.endswith("/approvals"):
                obj["merge_commit_sha"] = "c" * 40
            return obj
        self.reject("exact merged source review", get_json=wrong)

    def test_ordinary_developer_approval_cannot_substitute_for_maintainer(self):
        def developer(path):
            return dict(access_level=30) if "/members/all/" in path else self.api(path)
        self.reject("Maintainer source approval required", get_json=developer)

    def test_unbound_package_url_rejected(self):
        self.packages[0]["url"] = None
        self.save()
        self.reject("package URL is not bound")

    def test_versioned_content_cannot_be_replaced(self):
        self.overlay()
        target = self.site / "agpc-voice" / self.inputs["version"] / "agpc-voice.sh"
        target.write_bytes(b"existing different immutable script")
        self.reject("versioned Voice content is immutable")

    def test_republishing_reuses_version_signatures(self):
        self.overlay()
        before = native.snapshot(self.site)
        self.overlay()
        self.assertEqual(native.snapshot(self.site), before)

    def revision(self, value=1):
        self.inputs.update(schema="agpc.voice-publication-inputs/v2", installer_revision=value)
        self.receipt.update(schema="agpc.voice-standalone-build/v2", installer_revision=value)
        self.save()

    def test_v2_revision_preserves_signed_base_and_component_and_updates_aliases(self):
        self.overlay()
        original = native.snapshot(self.site)
        self.revision()
        script = self.bundle / "agpc-voice.sh"
        old_script = script.read_bytes()
        new_script = old_script.replace(b"#!/bin/bash\n", b"#!/usr/bin/env bash\n# corrected stdin bootstrap\n", 1)
        self.assertNotEqual(new_script, old_script)
        script.write_bytes(new_script)
        self.receipt["installer_sha256"] = native.digest(new_script)
        self.save()
        calls = []
        self.overlay(verify=lambda root, site, name: calls.append(name))
        prefix = "agpc-voice/" + self.inputs["version"] + "/installers/1/"
        for name, digest in original.items():
            if name.startswith("agpc-voice/"):
                self.assertEqual(native.file_digest(self.site / name), digest, name)
        for name in ("agpc-voice.sh", "agpc-voice.source.json"):
            for suffix in ("", ".asc"):
                self.assertEqual((self.site / (name + suffix)).read_bytes(),
                                 (self.site / (prefix + name + suffix)).read_bytes())
        self.assertFalse((self.site / (prefix + "packages")).exists())
        self.assertEqual(len(calls), 7)  # both latest aliases and all five immutable base artifacts
        record = json.loads((self.site / "agpc-voice.source.json").read_text())
        self.assertEqual(record["schema"], "agpc.voice-install-source/v2")
        self.assertEqual(record["installer_revision"], 1)
        self.assertEqual(record["packages"], self.packages)
        self.assertEqual((self.site / "agpc-voice.sh").read_bytes(), new_script)
        self.assertEqual((self.site / "agpc-voice" / self.inputs["version"] / "agpc-voice.sh").read_bytes(), old_script)
        before = native.snapshot(self.site)
        with patch.object(self, "sign", side_effect=lambda root, site, names: self.assertEqual(names, set())):
            self.overlay()
        self.assertEqual(native.snapshot(self.site), before)

    def test_revision_schema_and_bounded_identity_are_unambiguous(self):
        self.inputs["installer_revision"] = 1
        self.reject("revision requires v2")
        self.inputs["schema"] = "agpc.voice-publication-inputs/v2"
        for value in (None, True, False, 0, -1, 1000000, "1", "../1", 1.0):
            self.inputs["installer_revision"] = value
            self.reject("invalid installer revision")
        del self.inputs["installer_revision"]
        self.reject("invalid installer revision")

    def test_revision_receipt_must_bind_exact_v2_source_selection(self):
        self.inputs.update(schema="agpc.voice-publication-inputs/v2", installer_revision=1)
        self.reject("revision differs from source receipt")
        self.receipt["installer_revision"] = 1
        self.save()
        self.reject("revision requires v2")
        self.receipt["schema"] = "agpc.voice-standalone-build/v2"
        self.receipt["installer_revision"] = 2
        self.save()
        self.reject("revision differs from source receipt")

    def test_revision_requires_signed_base_and_never_creates_packages(self):
        self.revision()
        self.reject("signed latest Voice record required")
        self.inputs.pop("installer_revision")
        self.inputs["schema"] = "agpc.voice-publication-inputs/v1"
        self.receipt.pop("installer_revision")
        self.receipt["schema"] = "agpc.voice-standalone-build/v1"
        self.save()
        self.overlay()
        self.revision()
        target = self.site / "agpc-voice" / self.inputs["version"] / "packages"
        next(target.glob("*.asc")).unlink()
        self.reject("signed immutable Voice base required")

    def test_revision_refuses_base_signature_and_cross_binding_failures(self):
        self.overlay()
        self.revision()
        def bad_signature(root, site, name):
            if name.endswith(".deb"):
                raise ValueError("fixture invalid signature")
        self.reject("fixture invalid signature", verify=bad_signature)
        base = self.site / "agpc-voice" / self.inputs["version"]
        path = base / "BUILD-RECEIPT.json"
        original = path.read_bytes()
        record = json.loads(original)
        record["source_commit"] = "c" * 40
        path.write_text(json.dumps(record))
        self.reject("base receipt/script binding differs")
        path.write_bytes(original)
        package = next((base / "packages").glob("*.deb"))
        package.write_bytes(b"tampered package")
        self.reject("signed base package differs")

    def test_revision_base_receipt_retains_component_metadata_without_requiring_projection_identity(self):
        self.overlay()
        self.revision()
        path = self.site / "agpc-voice" / self.inputs["version"] / "BUILD-RECEIPT.json"
        record = json.loads(path.read_bytes())
        # The real source receipt contains provenance/size fields omitted from the public projection.
        record["package_pins"][0].update(provenance="original-main", bytes=123, source="component-source")
        path.write_text(json.dumps(record))
        self.overlay()

    def test_revision_refuses_base_receipt_package_mismatch(self):
        self.overlay()
        self.revision()
        path = self.site / "agpc-voice" / self.inputs["version"] / "BUILD-RECEIPT.json"
        record = json.loads(path.read_bytes())
        record["package_pins"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(record))
        self.reject("base receipt/package binding differs")

    def test_revision_rejects_base_component_identity_change(self):
        self.overlay()
        self.revision()
        base = self.site / "agpc-voice" / self.inputs["version"]
        path = base / "agpc-voice.source.json"
        record = json.loads(path.read_bytes())
        record["voice_source"]["ci_job"] = 77
        path.write_text(json.dumps(record))
        (self.site / "agpc-voice.source.json").write_bytes(path.read_bytes())
        self.reject("retain signed component provenance")

    def test_revision_rejects_torn_latest_alias_and_malformed_previous_schema(self):
        self.overlay()
        self.revision()
        (self.site / "agpc-voice.sh").write_bytes(b"alias only override")
        self.reject("alias differs from immutable signed record")
        path = self.site / "agpc-voice.source.json"
        record = json.loads(path.read_bytes())
        record.update(schema="agpc.voice-install-source/v2", installer_revision=True)
        path.write_text(json.dumps(record))
        self.reject("invalid installer revision")

    def test_revision_content_is_immutable_and_latest_cannot_downgrade(self):
        self.overlay()
        legacy = (dict(self.inputs), dict(self.receipt))
        self.revision(2)
        self.overlay()
        self.revision(1)
        self.reject("revision downgrade forbidden")
        self.inputs, self.receipt = legacy
        self.save()
        self.reject("revision downgrade forbidden")
        self.revision(2)
        target = self.site / "agpc-voice" / self.inputs["version"] / "installers/2/BUILD-RECEIPT.json"
        target.write_bytes(b"conflicting existing revision")
        self.reject("versioned Voice content is immutable")

    def test_v1_newer_component_still_replaces_v2_latest_alias(self):
        # The ordinary v1 fixture component is newer than this previous v2 record.
        (self.site / "agpc-voice.source.json").write_text(json.dumps(dict(
            schema="agpc.voice-install-source/v2", version="0.1.0~candidate.5", installer_revision=999999)))
        self.overlay()
        record = json.loads((self.site / "agpc-voice.source.json").read_text())
        self.assertEqual(record["schema"], "agpc.voice-install-source/v1")
        self.assertNotIn("installer_revision", record)

    def test_revision_keeps_main_review_and_original_component_gates(self):
        self.overlay()
        self.revision()
        self.reject("differs from component main CI", get_bytes=lambda path: b"substituted")
        def unapproved(path):
            return dict(approved=False, approved_by=[]) if path.endswith("/approvals") else self.api(path)
        self.reject("source review approval missing", get_json=unapproved)

    def test_latest_alias_cannot_downgrade(self):
        (self.site / "agpc-voice.source.json").write_text(json.dumps(dict(schema="agpc.voice-install-source/v1",
                                                                       version="0.1.0~candidate.7")))
        self.reject("downgrade forbidden")

    def test_extra_private_file_or_checksum_mutation_rejected(self):
        (self.bundle / "private.env").write_bytes(b"fixture private file")
        self.reject("unexpected or missing files")
        (self.bundle / "private.env").unlink()
        (self.bundle / "SHA256SUMS").write_text("a" * 64 + "  agpc-voice.sh\n")
        self.reject("checksum inventory mismatch")

    def test_artifact_hash_paths_duplicates_and_symlinks_rejected(self):
        for name, symlink in [("../private.env", False), ("agpc-voice-bundle/link", True),
                              ("agpc-voice-bundle/private.env", False)]:
            with self.subTest(name=name):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    member = zipfile.ZipInfo(name)
                    if symlink:
                        member.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(member, b"fixture")
                data = buffer.getvalue()
                record = {**self.inputs, "archive_bytes": len(data), "archive_sha256": native.digest(data)}
                with self.assertRaises(ValueError):
                    voice.extract_bundle(data, self.root / "extract", record)
        with self.assertRaisesRegex(ValueError, "artifact hash/size"):
            voice.extract_bundle(b"wrong", self.root / "extract", self.inputs)

    def test_workflow_reuses_existing_permissions_and_has_no_runtime_tests(self):
        new = (ROOT / ".github/workflows/publish-agpc-voice.yml").read_text()
        old = (ROOT / ".github/workflows/publish-voice-mote.yml").read_text()
        def permissions(text):
            return {line.strip() for line in re.search(r"permissions:\n(.*?)\nconcurrency:", text, re.S).group(1).splitlines()
                    if line.strip()}
        self.assertEqual(permissions(new), permissions(old))
        for value in ["group: medge-apt-pages", "environment: release", "refs/heads/main"]:
            self.assertIn(value, new)
        self.assertNotIn("unittest", new)
        self.assertNotIn("apt-get", new)
        self.assertNotIn("voice-mote.sh", new)


if __name__ == "__main__":
    unittest.main()
