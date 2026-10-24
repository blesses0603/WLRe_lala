"""Classification tests must not ship any actual game assets."""

import unittest
from tools.check_public_resources import prohibited_reason


class PublicResourceGuardTests(unittest.TestCase):
    def test_blocks_archives_and_raw_bundle_files(self):
        for path in ('wlre/resources/item_icons.zip', 'docs/button-assets/game-buttons.zip',
                     'DataPackage/BundleFiles/00/abc/__data',
                     'MainPackage/ManifestFiles/MainPackage_1275.bytes',
                     '1275_差異/bundles/list.json',
                     'uploads/Unity/Example_Data/Resources/unity default resources',
                     'wlre/resources/npc_talk_1262.json.gz'):
            with self.subTest(path=path):
                self.assertIsNotNone(prohibited_reason(path))

    def test_blocks_official_derived_index_and_image(self):
        for path in ('wlre/resources/item_icon_map.json',
                     'wlre/resources/portals.json',
                     'wlre/resources/assets/buttons/Btn_Bag.png',
                     'docs/button-assets/button-preview-1.png'):
            with self.subTest(path=path):
                self.assertIsNotNone(prohibited_reason(path))

    def test_allows_program_code_configuration_and_docs(self):
        for path in ('wlre/services/world/navigation.py',
                     'tools/lala_manifest_full_index.py',
                     'wlre/resources/lala_supported_resources.json',
                     'README.md',
                     'docs/button-assets/README.md'):
            with self.subTest(path=path):
                self.assertIsNone(prohibited_reason(path))

    def test_blocks_large_generated_data_even_with_generic_name(self):
        self.assertIsNotNone(prohibited_reason('docs/report.html', 2 * 1024 * 1024))
        self.assertIsNone(prohibited_reason('docs/report.html', 1024))


if __name__ == '__main__':
    unittest.main()
