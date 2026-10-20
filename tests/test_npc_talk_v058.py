"""Official 1262 TalkData_C record format and optional content safety."""
import gzip
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from wlre.services.world.npc_talk import (
    parse_talk_data, make_catalog, load_catalog, dialogue_text,
)


def sample_record(ident=411, text='你好，冒險者！', voice=17):
    data=text.encode('utf-16le')
    return (struct.pack('<HH',ident,len(data)) + data + b'\0'*5 +
            struct.pack('<H',voice) + b'\0'*8 + b'\0'*20)


class TalkDataTests(unittest.TestCase):
    def test_exact_binary_layout(self):
        raw=struct.pack('<i',1)+sample_record()
        rows=parse_talk_data(raw)
        self.assertEqual(rows[411], {'text':'你好，冒險者！','voice_id':17})
        self.assertEqual(make_catalog(raw)['source_sha256'],hashlib.sha256(raw).hexdigest())

    def test_missing_optional_text_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(load_catalog(Path(td)/'absent.gz'),{})
        self.assertIsNone(dialogue_text({},411))
        self.assertIsNone(dialogue_text({411:'hello'},True))

    def test_valid_index_round_trip(self):
        raw=struct.pack('<i',2)+sample_record()+sample_record(412,'請選擇',0)
        catalog=make_catalog(raw)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'npc_talk_1262.json.gz'
            with gzip.open(path,'wt',encoding='utf-8') as s:
                json.dump(catalog,s,ensure_ascii=False)
            rows=load_catalog(path)
        self.assertEqual(dialogue_text(rows,411),'你好，冒險者！')
        self.assertEqual(dialogue_text(rows,412),'請選擇')

    def test_truncation_duplicate_id_and_encoding_fail_closed(self):
        row=sample_record()
        cases=[
            struct.pack('<i',2)+row,
            struct.pack('<i',2)+row+row,
            struct.pack('<i',1)+row[:-1],
            struct.pack('<i',1)+row+b'\0',
            struct.pack('<i',-1),
            struct.pack('<i',1)+sample_record(text='\ud800'),
        ]
        for bad in cases[:-1]:
            with self.subTest(size=len(bad)),self.assertRaises(ValueError):
                parse_talk_data(bad)
        odd=bytearray(row)
        odd[2:4]=struct.pack('<H',3)
        with self.assertRaises(ValueError):
            parse_talk_data(struct.pack('<i',1)+bytes(odd))

    def test_malformed_catalog_is_rejected(self):
        raw=struct.pack('<i',1)+sample_record()
        catalog=make_catalog(raw)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bad.gz'
            for wrong in (
                {**catalog,'version':999},
                {**catalog,'source_sha256':'forged'},
                {**catalog,'records':{'411':{'text':'x','voice_id':True}}},
                {**catalog,'records':{'-1':{'text':'x','voice_id':0}}},
            ):
                with gzip.open(path,'wt',encoding='utf-8') as s:json.dump(wrong,s)
                with self.assertRaises(ValueError):load_catalog(path)
