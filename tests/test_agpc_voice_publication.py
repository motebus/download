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
        return dict(id=job, status="success", ref="main", commit=dict(id=commit),
                    pipeline=dict(id=project, sha=commit, ref="main"))

    def component(self, endpoint):
        return next((self.bundle / "packages").glob("agpc-voice_*.deb")).read_bytes()

    def sign(self, root, site, names):
        for name in names:
            (site / (name + ".asc")).write_bytes(b"fixture signature")

    def overlay(self, get_json=None, get_bytes=None):
        with patch.object(native, "sign_files", side_effect=self.sign), patch.object(voice, "verify_signature"):
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
