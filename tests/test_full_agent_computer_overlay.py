from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import test_publish_apt as fixtures
import test_agent_sphere_apt as apt_fixtures

p = fixtures.publish_apt
resolution = apt_fixtures.resolution


def config_fixture(loop=False):
    proof = {"source_commit": "a" * 40, "source_ref": "refs/heads/main", "main_pipeline_id": 123,
             "build_status": "success", "public_payload_reviewed": True}
    def record(name):
        architecture = "all" if name in ("agent-sphere", "agent-ultra", "agent-apps", "jujue", "mote-chatd") else "amd64"
        version = "3.1.0-1" if loop and name == "mote-mcpd" else "9.0.0-1"
        return {"name": name, "version": version, "architecture": architecture,
                "asset": f"{name}_{version}_{architecture}.deb", "sha256": "b" * 64,
                "provenance": copy.deepcopy(proof)}
    return {"schema": p.AGENT_COMPUTER_LOOP_SCHEMA if loop else p.AGENT_COMPUTER_FULL_SCHEMA, "release": {
        "repository": "motebus/download", "tag": "agent-computer-v0.1.0-1", "source_commit": "c" * 40,
        "packages": [record(name) for name in (p.AGENT_LOOP_REDISTRIBUTABLE if loop else p.AGENT_COMPUTER_REDISTRIBUTABLE)],
        "retention_packages": [record("mote-chatd")],
        "external_prerequisites": [{"name": "obsidian", "version": "1.13.7", "architecture": "amd64",
            "asset": "obsidian_1.13.7_amd64.deb", "sha256": "d" * 64, "redistribute": False,
            "url": "https://github.com/obsidianmd/obsidian-releases/releases/download/v1.13.7/obsidian_1.13.7_amd64.deb"}]}}


def write_config(root, config):
    (root / p.AGENT_COMPUTER_OVERLAY_FILE).write_text(json.dumps(config))


def make_deb(root, package, depends=None, payload=None, fields=None):
    asset = fixtures.PublicAptTest().make_deb(root, package=package["name"], version=package["version"],
                                            architecture=package["architecture"])
    stage = root / ("package-" + package["name"])
    if depends:
        with (stage / "DEBIAN/control").open("a") as handle:
            handle.write("Depends: " + depends + "\n")
    if fields:
        with (stage / "DEBIAN/control").open("a") as handle:
            for key, value in fields.items():
                handle.write(f"{key}: {value}\n")
    for name, data in (payload or {}).items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    stage.chmod(0o755)
    for path in stage.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)
    subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(stage), str(asset)],
                   check=True, stdout=subprocess.DEVNULL)
    package["sha256"] = p.sha256(asset)
    return asset


def make_full_bundle(root, loop=False):
    config = config_fixture(loop=loop)
    bundle = root / "overlay"
    bundle.mkdir()
    versions = {x["name"]: x["version"] for x in config["release"]["packages"] + config["release"]["external_prerequisites"]}
    for package in p.overlay_packages(config):
        dependencies = None
        if package["name"] in p.AGENT_META_DEPENDENCIES:
            names = p.core_components(config) if package["name"] == "agent-sphere" else p.AGENT_META_DEPENDENCIES[package["name"]]
            dependencies = ", ".join(f"{name} (>= {versions[name]})" for name in names)
        elif package["name"] == "cx-loop":
            dependencies = "uchatd (>= 9.0.0-1)"
        elif package["name"] == "mote-mcp-ultra":
            dependencies = "mote-mcpd (>= 3.1.0-1), mote-mcpd (<< 3.2.0)"
        elif package["name"] == "uchat":
            dependencies = "uchatd (>= 9.0.0-1)"
        elif package["name"] == "uchatd":
            dependencies = "redis-server (>= 5:6.2), mote-transportd (>= 9.0.0-1)"
        asset = make_deb(root / "build", package, dependencies)
        shutil.copy2(asset, bundle)
    external = root / "external"
    external.mkdir()
    package = config["release"]["external_prerequisites"][0]
    shutil.copy2(make_deb(root / "external-build", package), external)
    write_config(root, config)
    return config, bundle, external


