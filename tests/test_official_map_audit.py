import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from PIL import Image
from tools.audit_official_maps import audit, map_assets


class OfficialMapAudit(unittest.TestCase):
    def index(self):
        return {'assets': [{'path': f'Assets/ResourcesBuild/Texture/SmallMap2D/SmallMap2D_{i}.png',
                            'bundle_name': 'maps.bundle'} for i in (1, 2)],
                'bundles': [{'name': 'maps.bundle', 'file_hash': 'a'*32},
                            {'name': 'mainpackage_scene_3.bundle'}]}

    def test_id_coverage_is_separate_from_pixel_comparison_and_official_absence(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'local.zip'
            image = Image.new('RGBA', (1024,1024), (1,2,3,255))
            buffer = io.BytesIO();image.save(buffer,format='PNG')
            with ZipFile(path,'w') as z:
                z.writestr('image_index.json',json.dumps([{'name':'SmallMap2D_1'}]))
                z.writestr('SmallMap2D_1.png',buffer.getvalue())
            result = audit(self.index(),path)
            self.assertEqual(result['missing_ids'],[2])
            self.assertEqual(result['official_models_without_minimap_asset'],[3])
            self.assertFalse(result['pixel_comparison_complete'])
            self.assertFalse(result['current_online_version_observed'])
            self.assertIsNone(result['maps'][0]['pixel_changed'])
            changed = audit(self.index(),path,lambda model,asset: Image.new('RGBA',(1024,1024),'red'))
            self.assertTrue(changed['maps'][0]['pixel_changed'])
            same = audit(self.index(),path,lambda model,asset: image)
            self.assertFalse(same['maps'][0]['pixel_changed'])
            self.assertFalse(same['can_send_packets'])

    def test_duplicate_or_non_exact_assets_are_not_inferred(self):
        value = self.index()
        value['assets'].append(value['assets'][0])
        with self.assertRaises(ValueError): map_assets(value)
        value['assets'] = [{'path':'other/SmallMap2D_1.png','bundle_name':'maps.bundle'}]
        with self.assertRaises(ValueError): map_assets(value)
