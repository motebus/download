from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).parents[1] / 'scripts/native_install_policy.py'
SPEC = importlib.util.spec_from_file_location('native_policy_fixture', MODULE)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class NativeInstallPolicyTest(unittest.TestCase):
    def package(self, root, *, depends='libc6', hook='#!/bin/sh\nexit 0\n', unit='ExecStart=/usr/bin/native-runtime\n', user=False):
        stage = root / 'stage'
        (stage / 'DEBIAN').mkdir(parents=True)
        (stage / 'DEBIAN/control').write_text('Package: native-policy-fixture\nVersion: 1\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\nDescription: Native policy fixture\nDepends: '+depends+'\n')
        (stage / 'DEBIAN/postinst').write_text(hook)
        (stage / 'DEBIAN/postinst').chmod(0o755)
        units=stage/('usr/lib/systemd/user' if user else 'usr/lib/systemd/system');units.mkdir(parents=True)
        (units/'fixture.service').write_text('[Service]\n'+unit)
        output=root/'fixture.deb'
        subprocess.run(['dpkg-deb','--build','--root-owner-group','-Zgzip',str(stage),str(output)],check=True,capture_output=True)
        return output

    def test_actual_archives_reject_runtime_dependency_hook_and_unit(self):
        for kwargs in ({'depends':'libc6, docker.io'},
                       {'hook':'#!/bin/sh\n/usr/bin/podman info\n'},
                       {'unit':'ExecStart=-/usr/bin/env FOO=bar /usr/bin/docker run image\n'}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError,'container runtime'):
                    policy.audit_deb(self.package(Path(folder),**kwargs))

    def test_actual_system_and_user_units_reject_dependency_and_socket_grants(self):
        for user in (False, True):
            for directive in ('Requires=docker.service', 'Requires = docker.service',
                              'ExecStart = /usr/bin/docker info', 'Requisite=containerd.service',
                              'Wants=podman.socket', 'BindsTo=containerd.socket',
                              'BindPaths=-/run/docker.sock',
                              'BindReadOnlyPaths=/run/podman/podman.sock:/run/engine.sock'):
                with self.subTest(user=user,directive=directive), tempfile.TemporaryDirectory() as folder:
                    with self.assertRaisesRegex(ValueError,'container runtime'):
                        policy.audit_deb(self.package(Path(folder),unit=directive+'\n',user=user))

    def test_socket_denial_comments_and_diagnostic_arguments_are_not_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            deb=self.package(Path(folder),hook='#!/bin/sh\n# docker is not used\necho docker\nexit 0\n',
                unit='ExecStart=/usr/bin/native-runtime\nInaccessiblePaths=-/run/docker.sock -/var/run/docker.sock\n')
            self.assertEqual(policy.audit_deb(deb),{'asset':'fixture.deb','hooks':1,'units':1})

    def test_all_automatic_relationships_and_alternatives_are_checked(self):
        for field in ('Depends','Pre-Depends','Recommends'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,'container runtime packages'):
                policy.dependencies({field:'libc6 | podman (>= 1)'})
        policy.dependencies({'Depends':'libc6, init-system-helpers','Suggests':'docker.io'})

    def test_runtime_package_families_include_multiarch_without_rejecting_native_names(self):
        for name in ('docker.io:amd64','docker-ce-cli','moby-engine','podman-docker','containerd.io','runc','crun','buildah','nerdctl','cri-o','lxc-utils','lxd','incus','systemd-container'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                policy.reject_runtime_packages([name])
        policy.reject_runtime_packages(['libc6','liblxc1','native-docker-diagnostic-docs'])

    def test_direct_literal_shell_command_and_continued_unit_are_checked(self):
        for text in ('/bin/sh -c "docker info"', '/usr/bin/env FOO=bar podman run image',
                     'if docker info; then exit 1; fi', 'exec /usr/bin/docker \\\n info'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                policy.direct_command(text)
