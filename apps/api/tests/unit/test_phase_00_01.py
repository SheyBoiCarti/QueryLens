"""Unit tests for Phase 00 Task 00.01 (Repository layout, scripts, and ignores)."""

import json
from pathlib import Path
import unittest


class TestRepositoryLayout(unittest.TestCase):
    """Verify repository structure, required manifests, scripts, and ignores."""

    def setUp(self):
        self.root = Path(__file__).resolve().parents[4]

    def test_root_package_json_manifest_and_scripts(self):
        """Root package.json exists, declares workspaces and required scripts."""
        pkg_path = self.root / "package.json"
        self.assertTrue(pkg_path.is_file(), "package.json must exist in root")

        with open(pkg_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("workspaces", data)
        self.assertIn("apps/web", data["workspaces"])

        scripts = data.get("scripts", {})
        required_scripts = ["bootstrap", "dev", "seed", "lint", "typecheck", "test", "verify"]
        for s in required_scripts:
            self.assertIn(s, scripts, f"Missing required script '{s}' in package.json")

    def test_locks_exist(self):
        """package-lock.json and requirements.lock must exist."""
        pkg_lock = self.root / "package-lock.json"
        self.assertTrue(pkg_lock.is_file(), "package-lock.json must exist in root")

        py_lock = self.root / "apps" / "api" / "requirements.lock"
        self.assertTrue(py_lock.is_file(), "apps/api/requirements.lock must exist")

    def test_gitignore_rules(self):
        """.gitignore ignores .env, .venv, node_modules, keyrings, backups while preserving .env.example."""
        gitignore_path = self.root / ".gitignore"
        self.assertTrue(gitignore_path.is_file(), ".gitignore must exist")

        content = gitignore_path.read_text(encoding="utf-8")
        self.assertIn(".env", content)
        self.assertIn("!.env.example", content)
        self.assertIn(".venv", content)
        self.assertIn("node_modules", content)
        self.assertIn("*.keyring.json", content)
        self.assertIn("backups", content)

    def test_apps_directories(self):
        """apps/api and apps/web exist with respective project manifests."""
        api_pyproject = self.root / "apps" / "api" / "pyproject.toml"
        self.assertTrue(api_pyproject.is_file(), "apps/api/pyproject.toml must exist")

        web_pkg = self.root / "apps" / "web" / "package.json"
        self.assertTrue(web_pkg.is_file(), "apps/web/package.json must exist")


if __name__ == "__main__":
    unittest.main()
