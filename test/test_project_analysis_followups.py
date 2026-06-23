import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("OPENAI_KEY", "test-openai-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("RIOT_KEY", "test-riot-key")
os.environ.setdefault("SONPANNO_GUILD_ID", "123")
os.environ.setdefault("SSAFY_GUILD_ID", "456")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_DATABASE", "test")
os.environ.setdefault("DB_USERNAME", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("API_PORT", "1557")
os.environ.setdefault("CELEBRATION_UPDATE_API_KEY", "test")
os.environ.setdefault("ECOS_API_KEY", "test")


class DeploymentContractTests(unittest.TestCase):
    def test_docker_and_docs_use_python_311_baseline(self):
        dockerfile_deps = Path("Dockerfile.deps").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        agents = Path("AGENTS.md").read_text(encoding="utf-8")

        self.assertEqual(dockerfile_deps.count("FROM python:3.11-slim"), 2)
        self.assertNotIn("python:3.12", dockerfile_deps)
        self.assertIn("Python 3.11", readme)
        self.assertIn("Python 3.11", agents)

    def test_compose_exposes_env_file_to_runtime(self):
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("ENV_FILE=${ENV_FILE:-.env}", compose)

    def test_jenkins_runs_compile_and_unittest_before_deploy(self):
        text = Path("Jenkinsfile").read_text(encoding="utf-8")

        self.assertIn("stage('Verify')", text)
        self.assertLess(text.index("stage('Verify')"), text.index("stage('Deploy')"))
        self.assertIn("python --version", text)
        self.assertIn("git show --check --pretty=format: --no-ext-diff HEAD", text)
        self.assertIn(
            "python -m compileall -q bot.py api cogs common func util test",
            text,
        )
        self.assertIn("python -m unittest discover -s test", text)
        self.assertIn("docker run --rm", text)

    def test_jenkins_streams_workspace_into_docker_instead_of_bind_mounting(self):
        text = Path("Jenkinsfile").read_text(encoding="utf-8")

        self.assertNotIn('-v "$PWD:/app"', text)
        self.assertGreaterEqual(text.count("tar -cf -"), 2)
        self.assertGreaterEqual(text.count("tar -xf - -C /app"), 2)

    def test_jenkins_deps_image_cache_key_includes_dockerfile_deps(self):
        text = Path("Jenkinsfile").read_text(encoding="utf-8")

        self.assertGreaterEqual(text.count("sha256sum requirements.txt Dockerfile.deps"), 2)

    def test_jenkins_uses_dependency_venv_python_inside_docker(self):
        text = Path("Jenkinsfile").read_text(encoding="utf-8")

        self.assertNotIn("sh -lc '", text)
        self.assertIn("/opt/venv/bin/python --version", text)
        self.assertIn("/opt/venv/bin/python -m compileall", text)
        self.assertIn("/opt/venv/bin/python -m unittest discover -s test", text)
        self.assertIn("/opt/venv/bin/python scripts/migrate_db.py", text)

    def test_jenkins_runs_database_migration_before_deploy(self):
        text = Path("Jenkinsfile").read_text(encoding="utf-8")

        self.assertIn("stage('Migrate Database')", text)
        self.assertLess(
            text.index("stage('Migrate Database')"),
            text.index("stage('Deploy')"),
        )
        self.assertIn("python scripts/migrate_db.py", text)

    def test_readme_and_agents_document_current_test_contract(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        agents = Path("AGENTS.md").read_text(encoding="utf-8")

        for text in (readme, agents):
            self.assertIn("python -m compileall -q bot.py api cogs common func util test", text)
            self.assertIn("python -m unittest discover -s test", text)
            self.assertIn("test/`는 importable package가 아니", text)

        self.assertNotIn("No formal unit test suite", agents)
        self.assertIn("requirements.txt", agents)

    def test_deploy_docs_include_runtime_resource_guidance(self):
        deploy_doc = Path("docs/jenkins-deploy.md").read_text(encoding="utf-8")

        self.assertIn("권장 운영 리소스", deploy_doc)
        self.assertIn("mem_limit: 500m", deploy_doc)
        self.assertIn("YouTube 요약", deploy_doc)
        self.assertIn("STT", deploy_doc)
        self.assertIn("health check", deploy_doc)


class StartupGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_on_ready_runs_startup_only_once(self):
        import bot

        bot._startup_completed = False
        sync = AsyncMock(return_value=[])

        with patch("bot.load_variable", new=AsyncMock()) as load_variable:
            with patch("bot.update_db_info", new=AsyncMock()) as update_db_info:
                with patch.object(bot.DISCORD_CLIENT.tree, "sync", new=sync):
                    await bot.on_ready()
                    await bot.on_ready()

        self.assertEqual(load_variable.await_count, 1)
        self.assertEqual(update_db_info.await_count, 1)
        self.assertEqual(sync.await_count, 1)

    def test_build_party_list_recalculates_without_duplicate_append(self):
        import bot

        class Category:
            def __init__(self, name: str) -> None:
                self.name = name

        class Guild:
            def __init__(self) -> None:
                self.id = 123
                self.name = "guild"
                self.categories = [
                    Category("레이드-파티"),
                    Category("잡담"),
                ]

        first = bot.build_party_list([Guild()])
        second = bot.build_party_list([Guild()])

        self.assertEqual([category.name for category in first[123]], ["레이드-파티"])
        self.assertEqual([category.name for category in second[123]], ["레이드-파티"])
        self.assertIsNot(first, second)


class DbMigrationContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_validates_schema_without_running_migrations(self):
        import bot

        with patch("bot.ensure_schema_ready", new=AsyncMock()) as ensure_schema_ready:
            with patch("bot.upsert_guild", new=AsyncMock()):
                with patch("bot.upsert_user", new=AsyncMock()):
                    await bot.update_db_info()

        ensure_schema_ready.assert_awaited_once()

    def test_db_module_exposes_schema_version_and_migration_entrypoints(self):
        import util.db as db

        self.assertIsInstance(db.DB_SCHEMA_VERSION, int)
        self.assertGreaterEqual(db.DB_SCHEMA_VERSION, 1)
        self.assertTrue(callable(db.run_schema_migrations))
        self.assertTrue(callable(db.ensure_schema_ready))
        self.assertTrue(callable(db.get_schema_version))
        self.assertIn(
            "schema_migrations",
            Path("util/db.py").read_text(encoding="utf-8"),
        )

    def test_migration_script_invokes_schema_migrations(self):
        source = Path("scripts/migrate_db.py").read_text(encoding="utf-8")

        self.assertIn("asyncio.run", source)
        self.assertIn("run_schema_migrations", source)
        self.assertIn("close_db_pool", source)

    def test_status_api_exposes_schema_version_in_health_payload(self):
        source = Path("cogs/status_api.py").read_text(encoding="utf-8")

        self.assertIn("DB_SCHEMA_VERSION", source)
        self.assertIn('"schema_version"', source)


class CogLoadPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_cog_failure_does_not_stop_remaining_loads(self):
        import bot

        loaded: list[str] = []

        async def fake_load_extension(extension: str) -> None:
            if extension == "cogs.optional_bad":
                raise RuntimeError("broken optional")
            loaded.append(extension)

        with patch("bot.discover_cog_extensions", return_value=["cogs.optional_bad", "cogs.good"]):
            with patch.object(bot, "REQUIRED_COGS", {"cogs.required"}):
                with patch.object(
                    bot.DISCORD_CLIENT,
                    "load_extension",
                    side_effect=fake_load_extension,
                ):
                    with self.assertLogs("bot", level="ERROR") as captured:
                        await bot.load_cogs()

        self.assertEqual(loaded, ["cogs.good"])
        self.assertIn("cogs.optional_bad", "\n".join(captured.output))

    async def test_required_cog_failure_raises_startup_error(self):
        import bot

        async def fake_load_extension(extension: str) -> None:
            raise RuntimeError(f"broken {extension}")

        with patch("bot.discover_cog_extensions", return_value=["cogs.status_api"]):
            with patch.object(bot, "REQUIRED_COGS", {"cogs.status_api"}):
                with patch.object(
                    bot.DISCORD_CLIENT,
                    "load_extension",
                    side_effect=fake_load_extension,
                ):
                    with self.assertLogs("bot", level="ERROR") as captured:
                        with self.assertRaises(bot.RequiredCogLoadError):
                            await bot.load_cogs()

        self.assertIn("cogs.status_api", "\n".join(captured.output))


class SensitiveLogPolicyTests(unittest.TestCase):
    def test_chatgpt_helpers_do_not_print_full_response_object(self):
        import api.chatGPT as chatgpt

        class FakeResponse:
            output_text = "요약 결과"

        with patch.object(
            chatgpt.clientGPT.responses,
            "create",
            return_value=FakeResponse(),
        ):
            with patch("builtins.print") as print_mock:
                self.assertEqual(
                    chatgpt.custom_prompt_model(prompt={"id": "pmpt_test"}),
                    "요약 결과",
                )
                self.assertEqual(
                    chatgpt.generate_text_model("입력", "지시"),
                    "요약 결과",
                )

        print_mock.assert_not_called()

    def test_chatgpt_helpers_wrap_client_failures_in_domain_error(self):
        import api.chatGPT as chatgpt

        with patch.object(
            chatgpt.clientGPT.responses,
            "create",
            side_effect=RuntimeError("secret-token"),
        ):
            with self.assertRaises(chatgpt.OpenAIModelError) as captured:
                chatgpt.generate_text_model("입력", "지시")

        self.assertIsInstance(captured.exception.__cause__, RuntimeError)
        self.assertNotIn("secret-token", str(captured.exception))


class WebSubTokenPolicyTests(unittest.TestCase):
    def test_websub_token_is_required_for_deploy_env(self):
        from cogs.status_api import get_youtube_websub_verify_token

        with patch.dict(
            os.environ,
            {
                "ENV_FILE": ".env.deploy",
                "YOUTUBE_WEBSUB_VERIFY_TOKEN": "",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_youtube_websub_verify_token()

    def test_websub_token_can_be_omitted_for_local_env(self):
        from cogs.status_api import get_youtube_websub_verify_token

        with patch.dict(
            os.environ,
            {
                "ENV_FILE": ".env",
                "YOUTUBE_WEBSUB_VERIFY_TOKEN": "",
            },
            clear=False,
        ):
            with self.assertLogs("cogs.status_api", level="WARNING") as captured:
                token = get_youtube_websub_verify_token()

        self.assertEqual(token, "")
        self.assertIn("YOUTUBE_WEBSUB_VERIFY_TOKEN", "\n".join(captured.output))


class YouTubeTempWorkspaceTests(unittest.TestCase):
    def test_youtube_api_adapter_returns_title_and_wraps_failures(self):
        from func.youtube_api import YouTubeApiError, fetch_video_title

        class FakeRequest:
            def __init__(self, response=None, error=None):
                self.response = response
                self.error = error

            def execute(self):
                if self.error:
                    raise self.error
                return self.response

        class FakeVideos:
            def __init__(self, request):
                self.request = request

            def list(self, **_kwargs):
                return self.request

        class FakeService:
            def __init__(self, request):
                self.request = request

            def videos(self):
                return FakeVideos(self.request)

        success_request = FakeRequest(
            {"items": [{"snippet": {"title": "테스트 영상"}}]}
        )
        with patch("func.youtube_api.build", return_value=FakeService(success_request)):
            self.assertEqual(fetch_video_title("video-id"), "테스트 영상")

        failure_request = FakeRequest(error=ValueError("secret-token"))
        with patch("func.youtube_api.build", return_value=FakeService(failure_request)):
            with self.assertRaises(YouTubeApiError) as captured:
                fetch_video_title("video-id")

        self.assertIsInstance(captured.exception.__cause__, ValueError)
        self.assertNotIn("secret-token", str(captured.exception))

    def test_youtube_link_parser_module_exposes_link_helpers(self):
        from func.youtube_links import (
            YOUTUBE_POST_KIND,
            YOUTUBE_VIDEO_KIND,
            extract_post_id,
            extract_video_id,
            extract_youtube_links,
            get_youtube_link_kind,
            normalize_youtube_link,
        )

        self.assertEqual(
            normalize_youtube_link("https://youtube.com/shorts/abc123"),
            "https://youtube.com/watch?v=abc123",
        )
        self.assertEqual(
            extract_youtube_links(
                "a https://youtu.be/video1 b https://youtube.com/post/UgkxPost"
            ),
            ["https://youtu.be/video1", "https://youtube.com/post/UgkxPost"],
        )
        self.assertEqual(get_youtube_link_kind("https://youtu.be/video1"), YOUTUBE_VIDEO_KIND)
        self.assertEqual(
            get_youtube_link_kind("https://youtube.com/post/UgkxPost"),
            YOUTUBE_POST_KIND,
        )
        self.assertEqual(extract_video_id("https://youtube.com/watch?v=video1"), "video1")
        self.assertEqual(extract_post_id("https://youtube.com/post/UgkxPost"), "UgkxPost")

    def test_youtube_workspace_helper_builds_scoped_paths_and_cleans_up(self):
        from func.youtube_workspace import (
            subtitle_output_template,
            youtube_audio_path,
            youtube_summary_workspace,
        )

        with youtube_summary_workspace() as workspace:
            workspace_path = workspace
            audio_path = youtube_audio_path(workspace)
            subtitle_template = Path(subtitle_output_template(workspace))
            audio_path.write_text("audio", encoding="utf-8")

            self.assertTrue(audio_path.is_relative_to(workspace))
            self.assertEqual(audio_path.name, "youtube_audio.mp3")
            self.assertTrue(subtitle_template.is_relative_to(workspace))
            self.assertEqual(subtitle_template.name, "youtube_subtitles.%(ext)s")

        self.assertFalse(workspace_path.exists())

    def test_download_youtube_subtitles_uses_requested_output_dir(self):
        import func.youtube_summary as youtube_summary

        captured_opts = {}

        class FakeYDL:
            def __init__(self, opts):
                captured_opts.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def download(self, _urls):
                output_file = captured_opts["outtmpl"].replace("%(ext)s", "ko.vtt")
                Path(output_file).write_text("WEBVTT\n자막", encoding="utf-8")

        with tempfile.TemporaryDirectory() as workspace:
            with patch("func.youtube_media.YoutubeDL", FakeYDL):
                subtitle_path = youtube_summary.download_youtube_subtitles(
                    "https://youtu.be/test-video",
                    output_dir=workspace,
                )

            workspace_path = Path(workspace).resolve()
            self.assertTrue(Path(subtitle_path).resolve().is_relative_to(workspace_path))
            self.assertTrue(
                Path(captured_opts["outtmpl"]).resolve().is_relative_to(workspace_path)
            )


class YouTubeProcessWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_youtube_link_wraps_failures_in_domain_error(self):
        import func.youtube_summary as youtube_summary

        with patch(
            "func.youtube_processor.process_youtube_video_link",
            side_effect=ValueError("secret-token"),
        ):
            with self.assertRaises(youtube_summary.YouTubeSummaryError) as captured:
                await youtube_summary.process_youtube_link("https://youtu.be/test-video")

        self.assertIsInstance(captured.exception.__cause__, ValueError)
        self.assertNotIn("secret-token", str(captured.exception))

    async def test_process_youtube_video_link_cleans_request_workspace(self):
        import func.youtube_summary as youtube_summary

        workspaces: list[Path] = []

        def fake_download_subtitles(_url, primary_lang, fallback_lang, output_dir):
            workspace = Path(output_dir)
            workspaces.append(workspace)
            subtitle_file = workspace / "youtube_subtitles.ko.vtt"
            subtitle_file.write_text("WEBVTT\n요약할 자막", encoding="utf-8")
            return str(subtitle_file)

        with patch("func.youtube_processor.extract_video_id", return_value="video-id"):
            with patch("func.youtube_processor.is_live_video", return_value=False):
                with patch(
                    "func.youtube_processor.download_youtube_subtitles",
                    side_effect=fake_download_subtitles,
                ):
                    with patch(
                        "func.youtube_processor.read_subtitles_file",
                        return_value="요약할 자막",
                    ):
                        with patch(
                            "func.youtube_processor.summarize_text_with_gpt",
                            new=AsyncMock(return_value="영상 요약"),
                        ):
                            with patch(
                                "func.youtube_processor.fetch_youtube_comments",
                                return_value=[],
                            ):
                                result = await youtube_summary.process_youtube_video_link(
                                    "https://youtu.be/test-video"
                                )

        self.assertEqual(result, "영상 요약")
        self.assertEqual(len(workspaces), 1)
        self.assertFalse(workspaces[0].exists())

    async def test_process_youtube_video_link_keeps_summary_when_comments_fail(self):
        import func.youtube_summary as youtube_summary

        with patch("func.youtube_processor.extract_video_id", return_value="video-id"):
            with patch("func.youtube_processor.is_live_video", return_value=False):
                with patch("func.youtube_processor.download_youtube_subtitles", return_value=""):
                    with patch("func.youtube_processor.youtube_to_mp3", new=AsyncMock()):
                        with patch(
                            "func.youtube_processor.speech_to_text",
                            new=AsyncMock(return_value="STT 텍스트"),
                        ):
                            with patch(
                                "func.youtube_processor.summarize_text_with_gpt",
                                new=AsyncMock(return_value="영상 요약"),
                            ):
                                with patch(
                                    "func.youtube_processor.fetch_youtube_comments",
                                    side_effect=youtube_summary.YouTubeApiError(
                                        "comment failure"
                                    ),
                                ):
                                    with self.assertLogs(
                                        "func.youtube_processor",
                                        level="WARNING",
                                    ):
                                        result = await youtube_summary.process_youtube_video_link(
                                            "https://youtu.be/test-video"
                                        )

        self.assertEqual(result, "영상 요약")


if __name__ == "__main__":
    unittest.main()
