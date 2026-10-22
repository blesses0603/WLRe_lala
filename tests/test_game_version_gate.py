"""Official server version is the ONLY gate; local game files do not matter."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.game_version_gate import configured_sources, run_prelogin_check


def response(main="1262", data="1262", *, state="same_resources"):
    return {
        "status": state,
        "packages": {
            "MainPackage": {"remote": main,
                            "comparison": "same" if main == "1262" else "newer"},
            "DataPackage": {"remote": data,
                            "comparison": "same" if data == "1262" else "newer"},
        },
        "protocol_compatibility": "unverified",
    }


class RemoteGameVersionTests(unittest.TestCase):
    def test_official_discovery_failure_never_claims_a_match(self):
        with patch.dict("os.environ", {}, clear=True):
            result = run_prelogin_check(
                discovery_checker=lambda: {"status": "unverified", "packages": {}})
        self.assertFalse(result["blocked"])
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["source"], "official_remote_only")
        self.assertIn("不代表已同步", result["message"])

    def test_config_sources_are_official_endpoint_urls_only(self):
        with patch.dict("os.environ", {
                "WLRE_OFFICIAL_MAIN_VERSION_URL": "https://example.invalid/a",
                "WLRE_OFFICIAL_DATA_VERSION_URL": "https://example.invalid/b",
                "WLRE_GAME_YOO_ROOT": "C:/local-game"}, clear=True):
            self.assertEqual(configured_sources(), {
                "MainPackage": "https://example.invalid/a",
                "DataPackage": "https://example.invalid/b",
            })

    def test_default_uses_remote_discovery_not_environment(self):
        calls = []
        def discover():
            calls.append("three_stage")
            return response("1275", "1275", state="resources_changed")
        with patch.dict("os.environ", {"WLRE_GAME_YOO_ROOT": "/absent"}, clear=True):
            result = run_prelogin_check(discovery_checker=discover)
        self.assertEqual(calls, ["three_stage"])
        self.assertTrue(result["blocked"])

    def test_remote_1262_equal_not_assume_protocol_match(self):
        got = run_prelogin_check({}, checker=lambda _: response())
        self.assertFalse(got["blocked"])
        self.assertEqual(got["status"], "version_identifiers_match")
        self.assertEqual(got["remote"]["protocol_compatibility"], "unverified")

    def test_remote_1275_blocks_without_local_game_folder(self):
        got = run_prelogin_check({}, checker=lambda _: response("1275", "1262",
                                                            state="resources_changed"))
        self.assertTrue(got["blocked"])
        self.assertEqual(got["status"], "blocked")
        self.assertIn("等待 LaLa 更新", got["message"])

    def test_partial_official_change_blocks_if_other_endpoint_unavailable(self):
        got = run_prelogin_check({}, checker=lambda _: {
            "status": "unverified",
            "packages": {
                "MainPackage": {"remote": "1275", "comparison": "newer"},
                "DataPackage": {"remote": None, "comparison": "unverified"},
            },
        })
        self.assertTrue(got["blocked"])

    def test_partial_result_with_no_confirmed_change_is_unknown(self):
        got = run_prelogin_check({}, checker=lambda _: {
            "status": "unverified",
            "packages": {
                "MainPackage": {"remote": "1262", "comparison": "same"},
                "DataPackage": {"remote": None, "comparison": "unverified"},
            },
        })
        self.assertEqual(got["status"], "unverified")

    def test_local_data_never_affects_version_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "Game_Data" / "yoo" / "MainPackage" / "ManifestFiles"
            root.mkdir(parents=True)
            (root / "MainPackage_1275_2026_10_21_18_29_38_49.bytes").touch()
            with patch.dict("os.environ", {"WLRE_GAME_YOO_ROOT": folder}, clear=True):
                got = run_prelogin_check(
                    discovery_checker=lambda: {"status": "unverified", "packages": {}})
            self.assertEqual(got["status"], "unverified")
            self.assertNotIn("local", got)
            self.assertFalse(got["blocked"])

    def test_app_connect_never_reads_account_or_network_before_gate(self):
        from wlre.ui.gui import App
        fake = SimpleNamespace(assert_ui_thread=Mock(),
                               can_login_after_version_check=Mock(return_value=False))
        with patch("wlre.ui.gui.run_client") as client:
            self.assertIsNone(App.connect(fake))
        fake.can_login_after_version_check.assert_called_once_with()
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
