import ast
import unittest
from pathlib import Path


STATUS_API_COG_PATH = Path("cogs/status_api/__init__.py")
LEGACY_STATUS_API_COG_PATH = Path("cogs/status_api.py")


class StatusApiCogLayoutTests(unittest.TestCase):
    def test_status_api_cog_uses_package_layout(self):
        self.assertTrue(STATUS_API_COG_PATH.exists())
        self.assertFalse(LEGACY_STATUS_API_COG_PATH.exists())

    def test_status_api_routes_remain_exposed_from_package_cog(self):
        tree = ast.parse(STATUS_API_COG_PATH.read_text(encoding="utf-8"))
        route_constants: dict[str, str] = {}
        class_names: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_names.add(node.name)
                if node.name != "StatusApi":
                    continue
                for stmt in node.body:
                    if not (
                        isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)
                    ):
                        continue
                    route_constants[stmt.targets[0].id] = stmt.value.value

        self.assertIn("StatusApi", class_names)
        self.assertEqual(route_constants["CELEBRATION_UPDATE_PATH"], "/celebration/update")
        self.assertEqual(route_constants["YOUTUBE_WEBSUB_PATH"], "/youtube/websub")


if __name__ == "__main__":
    unittest.main()
