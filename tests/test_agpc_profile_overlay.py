"""Native v7 ownership and separate standard/full provenance, retaining v1/v5/v6."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import test_full_agent_computer_overlay as f

p = f.p
REPOSITORY = Path(__file__).resolve().parents[1]


def config_fixture():
    config = f.config_fixture(loop=True)
    config["schema"] = p.AGENT_COMPUTER_PROFILE_SCHEMA
    records = {r["name"]: r for r in config["release"]["packages"]}
    records["agpc-apps"] = records.pop("agent-apps")
    records["contextd"] = copy.deepcopy(records["uchatd"])
    packages = []
    for name in p.AGENT_PROFILE_REDISTRIBUTABLE:
        record = records[name]
        record["name"] = name
        record["version"] = p.AGENT_PROFILE_FLOORS.get(name, record["version"])
        record["asset"] = f"{name}_{record['version']}_{record['architecture']}.deb"
        packages.append(record)
    config["release"]["packages"] = packages
    transition = copy.deepcopy(records["agpc-apps"])
    transition.update(name="agent-apps", asset="agent-apps_0.3.0-1_all.deb")
    config["release"]["retention_packages"] = []
    config["release"]["retention_packages"].append(transition)
    return config


def make_bundle(root):
    config = config_fixture()
    bundle = root / "overlay"
    bundle.mkdir()
    versions = {r["name"]: r["version"] for r in
                config["release"]["packages"] + config["release"]["external_prerequisites"]}
    meta = {**p.AGENT_META_DEPENDENCIES, "agent-sphere": p.core_components(config)}
    meta["agpc-apps"] = meta.pop("agent-apps")
    for record in p.overlay_packages(config):
        name = record["name"]
        if name in meta:
            depends = ", ".join(f"{dep} (>= {versions[dep]})" for dep in meta[name])
        elif name == "agent-apps":
            depends = "agpc-apps (= 0.3.0-1)"
        elif name in ("uchat", "cx-loop"):
            depends = "uchatd (>= 0.5.0-1)"
        elif name == "uchatd":
            depends = "redis-server (>= 5:6.2), mote-transportd (>= 9.0.0-1)"
        elif name == "mote-mcp-ultra":
            depends = "mote-mcpd (>= 3.1.0-1), mote-mcpd (<< 3.2.0)"
        else:
            depends = None
        shutil.copy2(f.make_deb(root / "build", record, depends), bundle)
    f.write_config(root, config)
    return config, bundle


class NativeProfileOverlayTests(unittest.TestCase):
    def test_v7_exact_order_core_ownership_and_optional_retention(self):
        config = config_fixture()
        expected = [name for old in p.AGENT_LOOP_REDISTRIBUTABLE for name in
                    (["agpc-apps"] if old == "agent-apps" else
                     [old, "contextd"] if old == "cx-loop" else [old])]
        self.assertEqual(list(p.canonical_packages(config)), expected)
        self.assertEqual(expected.count("uchatd"), 1)
        self.assertEqual(p.core_components(config), (*p.AGENT_LOOP_SPHERE_COMPONENTS, "contextd", "uchatd"))
        self.assertNotIn("agent-apps", expected)
        self.assertNotIn("uchat", p.core_components(config))
        for retain in ([], ["agent-apps"]):
            changed = copy.deepcopy(config)
            changed["release"]["retention_packages"] = [r for r in config["release"]["retention_packages"]
                                                       if r["name"] in retain]
            p.validate_full_overlay_config(changed["release"], schema=changed["schema"])
        for mutation in (
            lambda r: r["packages"].reverse(),
            lambda r: r["packages"].pop(),
            lambda r: r["retention_packages"].append(copy.deepcopy(r["retention_packages"][-1])),
            lambda r: r["retention_packages"][-1].update(version="0.3.0-2", asset="agent-apps_0.3.0-2_all.deb"),
            lambda r: r["packages"][0]["provenance"].update(public_payload_reviewed=False),
        ):
            changed = copy.deepcopy(config)
            mutation(changed["release"])
            with self.assertRaises(p.PublishError):
                p.validate_full_overlay_config(changed["release"], schema=changed["schema"])

    def test_historical_v5_v6_compositions_still_validate(self):
        for loop in (False, True):
            config = f.config_fixture(loop=loop)
            p.validate_full_overlay_config(config["release"], schema=config["schema"])
            self.assertIn("agent-apps", p.canonical_packages(config))
            self.assertNotIn("contextd", p.core_components(config))
            self.assertNotIn("uchatd", p.core_components(config))

    def test_v7_version_floors_are_fail_closed(self):
        for name in p.AGENT_PROFILE_FLOORS:
            config = config_fixture()
            record = next(r for r in config["release"]["packages"] if r["name"] == name)
            record.update(version="0.0.0-1", asset=f"{name}_0.0.0-1_{record['architecture']}.deb")
            with self.subTest(package=name), self.assertRaises(subprocess.CalledProcessError):
                p.validate_full_overlay_config(config["release"], schema=config["schema"])

    def test_actual_debs_validate_native_ownership_and_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, bundle = make_bundle(root)
            self.assertEqual(p.validate_agent_computer_overlay(root, bundle), config)
            core = config["release"]["packages"][0]
            original = (bundle / core["asset"]).read_bytes()
            good_depends = p.package_field(bundle / core["asset"], "Depends")
            for bad in (good_depends.replace("contextd (>= 0.1.0-19)", "contextd (>= 0.0.0-1)"),
                        good_depends.replace(", uchatd (>= 0.5.0-1)", ""),
                        good_depends + ", agpc-manager (>= 9.0.0-1)"):
                shutil.copy2(f.make_deb(root / f"bad-core-{len(list(root.iterdir()))}", core, bad), bundle)
                with self.assertRaises((p.PublishError, subprocess.CalledProcessError)):
                    p.validate_full_overlay_payload(config, bundle)
            (bundle / core["asset"]).write_bytes(original)
            transition = config["release"]["retention_packages"][-1]
            for depends, payload, fields in (
                ("agpc-apps (>= 0.3.0-1)", None, None),
                ("agpc-apps (= 0.3.0-1), libc6", None, None),
                ("agpc-apps (= 0.3.0-1)", {"usr/bin/agent-apps": "runtime"}, None),
                ("agpc-apps (= 0.3.0-1)", None, {"Provides": "agent-apps"}),
                ("agpc-apps (= 0.3.0-1)", None, {"Recommends": "codd"}),
            ):
                case = root / f"bad-transition-{len(list(root.iterdir()))}"
                shutil.copy2(f.make_deb(case, transition, depends, payload, fields), bundle)
                with self.assertRaises(p.PublishError):
                    p.validate_full_overlay_payload(config, bundle)
            case = root / "transition-script"
            asset = f.make_deb(case, transition, "agpc-apps (= 0.3.0-1)")
            stage = case / "package-agent-apps"
            script = stage / "DEBIAN/postinst"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o755)
            subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(stage), str(asset)],
                           check=True, stdout=subprocess.DEVNULL)
            shutil.copy2(asset, bundle)
            with self.assertRaisesRegex(p.PublishError, "must not carry maintainer scripts"):
                p.validate_full_overlay_payload(config, bundle)

    def test_v7_uchat_floor_and_no_cloud_or_old_apps_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, bundle = make_bundle(root)
            approved = {r["name"]: r for r in config["release"]["packages"] + config["release"]["external_prerequisites"]}
            apps = approved["agpc-apps"]
            original = (bundle / apps["asset"]).read_bytes()
            depends = p.package_field(bundle / apps["asset"], "Depends")
            shutil.copy2(f.make_deb(root / "bad-apps", apps,
                                  depends.replace("uchat (>= 3.2.0-5)", "uchat (>= 3.1.0-1)")), bundle)
            with self.assertRaises(subprocess.CalledProcessError):
                p.validate_uchat_dependencies(bundle, approved, apps_owner="agpc-apps", native_profile=True)
            (bundle / apps["asset"]).write_bytes(original)
            for forbidden in ("codd", "agent-apps"):
                context = approved["contextd"]
                shutil.copy2(f.make_deb(root / forbidden, context, forbidden), bundle)
                with self.assertRaisesRegex(p.PublishError, "old Apps or cloud codd"):
                    p.validate_profile_dependencies(bundle, approved)


class NativeProfileInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in p.AGENT_INSTALLER_FILES:
            shutil.copy2(REPOSITORY / name, self.root)

    def test_current_v2_profiles_return_standard_and_alias_full(self):
        record = p.validate_agent_apps_installer(self.root)
        self.assertEqual((record["schema"], record["asset"], record["profile"]),
                         (p.AGENT_PROFILE_INSTALLER_SCHEMA, "agpc.sh", "standard"))
        self.assertEqual((self.root / "agent-sphere-apps.sh").read_bytes(),
                         (self.root / "agpc-all.sh").read_bytes())
        self.assertNotEqual((self.root / "agpc.sh").read_bytes(), (self.root / "agpc-all.sh").read_bytes())

    def test_v1_contract_needs_no_full_files(self):
        record = json.loads((self.root / "agpc.source.json").read_text())
        record.pop("profile")
        record["schema"] = p.AGENT_APPS_INSTALLER_SCHEMA
        (self.root / "agpc.source.json").write_text(json.dumps(record))
        for canonical, alias in zip(("agpc.sh", "agpc.source.json"), p.AGENT_INSTALLER_ALIASES):
            shutil.copy2(self.root / canonical, self.root / alias)
        for name in p.AGENT_FULL_INSTALLER_FILES:
            (self.root / name).unlink()
        self.assertEqual(p.validate_agent_apps_installer(self.root), record)
        self.assertFalse(set(p.AGENT_FULL_INSTALLER_FILES) & set(p.agent_installer_files(self.root)))

    def test_v2_rejects_profile_release_field_digest_and_alias_drift(self):
        path = self.root / "agpc-all.source.json"
        original = path.read_bytes()
        for changes in ({"profile": "standard"}, {"asset": "agpc.sh"},
                        {"source_commit": "b" * 40}, {"tag": "v0.3.0-3"},
                        {"schema": p.AGENT_APPS_INSTALLER_SCHEMA}, {"sha256": "a" * 64},
                        {"unreviewed": True}):
            record = json.loads(original)
            record.update(changes)
            path.write_text(json.dumps(record))
            with self.subTest(changes=changes), self.assertRaises(p.PublishError):
                p.validate_agent_apps_installer(self.root)
        path.write_bytes(original)
        shutil.copy2(self.root / "agpc.sh", self.root / p.AGENT_INSTALLER_ALIASES[0])
        with self.assertRaisesRegex(p.PublishError, "alias differs"):
            p.validate_agent_apps_installer(self.root)

    def test_v2_rejects_missing_symlinked_or_nonexecutable_full(self):
        for name in p.AGENT_FULL_INSTALLER_FILES:
            path = self.root / name
            original, mode = path.read_bytes(), path.stat().st_mode
            path.unlink()
            with self.assertRaisesRegex(p.PublishError, "missing regular"):
                p.validate_agent_apps_installer(self.root)
            path.symlink_to(REPOSITORY / name)
            with self.assertRaisesRegex(p.PublishError, "missing regular"):
                p.validate_agent_apps_installer(self.root)
            path.unlink()
            path.write_bytes(original)
            path.chmod(mode)
        (self.root / "agpc-all.sh").chmod(0o644)
        with self.assertRaisesRegex(p.PublishError, "must be executable"):
            p.validate_agent_apps_installer(self.root)

    def test_signing_binds_full_bytes_before_reading_secret_key(self):
        site = self.root / "site"
        site.mkdir()
        for name in p.AGENT_INSTALLER_FILES:
            shutil.copy2(self.root / name, site)
        full = site / "agpc-all.sh"
        full.write_bytes(full.read_bytes() + b"# changed\n")
        record = json.loads((site / "agpc-all.source.json").read_text())
        record["sha256"] = p.sha256(full)
        (site / "agpc-all.source.json").write_text(json.dumps(record))
        for canonical, alias in zip(p.AGENT_FULL_INSTALLER_FILES, p.AGENT_INSTALLER_ALIASES):
            shutil.copy2(site / canonical, site / alias)
        with mock.patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(
                p.PublishError, "staged full installer differs"):
            p.sign_release(site, self.root)


if __name__ == "__main__":
    unittest.main()
