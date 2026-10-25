"""Official server is the only authority for version-gate decisions."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.game_version_gate import configured_sources, run_prelogin_check
from wlre.services.official_version import RESOURCE_MAP_URL


def response(main="1275", data="1275", *, state="same_resources",
             newer_exe=False):
    return {
        "status": state,
        "newer_official_client": newer_exe,
        "resource_path": "1.3.21",
        "packages": {
            "MainPackage": {"remote": main,
                            "comparison": "same" if main.startswith("1275") else "newer"},
            "DataPackage": {"remote": data,
                            "comparison": "same" if data.startswith("1275") else "newer"},
        },
        "protocol_compatibility": "unverified",
    }


class RemoteGameVersionTests(unittest.TestCase):
    def test_source_is_official_dynamic_resource_map(self):
        self.assertEqual(configured_sources(), {"ResourcePath_PC.dat": RESOURCE_MAP_URL})

    def test_game_baseline_1275_remote_same(self):
        with patch("wlre.services.game_version_gate.check_official_game_resources",
                   return_value=response()) as check, patch(
                       "wlre.services.world.runtime_1275.ready",
                       return_value=(True, "1275 test fixture verified")):
            got = run_prelogin_check()
        check.assert_called_once_with()
        self.assertEqual(got["status"], "version_identifiers_match")
        self.assertFalse(got["blocked"])
        self.assertEqual(got["source"], "official_remote_only")
        self.assertEqual(got["baseline"], {"MainPackage": "1275", "DataPackage": "1275"})

    def test_future_1276_blocks(self):
        with patch("wlre.services.game_version_gate.check_official_game_resources",
                   return_value=response("1276_2026_10_22_18_29_38_49",
                                         "1276_2026_10_22_18_27_33_84",
                                         state="resources_changed")):
            got = run_prelogin_check()
        self.assertTrue(got["blocked"])
        self.assertIn("等待 LaLa 更新", got["message"])

    def test_partial_official_change_blocks_if_other_endpoint_unavailable(self):
        got = run_prelogin_check({}, checker=lambda _: {
            "status": "unverified", "packages": {
                "MainPackage": {"remote": "1275", "comparison": "newer"},
                "DataPackage": {"remote": None, "comparison": "unverified"}}})
        self.assertTrue(got["blocked"])

    def test_partial_result_with_no_confirmed_change_is_unknown(self):
        got = run_prelogin_check({}, checker=lambda _: {
            "status": "unverified", "packages": {
                "MainPackage": {"remote": "1262", "comparison": "same"},
                "DataPackage": {"remote": None, "comparison": "unverified"}}})
        self.assertEqual(got["status"], "unverified")
        self.assertIn("不代表已同步", got["message"])

    def test_new_official_executable_is_distinct_compatibility_signal(self):
        got = run_prelogin_check({}, checker=lambda _: response(newer_exe=True))
        self.assertTrue(got["blocked"])
        self.assertIn("客戶端版本", got["message"])

    def test_offline_is_not_false_match_or_unjustified_change(self):
        with patch("wlre.services.game_version_gate.check_official_game_resources",
                   return_value={"status":"unverified", "packages":{},
                                 "resource_path":None}), patch(
                       "wlre.services.world.runtime_1275.ready",
                       return_value=(True, "1275 fixture verified")):
            got = run_prelogin_check()
        self.assertEqual(got["status"], "blocked")
        self.assertTrue(got["blocked"])
        self.assertIn("不能替代本次官方版本確認", got["message"])

    def test_local_1275_assets_required_even_if_network_unknown(self):
        with patch("wlre.services.game_version_gate.check_official_game_resources",
                   return_value={"status":"unverified", "packages":{},
                                 "resource_path":None}), patch(
                       "wlre.services.world.runtime_1275.ready",
                       return_value=(False, "missing 1275 archive")):
            result = run_prelogin_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["blocked"])
        self.assertIn("1275", result["message"])
        self.assertIn("1262", result["message"])

    def test_local_install_versions_do_not_affect_remote_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "Game_Data" / "yoo" / "MainPackage" / "ManifestFiles"
            manifest.mkdir(parents=True)
            (manifest / "MainPackage_1275_2026_10_21_18_29_38_49.bytes").touch()
            with patch.dict("os.environ", {"WLRE_GAME_YOO_ROOT": tmp}, clear=True):
                with patch("wlre.services.game_version_gate.check_official_game_resources",
                           return_value=response()), patch(
                               "wlre.services.world.runtime_1275.ready",
                               return_value=(True, "1275 fixture")):
                    got = run_prelogin_check()
            self.assertFalse(got["blocked"])
            self.assertNotIn("local", got)

    def test_app_connect_never_uses_account_before_gate(self):
        from wlre.ui.gui import App
        fake = SimpleNamespace(assert_ui_thread=Mock(),
                               can_login_after_version_check=Mock(return_value=False))
        with patch("wlre.ui.gui.run_client") as client:
            self.assertIsNone(App.connect(fake))
        client.assert_not_called()
        fake.can_login_after_version_check.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
