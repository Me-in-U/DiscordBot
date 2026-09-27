import os
import unittest

os.environ.setdefault("OPENAI_KEY", "test-key")

from cogs.questions import GENERAL_PROMPT_VERSION, GOD_QUESTION_PROMPT_VERSION
from func.find1557 import FIND1557_FROM_IMAGE_PROMPT_VERSION


class AiPromptVersionTests(unittest.TestCase):
    def test_question_prompts_use_published_versions(self):
        self.assertEqual(GENERAL_PROMPT_VERSION, "10")
        self.assertEqual(GOD_QUESTION_PROMPT_VERSION, "10")

    def test_find1557_uses_published_version(self):
        self.assertEqual(FIND1557_FROM_IMAGE_PROMPT_VERSION, "9")


if __name__ == "__main__":
    unittest.main()
