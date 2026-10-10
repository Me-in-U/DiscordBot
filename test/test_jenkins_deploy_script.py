import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


BASH = shutil.which("bash") if os.name == "posix" else shutil.which(
    "bash.exe", path=str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin"),
)


@unittest.skipUnless(BASH, "Deployment script requires Bash or Git Bash")
class JenkinsDeployScriptTests(unittest.TestCase):
    def run_deploy(self, *, dockerfile="FROM python:3.11-slim\n", health="ok"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "bin").mkdir()
            script = root / "scripts" / "jenkins_deploy.sh"
            script.write_text(Path("scripts/jenkins_deploy.sh").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            (root / "requirements.txt").write_text("aiohttp==3.13.3\n")
            (root / "Dockerfile.deps").write_text(dockerfile)
            (root / ".env").write_text("EXAMPLE=value\n")
            command_log = root / "commands.log"
            for name, content in {
                "docker": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\nexit 0\n',
                "curl": '#!/bin/sh\nif [ "$FAKE_HEALTH" = fail ]; then echo "curl: (52) Empty reply from server" >&2; exit 52; fi\nexit 0\n',
            }.items():
                executable = root / "bin" / name
                executable.write_text(content, newline="\n")
                executable.chmod(0o755)
            env = os.environ.copy()
            env.pop("DEPS_IMAGE", None)
            env.update({
                "PATH": f"{root / 'bin'}{os.pathsep}{env['PATH']}",
                "TEST_BIN": (f"/{root.drive[0].lower()}{root.as_posix()[2:]}/bin" if os.name == "nt" else str(root / "bin")),
                "TEST_SCRIPT": script.as_posix(),
                "ENV_FILE": ".env",
                "COMMAND_LOG": command_log.as_posix(),
                "FAKE_HEALTH": health,
                "HEALTHCHECK_MAX_ATTEMPTS": "2",
                "HEALTHCHECK_INTERVAL_SECONDS": "0",
            })
            result = subprocess.run([BASH, "--noprofile", "--norc", "-c", 'export PATH="$TEST_BIN:$PATH"; source "$TEST_SCRIPT"'], env=env, capture_output=True, text=True, timeout=20)
            commands = command_log.read_text()
        return result, commands

    def test_dockerfile_change_changes_runtime_dependency_image(self):
        first, first_commands = self.run_deploy()
        second, second_commands = self.run_deploy(dockerfile="FROM python:3.11-slim\nRUN echo changed\n")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        first_image = next(line for line in first_commands.splitlines() if line.startswith("image inspect "))
        second_image = next(line for line in second_commands.splitlines() if line.startswith("image inspect "))
        self.assertNotEqual(first_image, second_image)

    def test_health_failure_reports_last_error_and_fails_deploy(self):
        result, commands = self.run_deploy(health="fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Waiting for bot health check (2/2)", result.stdout)
        self.assertEqual(result.stdout.count("Empty reply from server"), 1)
        self.assertIn("[ERROR] Last health check response:", result.stdout)
        self.assertNotIn("[SUCCESS]", result.stdout)
