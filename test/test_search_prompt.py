import os
import unittest
from pathlib import Path

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.search import SEARCH_PROMPT_ID, SEARCH_PROMPT_VERSION


SEARCH_COG_PATH = Path("cogs/search/__init__.py")
LEGACY_SEARCH_COG_PATH = Path("cogs/search.py")


class SearchPromptTests(unittest.TestCase):
    def test_search_cog_uses_package_layout(self):
        self.assertTrue(SEARCH_COG_PATH.exists())
        self.assertFalse(LEGACY_SEARCH_COG_PATH.exists())

    def test_search_command_uses_prompt_version_6(self):
        self.assertEqual(
            SEARCH_PROMPT_ID,
            "pmpt_68b25c89c1a48193a60de5a3cb23a1eb0c25a13613efd1bf",
        )
        self.assertEqual(SEARCH_PROMPT_VERSION, "6")


if __name__ == "__main__":
    unittest.main()
