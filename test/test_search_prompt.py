import os
import unittest

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.search import SEARCH_PROMPT_ID, SEARCH_PROMPT_VERSION


class SearchPromptTests(unittest.TestCase):
    def test_search_command_uses_prompt_version_5(self):
        self.assertEqual(
            SEARCH_PROMPT_ID,
            "pmpt_68b25c89c1a48193a60de5a3cb23a1eb0c25a13613efd1bf",
        )
        self.assertEqual(SEARCH_PROMPT_VERSION, "5")


if __name__ == "__main__":
    unittest.main()
