from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/publish_sphere_runner.py"
SPEC = importlib.util.spec_from_file_location("publish_sphere_runner", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class SphereRunnerReleaseTests(unittest.TestCase):
    def test_public_source_and_approved_admission_validate(self) -> None:
        admission = runner.validate_source(ROOT / "sphere-runner")
        self.assertEqual(admission["status"], "approved")
        self.assertEqual(admission["release_version"], "5.2.0-3")
        self.assertEqual([item["id"] for item in admission["targets"]], ["L1", "L9"])

    def test_stage_is_exact_and_finalize_binds_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "dist"
            runner.stage(ROOT / "sphere-runner", output)
            artifact_map = json.loads((output / ".artifact-map.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [item["name"] for item in artifact_map["artifacts"]],
                [item[0] for item in runner.ARTIFACTS],
            )
            for item in artifact_map["artifacts"]:
                (output / (item["name"] + ".asc")).write_text("test signature\n", encoding="utf-8")
            runner.finalize(output, "a" * 40)
            manifest = runner.validate_dist(output)
            self.assertEqual(manifest["tag"], "sphere-runner-v5.2.0-3-7")
            bootstrap = next(item for item in manifest["artifacts"] if item["name"].startswith("bootstrap-"))
            self.assertEqual(bootstrap["targets"], ["BOOTSTRAP"])

    def test_private_key_or_extra_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "sphere-runner"
            import shutil

            shutil.copytree(ROOT / "sphere-runner", source)
            (source / "private.pem").write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
            with self.assertRaises(runner.RunnerReleaseError):
                runner.validate_source(source)


if __name__ == "__main__":
    unittest.main()
