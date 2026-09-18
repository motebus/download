"""Module-scoped tests; these do not assert macOS or remote runtime readiness."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agpc-mac.sh"


def run_function(body):
    return subprocess.run(
        ["/bin/bash", "-c", 'source "$1"; ' + body, "test", str(SCRIPT)],
        text=True, capture_output=True,
    )


class BootstrapTests(unittest.TestCase):
    def test_pipe_invocation(self):
        result = subprocess.run(["/bin/bash", "-s", "--", "--plan"],
                                input=SCRIPT.read_text(), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ubuntu 26.04 OCI release pending", result.stdout)

    def test_help_and_plan(self):
        for arg in ("--help", "--plan"):
            result = subprocess.run(["/bin/bash", str(SCRIPT), arg], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Phases 3–9 are planned, not implemented", result.stdout)

    def test_unknown_arguments(self):
        for args in (("--yes",), ("--check", "--plan")):
            self.assertEqual(subprocess.run(
                ["/bin/bash", str(SCRIPT), *args], capture_output=True
            ).returncode, 2)

    def test_endpoint_normalization(self):
        for raw, expected in (("Mac-Studio", "mac-studio"), ("My Mac", "my-mac"),
                              ("-MAC---01-", "mac-01")):
            result = run_function('normalize_hostname "' + raw + '"')
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), expected)
        for raw in ("", "---", "local", "LOCAL", "a" * 64):
            self.assertNotEqual(run_function('normalize_hostname "' + raw + '"').returncode, 0)

    def test_platform_matrix(self):
        for os_name, arch, version, expected in (
            ("Linux", "arm64", "15.0", 1),
            ("Darwin", "x86_64", "15.0", 1),
            ("Darwin", "arm64", "13.7", 1),
            ("Darwin", "arm64", "14.0", 0),
            ("Darwin", "arm64", "14.7", 0),
            ("Darwin", "x86_64", "14.7", 1),
            ("Darwin", "arm64", "bad", 1),
            ("Darwin", "arm64", "15.0", 0),
            ("Darwin", "arm64", "26.0", 0),
        ):
            body = ('uname() { if [[ $1 == -s ]]; then echo ' + os_name +
                    '; else echo ' + arch + '; fi; }; '
                    'sw_vers() { echo ' + version + '; }; platform_check')
            self.assertEqual(run_function(body).returncode, expected, body)

    def test_release_cannot_report_success(self):
        result = run_function("release_gate")
        self.assertEqual(result.returncode, 78)
        self.assertIn("NOT complete", result.stderr)

    def test_docker_version_gate(self):
        for actual, required, expected in (("14.0", "14", 0), ("14.7", "14.8", 1),
                                            ("26.0", "15.0", 0), ("bad", "14", 1)):
            result = run_function(f'version_at_least "{actual}" "{required}"')
            self.assertEqual(result.returncode, expected)

    def test_bad_docker_digest_rejected(self):
        result = run_function('shasum() { echo "bad  fixture"; }; verify_docker_digest fixture')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)

    def test_ready_docker_is_preserved(self):
        result = run_function('DOCKER_BIN=/bin/bash; docker_info() { return 0; }; '
                              'install_docker_desktop() { exit 90; }; '
                              'launchctl() { exit 91; }; ensure_docker_desktop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preserved", result.stdout)

    def test_docker_timeout_is_failure(self):
        result = run_function('docker_info() { return 1; }; sleep() { :; }; wait_for_docker')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not ready", result.stderr)

    def test_source_is_inert(self):
        result = run_function(":")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout + result.stderr, "")


if __name__ == "__main__":
    unittest.main()
