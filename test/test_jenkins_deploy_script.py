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
    def run_deploy(self, *, dockerfile="FROM python:3.11-slim\n", health="ok", previous=""):
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
                "docker": '#!/bin/sh\nprintf "%s\\n" "$* image=$BOT_IMAGE" >> "$COMMAND_LOG"\nif [ "$1" = inspect ]; then echo "$FAKE_PREVIOUS"; fi\nexit 0\n',
                "curl": '#!/bin/sh\nif [ "$FAKE_HEALTH" = recover ]; then count=0; [ ! -f "$COMMAND_LOG.count" ] || count=$(cat "$COMMAND_LOG.count"); count=$((count+1)); echo "$count" > "$COMMAND_LOG.count"; [ "$count" -gt 2 ] && exit 0; fi\nif [ "$FAKE_HEALTH" != ok ]; then echo "curl: (52) Empty reply from server" >&2; exit 52; fi\nexit 0\n',
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
                "FAKE_PREVIOUS": previous,
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

    def test_health_failure_attempts_previous_image_rollback(self):
        result, commands = self.run_deploy(health="fail", previous="sha256:previous")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Restoring previous application image", result.stdout)
        self.assertIn("--force-recreate discord-bot image=sha256:previous", commands)
        self.assertIn("Rollback did not become healthy", result.stdout)

    def test_rollback_restores_health_but_keeps_build_failed(self):
        result, commands = self.run_deploy(health="recover", previous="sha256:previous")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Previous application restored. Deployment remains failed", result.stdout)
        self.assertNotIn("[SUCCESS]", result.stdout)
        self.assertIn("--force-recreate discord-bot image=sha256:previous", commands)
