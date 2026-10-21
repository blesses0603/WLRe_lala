"""Local-only official text install is safe on mismatches or missing files."""
import gzip
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from wlre.services.world.npc_asset_install import install, read_verified
from wlre.services.world.npc_localization import load_text_data, load_battle_talk, battle_lines


def compressed(obj):
    raw=io.BytesIO()
    with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as out:
        out.write(json.dumps(obj,ensure_ascii=False).encode('utf-8'))
    return raw.getvalue()


class NPCAssetTests(unittest.TestCase):
    def make_bundle(self,root):
        assets={
            'npc_talk_1262.json.gz':('TalkData_C',{'15':{'text':'歡迎','voice_id':0}}),
            'npc_text_1262.json.gz':('TextData_C',{'120000':'NPC 戰鬥提示'}),
            'npc_battle_talk_1262.json.gz':('NpcTalkData_C',{'1':[{
                'text_id':120000,'kind':1,'parameter':0,'duration':5}]})}
        expected={}
        archive=root/'test.zip'
        with ZipFile(archive,'w') as out:
            for name,(source,records) in assets.items():
                content=compressed({'version':1262,'source':source,
                   'source_sha256':'a'*64,'records':records})
                out.writestr('wlre/resources/'+name,content)
                expected[name]=(hashlib.sha256(content).hexdigest(),
                    len(content),source,'a'*64,len(records))
        return archive,expected

    def test_validate_then_install_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive,expected=self.make_bundle(root)
            target=root/'resources';target.mkdir()
            self.assertEqual(len(read_verified(archive,expected)),3)
            self.assertEqual(len(install(archive,target,check=True,expected=expected)),3)
            self.assertFalse(list(target.iterdir()))
            self.assertEqual(len(install(archive,target,expected=expected)),3)
            with self.assertRaises(FileExistsError):
                install(archive,target,expected=expected)
            text=load_text_data(target/'npc_text_1262.json.gz')
            battle=load_battle_talk(target/'npc_battle_talk_1262.json.gz')
            self.assertEqual(battle_lines(1,battle,text),[(120000,'NPC 戰鬥提示')])
            self.assertEqual(battle_lines(2,battle,text),[])

    def test_checksum_corruption_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive,expected=self.make_bundle(root)
            target=root/'resources';target.mkdir()
            bad=dict(expected)
            sha,size,source,orig,n=bad['npc_talk_1262.json.gz']
            bad['npc_talk_1262.json.gz']=('0'*64,size,source,orig,n)
            with self.assertRaises(ValueError):
                install(archive,target,expected=bad)
            self.assertFalse(list(target.iterdir()))

    def test_missing_record_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive,expected=self.make_bundle(root)
            expected=dict(expected)
            sha,size,source,orig,n=expected['npc_text_1262.json.gz']
            expected['npc_text_1262.json.gz']=(sha,size,source,orig,n+1)
            with self.assertRaises(ValueError):
                read_verified(archive,expected)
