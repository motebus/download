"""CX-Loop v6 composition, preserving the immutable v5 cohort contract."""

import copy
import subprocess
import tempfile
from pathlib import Path
import unittest

import test_full_agent_computer_overlay as f

p = f.p


class CxLoopOverlayTests(unittest.TestCase):
    def test_existing_published_v5_remains_valid(self):
        root = Path(__file__).resolve().parents[1]
        config = p.load_agent_computer_overlay(root)
        self.assertIn(config["schema"], (p.AGENT_COMPUTER_FULL_SCHEMA, p.AGENT_COMPUTER_LOOP_SCHEMA))
        if config["schema"] == p.AGENT_COMPUTER_FULL_SCHEMA:
            self.assertNotIn("cx-loop", p.canonical_packages(config))
        else:
            self.assertIn("cx-loop", p.canonical_packages(config))

    def test_v6_requires_loop_and_successful_main_evidence(self):
        config = f.config_fixture(loop=True)
        p.validate_full_overlay_config(config["release"], schema=config["schema"])
        self.assertEqual(len(p.canonical_packages(config)), 28)
        for mutation in ["remove", "unreviewed"]:
            altered = copy.deepcopy(config)
            if mutation == "remove":
                altered["release"]["packages"] = [x for x in altered["release"]["packages"] if x["name"] != "cx-loop"]
            else:
                next(x for x in altered["release"]["packages"] if x["name"] == "cx-loop")["provenance"][
                    "main_pipeline_id"] = None
            with self.assertRaises(p.PublishError):
                p.validate_full_overlay_config(altered["release"], schema=altered["schema"])

    def test_v6_owns_loop_in_core_and_daemon_transitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, bundle, _ = f.make_full_bundle(root, loop=True)
            p.load_agent_computer_overlay(root)
            p.validate_full_overlay_payload(config, bundle)
            self.assertIn("cx-loop", p.core_components(config))
            self.assertNotIn("uchatd", p.core_components(config))
            self.assertNotIn("uchat", p.core_components(config))

    def test_wrong_floors_or_direct_inbox_dependency_are_rejected(self):
        for owner, depends in [
            ("cx-loop", "uchatd (>= 0.1.0-1)"),
            ("cx-loop", "uchatd (>= 9.0.0-1), redis-server"),
            ("cx-loop", "uchatd (>= 9.0.0-1), inboxd"),
        ]:
            with self.subTest(depends=depends), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config, bundle, _ = f.make_full_bundle(root, loop=True)
                record = next(x for x in config["release"]["packages"] if x["name"] == owner)
                asset = f.make_deb(root / "mutated", record, depends)
                (bundle / asset.name).write_bytes(asset.read_bytes())
                with self.assertRaises((p.PublishError, subprocess.CalledProcessError)):
                    p.validate_full_overlay_payload(config, bundle)

    def test_headless_plan_requires_loop_and_shared_daemon_without_apps(self):
        config = f.config_fixture(loop=True)
        names = set(p.core_components(config)) | {"agent-sphere", "uchatd"}
        versions = {x["name"]: x["version"] for x in config["release"]["packages"]}
        output = "\n".join(f"Inst {name} ({versions[name]} stable)" for name in names)
        chosen = f.resolution.validate_plan(output, {"packages": []}, config)
        self.assertEqual(set(chosen), names)
        for name in ["cx-loop", "uchatd"]:
            with self.subTest(name=name), self.assertRaises(p.PublishError):
                f.resolution.validate_plan(output.replace(f"Inst {name} (9.0.0-1 stable)", ""), {"packages": []}, config)
        with self.assertRaises(p.PublishError):
            f.resolution.validate_plan(output + "\nInst uchat (9.0.0-1 stable)", {"packages": []}, config)

    def test_provider_gateway_abi_cannot_float_across_minor_versions(self):
        for depends in [
            "mote-mcpd (>= 3.1.0-1)",
            "mote-mcpd (>= 3.0.0-3), mote-mcpd (<< 3.2.0)",
            "mote-mcpd (>= 3.1.0-1), mote-mcpd (<< 4.0.0)",
        ]:
            with self.subTest(depends=depends), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config, bundle, _ = f.make_full_bundle(root, loop=True)
                record = next(x for x in config["release"]["packages"] if x["name"] == "mote-mcp-ultra")
                asset = f.make_deb(root / "mutated", record, depends)
                (bundle / asset.name).write_bytes(asset.read_bytes())
                with self.assertRaises(p.PublishError):
                    p.validate_full_overlay_payload(config, bundle)
