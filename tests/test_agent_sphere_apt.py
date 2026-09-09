from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import test_publish_apt as fixtures


MODULE = Path(__file__).parents[1] / "scripts/validate_agent_sphere_apt.py"
SPEC = importlib.util.spec_from_file_location("validate_agent_sphere_apt", MODULE)
assert SPEC and SPEC.loader
resolution = importlib.util.module_from_spec(SPEC)
with mock.patch.dict(sys.modules, {"publish_apt": fixtures.publish_apt}):
    SPEC.loader.exec_module(resolution)


class AgentSphereAptTest(unittest.TestCase):
    def fixture(self) -> tuple[dict, dict, str]:
        base = fixtures.PublicAptTest().manifest("medge-public-release/v18")
        packages = [{"name": name, "architecture": architecture, "version": version,
                     "asset": f"{name}_{version}_{architecture}.deb", "sha256": "a" * 64}
                    for name, architecture, version in (("agent-sphere", "all", "0.1.0-1"),
                                                       ("mote-transportd", "amd64", "2.0.0-5"))]
        overlay = {"schema": "agent-computer-apt-overlay/v1", "release": {
            "repository": "motebus/agent-sphere-deb", "tag": "v0.1.0-1", "packages": packages}}
        versions = {p["name"]: p["version"] for p in base["packages"] + packages}
        output = "Inst libc6 (2.39 Ubuntu:24.04 [amd64])\n" + "".join(
            f"Inst {name} ({versions[name]} MoteBus:stable [amd64])\n"
            for name in sorted(resolution.RUNTIME_PACKAGES | {"agent-sphere"}))
        return base, overlay, output

    def test_plan_requires_all_six_signed_versions_and_allows_only_os_additions(self) -> None:
        base, overlay, output = self.fixture()
        selected = resolution.validate_plan(output, base, overlay)
        self.assertEqual(len(selected), 8)
        for invalid in (
            output.replace("Inst mlink ", "Conf mlink "),
            output.replace("Inst mote-transportd (2.0.0-5", "Inst mote-transportd (2.0.0-4"),
            output + "Remv mote-chatd [2.0.0-4]\n",
            output + "Inst mote-secd (1.0.0-2 MoteBus:stable [amd64])\n",
            output + "Inst agent-sphere (0.1.0-1 MoteBus:stable [all])\n",
        ):
            with self.subTest(plan=invalid), self.assertRaises(fixtures.publish_apt.PublishError):
                resolution.validate_plan(invalid, base, overlay)

    def test_application_and_retired_packages_are_rejected_even_outside_base_catalog(self) -> None:
        base, overlay, output = self.fixture()
        for name in ("agos", "agent-app", "agent-apps", "aport", "mdesk", "ss-webos", "mote-bridge-mcp",
                     "cx-node", "codex-cli", "mcp-run", "ultra-mcp-ssh", "mote-chatd"):
            with self.subTest(package=name), self.assertRaises(fixtures.publish_apt.PublishError):
                resolution.validate_plan(output + f"Inst {name} (1.0.0-1 source [amd64])\n", base, overlay)

    def test_inactive_config_never_runs_docker_or_signing_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "agent-computer-apt-overlay.json").write_text(json.dumps({
                "schema": "agent-computer-apt-overlay/v1", "release": None}))
            with mock.patch.object(fixtures.publish_apt, "run") as run:
                resolution.validate_signed_index(root, root / "site")
                run.assert_not_called()

    def test_active_gate_verifies_signatures_then_resolves_single_package_in_both_clean_images(self) -> None:
        base, overlay, output = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            site.mkdir()
            for where in (root, site):
                (where / "agent-computer-apt-overlay.json").write_text(json.dumps(overlay))
                (where / "medge-archive-keyring.gpg").write_bytes(b"fixture-public-key")
            (site / "release-manifest.json").write_text(json.dumps(base))
            with mock.patch.object(fixtures.publish_apt, "run", return_value=output) as run:
                resolution.validate_signed_index(root, site)
                commands = [call.args for call in run.call_args_list]
            self.assertEqual([args[0] for args in commands], ["gpgv", "gpgv", "gpgv", "docker", "docker"])
            self.assertIn("apt-get --simulate --no-remove install agent-sphere", resolution.SIMULATION)
            self.assertNotIn("trusted=yes", resolution.SIMULATION)
            self.assertIn("Signed-By:", resolution.SIMULATION)
            for args, (version, image) in zip(commands[3:], resolution.UBUNTU_IMAGES):
                self.assertIn(image, args)
                self.assertEqual(args[-1], version)
                self.assertIn("--pull=always", args)
                self.assertIn(f"type=bind,src={site.resolve()},dst=/repo,readonly", args)

    def test_signed_overlay_drift_is_rejected_before_container_resolution(self) -> None:
        base, overlay, output = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            site.mkdir()
            for where in (root, site):
                (where / "agent-computer-apt-overlay.json").write_text(json.dumps(overlay))
                (where / "medge-archive-keyring.gpg").write_bytes(b"fixture-public-key")
            changed = copy.deepcopy(overlay)
            changed["release"]["packages"][0]["sha256"] = "b" * 64
            (site / "agent-computer-apt-overlay.json").write_text(json.dumps(changed))
            with mock.patch.object(fixtures.publish_apt, "run", return_value=output) as run:
                with self.assertRaisesRegex(fixtures.publish_apt.PublishError, "signed overlay differs"):
                    resolution.validate_signed_index(root, site)
                self.assertFalse(any(call.args[0] == "docker" for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
