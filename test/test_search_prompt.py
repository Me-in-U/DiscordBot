import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.search import SEARCH_PROMPT_ID, SEARCH_PROMPT_VERSION, SearchCommands


SEARCH_COG_PATH = Path("cogs/search/__init__.py")
LEGACY_SEARCH_COG_PATH = Path("cogs/search.py")


class SearchPromptTests(unittest.TestCase):
    def test_search_cog_uses_package_layout(self):
        self.assertTrue(SEARCH_COG_PATH.exists())
        self.assertFalse(LEGACY_SEARCH_COG_PATH.exists())

    def test_search_command_uses_prompt_version_8(self):
        self.assertEqual(
            SEARCH_PROMPT_ID,
            "pmpt_68b25c89c1a48193a60de5a3cb23a1eb0c25a13613efd1bf",
        )
        self.assertEqual(SEARCH_PROMPT_VERSION, "8")


class SearchImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_passes_optional_image_to_prompt(self):
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        image = Mock(url="https://example.com/search.png")
        captured_kwargs = {}

        def fake_custom_prompt_model(**kwargs):
            captured_kwargs.update(kwargs)
            return "검색 결과"

        cog = SearchCommands(Mock())
        with patch("cogs.search.custom_prompt_model", fake_custom_prompt_model):
            await cog.search.callback(cog, interaction, " 검색 요청 ", image)

        self.assertEqual(
            captured_kwargs["prompt"]["variables"],
            {"user_input": "검색 요청"},
        )
        self.assertEqual(
            captured_kwargs["image_content"][0]["content"][0],
            {
                "type": "input_image",
                "image_url": "https://example.com/search.png",
            },
        )
        interaction.followup.send.assert_awaited_once_with("검색 결과")


if __name__ == "__main__":
    unittest.main()