class FullAgentComputerOverlayTest(unittest.TestCase):
    def test_actual_archives_reject_writable_units_and_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = next(x for x in config_fixture()["release"]["packages"] if x["name"] == "agos")
            for relative, mode in (("usr/lib/systemd/system/agosd.service", 0o666),
                                   ("usr/lib/systemd", 0o777)):
                with self.subTest(path=relative):
                    case = root / str(mode)
                    asset = make_deb(case, package, payload={
                        "usr/lib/systemd/system/agosd.service": "[Service]\nExecStart=/usr/sbin/agosd\n"})
                    stage = case / "package-agos"
                    (stage / "DEBIAN/postinst").write_text("#!/bin/sh\nexit 0\n")
                    (stage / "DEBIAN/postinst").chmod(0o755)
                    target = stage / relative
                    target.chmod(mode)
                    subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(stage), str(asset)],
                                   check=True, stdout=subprocess.DEVNULL)
                    with self.assertRaisesRegex(p.PublishError, "unsafe archive permissions"):
                        p.validate_deb_archive_permissions(asset)
                    target.chmod(0o755 if target.is_dir() or relative == "DEBIAN/postinst" else 0o644)
                    subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(stage), str(asset)],
                                   check=True, stdout=subprocess.DEVNULL)
                    p.validate_deb_archive_permissions(asset)

    def test_v3_signatures_bind_root_blocker_and_immutable_legacy_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            (site / "dists/stable").mkdir(parents=True)
            (site / "dists/stable/Release").write_text("Suite: stable\n")
            config = config_fixture()
            write_config(root, config)
            write_config(site, config)
            base = fixtures.PublicAptTest().manifest()
            manifest = json.dumps(base)
            (site / "release-manifest.json").write_text(manifest)
            legacy = site / "legacy" / ("medge-v" + base["medge_version"])
            legacy.mkdir(parents=True)
            (legacy / "release-manifest.json").write_text(manifest)
            for name in (*p.AGENT_INSTALLER_FILES, "uninstall.sh"):
                shutil.copy2(Path(__file__).parents[1] / name, root)
                shutil.copy2(root / name, site)
            gnupg = root / "fixture-gnupg"
            gnupg.mkdir(mode=0o700)
            env = {**os.environ, "GNUPGHOME": str(gnupg), "MEDGE_APT_SIGNING_PASSPHRASE": "fixture-only-passphrase"}
            subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "fixture-only-passphrase",
                "--quick-gen-key", "Agent Computer Fixture <fixture@example.invalid>", "rsa2048", "sign", "1d"],
                env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result = subprocess.run(["gpg", "--batch", "--with-colons", "--list-secret-keys"],
                                    env=env, check=True, text=True, capture_output=True).stdout
            fingerprint = next(line.split(":")[9] for line in result.splitlines() if line.startswith("fpr:"))
            (root / "medge-archive-keyring.fingerprint").write_text(fingerprint)
            key = root / "medge-archive-keyring.gpg"
            key.write_bytes(subprocess.check_output(["gpg", "--batch", "--export", fingerprint], env=env))
            with mock.patch.dict(os.environ, env):
                p.sign_release(site, root)
            for where, name in ((site, "uninstall.sh"), (site, p.AGENT_COMPUTER_OVERLAY_FILE),
                                (legacy, "release-manifest.json")):
                subprocess.run(["gpgv", "--keyring", str(key), str(where / (name + ".asc")), str(where / name)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertEqual((legacy / "release-manifest.json").read_text(), manifest)
            (site / "uninstall.sh").write_text("#!/bin/sh\nexit 0\n")
            result = subprocess.run(["gpgv", "--keyring", str(key), str(site / "uninstall.sh.asc"), str(site / "uninstall.sh")],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertNotEqual(result.returncode, 0)

    def test_exact_canonical_membership_provenance_and_upstream_authority(self):
        config = config_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_config(root, config)
            self.assertEqual(p.load_agent_computer_overlay(root), config)
            self.assertEqual(len(p.AGENT_COMPUTER_CANONICAL), 27)
            self.assertEqual(len(p.AGENT_SPHERE_COMPONENTS), 11)
            self.assertEqual(len(p.AGENT_APPS_COMPONENTS), 5)
            mutations = [
                lambda r: r.update(repository="motebus/agent-sphere-deb"),
                lambda r: r.update(tag="latest"),
                lambda r: r.update(source_commit="main"),
                lambda r: r["packages"].reverse(),
                lambda r: r["packages"].pop(),
                lambda r: r["packages"][0].update(name="agent-app"),
                lambda r: r["packages"][0].update(version="0.1.0-1~local20260909"),
                lambda r: r["packages"][0].update(architecture="amd64"),
                lambda r: r["packages"][0].update(asset="../escape.deb"),
                lambda r: r["packages"][0]["provenance"].update(build_status="pending"),
                lambda r: r["packages"][0]["provenance"].update(source_ref="refs/heads/topic"),
                lambda r: r["packages"][0]["provenance"].update(main_pipeline_id=True),
                lambda r: r["packages"][0]["provenance"].update(public_payload_reviewed=False),
                lambda r: r["external_prerequisites"][0].update(redistribute=True),
                lambda r: r["external_prerequisites"][0].update(url="https://example.invalid/obsidian.deb"),
                lambda r: r["external_prerequisites"].clear(),
                lambda r: r["retention_packages"].append(copy.deepcopy(r["retention_packages"][0])),
                lambda r: r["retention_packages"][0].update(name="cx-node"),
                lambda r: r.update(allow_retired_runtime=True),
            ]
            for mutation in mutations:
                changed = copy.deepcopy(config)
                mutation(changed["release"])
                write_config(root, changed)
                with self.subTest(config=changed), self.assertRaises(p.PublishError):
                    p.load_agent_computer_overlay(root)

    def test_real_debs_enforce_meta_ownership_locked_identity_and_retention_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, bundle, external = make_full_bundle(root)
            self.assertEqual(p.validate_agent_computer_overlay(root, bundle), config)
            p.validate_agent_computer_prerequisites(config, external)
            sphere = config["release"]["packages"][0]
            good = (bundle / sphere["asset"]).read_bytes()
            bad = make_deb(root / "wrong-owner", sphere, "agos (>= 9.0.0-1)")
            shutil.copy2(bad, bundle)
            write_config(root, config)
            with self.assertRaisesRegex(p.PublishError, "direct dependency ownership"):
                p.validate_agent_computer_overlay(root, bundle)

            (bundle / sphere["asset"]).write_bytes(good)
            sphere["sha256"] = p.sha256(bundle / sphere["asset"])
            guard = config["release"]["retention_packages"][0]
            bad = make_deb(root / "bad-guard", guard, payload={"usr/bin/mote-chatd": "retired executable"})
            shutil.copy2(bad, bundle)
            write_config(root, config)
            with self.assertRaisesRegex(p.PublishError, "documentation only"):
                p.validate_agent_computer_overlay(root, bundle)
            bad = make_deb(root / "bad-identity", guard,
                           payload={"etc/mote/mote-chatd/mote-chatd-mchat.env": "fixture=only"})
            shutil.copy2(bad, bundle)
            write_config(root, config)
            with self.assertRaisesRegex(p.PublishError, "locked deployment identity"):
                p.validate_agent_computer_overlay(root, bundle)

    def test_uchat_archives_require_private_redis_and_safe_transport(self):
        for name, depends in (("uchat", "redis-server, uchatd (>= 9.0.0-1)"),
                              ("uchat", "libc6"),
                              ("uchatd", "redis-server (>= 5:6.2), mote-transportd (>= 2.0.0-5)"),
                              ("uchatd", "redis-server (>= 6.2), mote-transportd (>= 9.0.0-1)")):
            with self.subTest(package=name, depends=depends), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config, bundle, _ = make_full_bundle(root)
                package = next(p for p in config["release"]["packages"] if p["name"] == name)
                shutil.copy2(make_deb(root / "changed", package, depends), bundle)
                write_config(root, config)
                with self.assertRaises((p.PublishError, subprocess.CalledProcessError)):
                    p.validate_agent_computer_overlay(root, bundle)

    def test_external_prerequisite_is_separate_exact_and_not_an_overlay_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, bundle, external = make_full_bundle(root)
            package = config["release"]["external_prerequisites"][0]
            asset = external / package["asset"]
            shutil.copy2(asset, bundle)
            with self.assertRaisesRegex(p.PublishError, "exactly the approved assets"):
                p.validate_agent_computer_overlay(root, bundle)
            asset.write_bytes(asset.read_bytes() + b"changed")
            with self.assertRaisesRegex(p.PublishError, "digest differs"):
                p.validate_agent_computer_prerequisites(config, external)

    def test_transitive_bridge_dependency_cannot_restore_retired_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, bundle, _ = make_full_bundle(root)
            package = next(x for x in config["release"]["packages"] if x["name"] == "cx-mesh")
            asset = make_deb(root / "old-dependency", package, "mote-bridge-mcp (>= 3.0.0-2)")
            shutil.copy2(asset, bundle)
            write_config(root, config)
            with self.assertRaisesRegex(p.PublishError, "Depends retains the retired mote-bridge-mcp"):
                p.validate_agent_computer_overlay(root, bundle)

    def test_real_debs_reject_cycles_ui_backedges_and_retired_cx_providers(self):
        cases = [
            ('moted', {'Depends': 'agent-sphere (>= 9.0.0-1)'}, 'circular canonical'),
            ('agos', {'Pre-Depends': 'agent-sphere (>= 9.0.0-1)'}, 'circular canonical'),
            ('agos', {'Depends': 'agpc-manager (>= 9.0.0-1)'}, 'management UI'),
            ('cx-mesh', {'Provides': 'cx-agent'}, 'retired cx-agent'),
            ('cx-mesh', {'Provides': 'codex-mesh'}, 'retired codex-mesh'),
            *[('agpc-manager', {field: 'sphere-manager (= 3.1.0-1)'},
               f'{field} retains the retired sphere-manager')
              for field in ('Depends', 'Pre-Depends', 'Recommends', 'Suggests', 'Provides')],
        ]
        for name, fields, error in cases:
            with self.subTest(name=name, fields=fields), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config, bundle, _ = make_full_bundle(root)
                package = next(x for x in config['release']['packages'] if x['name'] == name)
                asset = make_deb(root / 'invalid-edge', package, fields=fields)
                shutil.copy2(asset, bundle)
                write_config(root, config)
                with self.assertRaisesRegex(p.PublishError, error):
                    p.validate_agent_computer_overlay(root, bundle)

    def test_manager_replacement_relationships_do_not_restore_retired_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, bundle, _ = make_full_bundle(root)
            package = next(x for x in config['release']['packages'] if x['name'] == 'agpc-manager')
            asset = make_deb(root / 'reviewed-replacement', package, fields={
                'Conflicts': 'sphere-manager', 'Replaces': 'sphere-manager'})
            shutil.copy2(asset, bundle)
            write_config(root, config)
            p.validate_agent_computer_overlay(root, bundle)

    def test_aggregate_tag_sha_and_exact_deb_allowlist_are_required_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = config_fixture()
            write_config(root, config)
            release = config["release"]
            good = {"tagName": release["tag"], "isDraft": False,
                    "assets": [{"name": x["asset"]} for x in p.overlay_packages(config)]}
            cases = [(good, "f" * 40, "source commit"),
                     ({**good, "assets": good["assets"] + [{"name": "obsidian_1.13.7_amd64.deb"}]},
                      release["source_commit"], "undeclared DEBs")]
            for metadata, commit, error in cases:
                with mock.patch.object(p, "run", side_effect=[json.dumps(metadata), json.dumps({"sha": commit})]) as run:
                    with self.assertRaisesRegex(p.PublishError, error):
                        p.download_agent_computer_overlay(root, root / "destination")
                    self.assertFalse(any(call.args[:3] == ("gh", "release", "download") for call in run.call_args_list))
            p.validate_agent_computer_release_tag(root, release["tag"])
            with self.assertRaisesRegex(p.PublishError, "dispatch tag"):
                p.validate_agent_computer_release_tag(root, "agent-computer-v0.1.0-2")

    def test_v19_history_and_same_name_versions_remain_byte_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, overlay, external = make_full_bundle(root)
            bundle = root / "base"
            bundle.mkdir()
            base = fixtures.PublicAptTest().manifest()
            for package in base["packages"]:
                shutil.copy2(make_deb(root / "base-build", package), bundle)
            for installer in base["installers"]:
                path = bundle / installer["name"]
                path.write_text("#!/bin/bash\nset -euo pipefail\n")
                path.chmod(0o755)
                installer["sha256"] = p.sha256(path)
            manifest = bundle / "release-manifest.json"
            manifest.write_text(json.dumps(base))
            (bundle / "SHA256SUMS").write_text("".join(f"{p.sha256(path)}  {path.name}\n" for path in sorted(bundle.iterdir())))
            repository = Path(__file__).parents[1]
            for name in ("medge-archive-keyring.gpg", "medge-archive-keyring.fingerprint", "medge.sources",
                         *p.AGENT_INSTALLER_FILES, "uninstall.sh"):
                shutil.copy2(repository / name, root)
            site = root / "site"
            with mock.patch.object(p, "sign_release"):
                p.build_site(root, site, [bundle], overlay)
            resolution.validate_full_index_pins(site, config)
            self.assertEqual((site / "release-manifest.json").read_bytes(), manifest.read_bytes())
            for package in base["packages"]:
                copies = list((site / "pool").rglob(package["asset"]))
                self.assertEqual(len(copies), 1)
                self.assertEqual(p.sha256(copies[0]), package["sha256"])
            self.assertFalse(list(site.rglob("obsidian*.deb")))
            self.assertEqual(len(p.EXPECTED_PACKAGES_V19), 18)
            for script in base["installers"]:
                if script["name"] == "uninstall.sh":
                    legacy = site / "legacy" / ("medge-v" + base["medge_version"])
                    self.assertEqual((legacy / "uninstall.sh").read_bytes(), (bundle / "uninstall.sh").read_bytes())
                    self.assertEqual((legacy / "release-manifest.json").read_bytes(), manifest.read_bytes())
                    self.assertEqual((site / "uninstall.sh").read_bytes(), (repository / "uninstall.sh").read_bytes())
                    self.assertNotEqual(p.sha256(site / "uninstall.sh"), script["sha256"])
                else:
                    self.assertEqual((site / script["name"]).read_bytes(), (bundle / script["name"]).read_bytes())
            sphere_output = "".join(f"Inst {x['name']} ({x['version']} MoteBus:stable [amd64])\n"
                for x in config["release"]["packages"] if x["name"] in resolution.CURRENT_RUNTIME_PACKAGES | {"agent-sphere"})
            full_output = "Prerequisite obsidian 1.13.7\n" + "".join(
                f"Inst {x['name']} ({x['version']} MoteBus:stable [amd64])\n" for x in config["release"]["packages"])
            full_output += "".join(f"InstalledAGPC\t{x['name']}\t{x['version']}\tii \n"
                for x in config["release"]["packages"] + config["release"]["external_prerequisites"])
            commands = []
            original = p.run
            def run(*args, **kwargs):
                commands.append(args)
                if args[0] == "gpgv":
                    return ""
                if args[0] == "docker":
                    return full_output if resolution.FULL_SIMULATION in args else sphere_output
                return original(*args, **kwargs)
            with mock.patch.object(p, "run", side_effect=run):
                resolution.validate_signed_index(root, site, external)
            docker = [args for args in commands if args[0] == "docker"]
            self.assertEqual(len(docker), 4)
            self.assertEqual([args[0] for args in commands[:3]], ["gpgv"] * 3)
            self.assertEqual(sum(resolution.FULL_SIMULATION in args for args in docker), 2)
            for args in docker:
                self.assertIn("--pull=always", args)
                if resolution.FULL_SIMULATION in args:
                    self.assertIn(f"type=bind,src={external.resolve()},dst=/prerequisites,readonly", args)
            item = config["release"]["packages"][0]
            asset = next((site / "pool").rglob(item["asset"]))
            asset.write_bytes(asset.read_bytes() + b"tamper")
            with self.assertRaisesRegex(p.PublishError, "payload differs"):
                resolution.validate_full_index_pins(site, config)

    def test_full_resolution_requires_every_canonical_pin_and_no_retired_or_guard(self):
        config = config_fixture()
        base = fixtures.PublicAptTest().manifest()
        output = "Prerequisite obsidian 1.13.7\n" + "".join(
            f"Inst {item['name']} ({item['version']} MoteBus:stable [amd64])\n" for item in config["release"]["packages"])
        resolution.validate_plan(output, base, config, full=True)
        for name in p.AGENT_COMPUTER_RETIRED | {"aport", "qbix"}:
            with self.subTest(name=name), self.assertRaises(p.PublishError):
                resolution.validate_plan(output + f"Inst {name} (9.0.0-1 MoteBus:stable [amd64])\n", base, config, full=True)
        for bad in (output.replace("Inst medge ", "Conf medge "), output.replace("1.13.7", "1.13.6"),
                    output.replace("Inst agos (9.0.0-1", "Inst agos (2.0.0-1"), output + "Remv unrelated [1]\n"):
            with self.assertRaises(p.PublishError):
                resolution.validate_plan(bad, base, config, full=True)
        self.assertIn("apt-get --simulate --no-remove install agent-sphere agent-ultra agpc-manager agent-apps", resolution.FULL_SIMULATION)
        self.assertNotIn("trusted=yes", resolution.FULL_SIMULATION)
        self.assertNotIn("install agent-sphere\n", resolution.FULL_SIMULATION)


if __name__ == "__main__":
    unittest.main()
