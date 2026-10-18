"""Phase 10 safety net: docs, artifact policy and repository hygiene.

These tests require neither a game account nor a GitHub Actions paid runner.
"""
from pathlib import Path
import unittest

from tools import audit_repository


ROOT = Path(__file__).resolve().parents[1]


class DocumentationAndReleaseAudit(unittest.TestCase):
    def test_all_relative_markdown_links_resolve(self):
        documents = audit_repository.markdown_files(ROOT)
        self.assertIn(ROOT / "wlre/resources/assets/buttons/SOURCE.md", documents)
        self.assertIn(ROOT / "wlre/resources/assets/function-icons/SOURCE.md", documents)
        self.assertGreaterEqual(len(documents), 20)
        checked, broken = audit_repository.invalid_links(ROOT)
        self.assertGreater(checked, 100)
        self.assertEqual(broken, [], "Broken local Markdown references: " + repr(broken))

    def test_no_identical_nonempty_tracked_files(self):
        duplicates = audit_repository.duplicate_tracked_blobs(ROOT)
        if duplicates is None:
            self.skipTest("Git index unavailable, e.g. a source-only export")
        self.assertEqual(duplicates, [])

    def test_dev_readme_does_not_impersonate_unpublished_release(self):
        version = audit_repository.application_version(ROOT)
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "版本歷史.md").read_text(encoding="utf-8")
        self.assertIn("v0.6.0 開發版", readme)
        self.assertIn("v" + version, readme)
        self.assertIn("2026-10-17", changelog)
        self.assertIn("releases/tag/v0.5.0", readme)
        self.assertIn("不是正式發布", changelog)

    def test_actions_run_full_regressions_and_native_pr_builds(self):
        daily = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        native = (ROOT / ".github/workflows/desktop-packaging.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/release-windows.yml").read_text(encoding="utf-8")
        self.assertIn('os: [ubuntu-latest, windows-2022, macos-15]', daily)
        self.assertIn('python -m tools.audit_repository --strict-git', daily)
        self.assertIn('python -m compileall -q', daily)
        self.assertIn('tools.build.build_macos --arch arm64 --dry-run', daily)
        self.assertIn('tools.build.build_macos --arch x64 --dry-run', daily)
        self.assertIn("workflow_dispatch:", native)
        native_triggers = native.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("pull_request:", native_triggers)
        self.assertIn("tools/build/**", native_triggers)
        self.assertIn("tags:", release)
        self.assertIn("build_macos:", release)

    def test_legacy_compatibility_and_experience_regressions_retained(self):
        for relative in (
            "tests/test_exp_efficiency_regression.py",
            "wlre/core/efficiency.py",
            "wlre/services/expedition_data.py",
            "wlre/services/expedition_teams.py",
            "wlre/ui/expedition_ui.py",
            "wlre/ui/minimap.py",
            "docs/README_v0.5.0.md",
        ):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())


if __name__ == "__main__":
    unittest.main()
