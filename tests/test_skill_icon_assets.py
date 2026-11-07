import hashlib
import sqlite3
import shutil
import tempfile
from pathlib import Path
from contextlib import closing
import unittest
from unittest.mock import patch
from wlre.ui import skill_icons as icons
from wlre.services.world import combat_catalog as catalog


class OfficialSkillIcons(unittest.TestCase):
    def test_all_exported_assets_have_exact_provenance_and_pixels(self):
        manifest=icons._manifest()
        self.assertEqual(len(manifest),306)
        with closing(icons._database()) as db:
            self.assertEqual({row[0] for row in db.execute('SELECT name FROM images')},set(manifest))
            self.assertEqual(dict(db.execute('SELECT key,value FROM metadata'))['mapping_lua_sha256'],
                             '962e95717ddce2c8d56da622df0e578afbf7bd6c63a19e53a809fb4a283f3228')
            for name,entry in manifest.items():
                self.assertEqual(entry['source_asset'],'Assets/ResourcesBuild/Sprite/Sprite_Skill/'+name+'.png')
                raw=db.execute('SELECT png FROM images WHERE name=?',(name,)).fetchone()[0]
                self.assertEqual(len(raw),entry['bytes'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
                self.assertEqual(icons.skill_icon_image({'GId':int(name[7:-1])},48).size,(48,48))

    def test_corrupt_or_missing_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            shutil.copy2(icons.ASSET_ROOT/'skill-icons.sqlite3',root/'skill-icons.sqlite3')
            with closing(sqlite3.connect(root/'skill-icons.sqlite3')) as db:
                db.execute("UPDATE images SET png=zeroblob(length(png)) WHERE name='icon_sk10001s'")
                db.commit()
            icons._pixels.cache_clear();icons._manifest.cache_clear()
            try:
                with patch.object(icons,'ASSET_ROOT',root):
                    self.assertIsNone(icons.skill_icon_image({'GId':10001}))
                with patch.object(icons,'ASSET_ROOT',root/'missing'):
                    self.assertIsNone(icons.skill_icon_image({'GId':10001}))
            finally:
                icons._pixels.cache_clear();icons._manifest.cache_clear()

    def test_mapping_uses_gid_not_skill_id(self):
        self.assertEqual(icons.icon_name({'ID':77,'GId':10001}),'icon_sk10001s')
        self.assertIsNotNone(icons.skill_icon_image({'ID':77,'GId':10001}))
        for row in ({'ID':10001},{'GId':0},{'GId':True},{'GId':'10001'},{'GId':65536},{'GId':65535}):
            self.assertIsNone(icons.skill_icon_image(row))
        for size in (0,257,True):
            with self.assertRaises(ValueError):icons.skill_icon_image({'GId':10001},size)

    def test_returned_image_is_not_shared_mutable_cache(self):
        first=icons.skill_icon_image({'GId':10001})
        second=icons.skill_icon_image({'GId':10001})
        self.assertIsNot(first,second)
        self.assertEqual(first.tobytes(),second.tobytes())

    def test_description_is_resolved_from_official_text_reference(self):
        item=b'items'; npc=b'\0\0\0\0'
        rows={'7':{'Name':100,'Desc':101,'Key':0},'8':{'Name':100,'Desc':0,'Key':0}}
        with patch.object(catalog,'ITEMDATA_1296_SHA256',hashlib.sha256(item).hexdigest()), \
             patch.object(catalog,'validate_npcs'),patch.object(catalog,'parse_itemdata',return_value={}), \
             patch.object(catalog,'parse_skills',return_value=rows),patch.object(catalog,'parse_constants',return_value=([],{})):
            result=catalog.build_catalog(b'',npc,item,{100:'技能',101:'官方說明'},{'Define.lua':'','FightUnit.lua':''})
        self.assertEqual(result['skills']['7']['description'],'官方說明')
        self.assertEqual(result['skills']['8']['description'],'')


if __name__=='__main__':unittest.main()
