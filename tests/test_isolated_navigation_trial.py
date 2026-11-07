import json
from pathlib import Path
import tempfile
import unittest
from tools.isolated_navigation_trial import SEED,digest,restore,prepare


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'quarantine').mkdir()
        (self.root/'source/wlre/resources').mkdir(parents=True)
        self.held=self.root/'quarantine'/SEED;self.held.write_bytes(b'synthetic quarantined bytes')
        (self.root/'isolation.json').write_text(json.dumps({'seed_sha256':digest(self.held)}))

    def test_restore_is_copy_and_never_overwrites(self):
        result=restore(self.root)
        target=Path(result['restored']);self.assertEqual(target.read_bytes(),self.held.read_bytes())
        self.assertTrue(self.held.exists())
        with self.assertRaises(FileExistsError):restore(self.root)

    def test_corrupt_quarantine_does_not_publish(self):
        self.held.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):restore(self.root)
        self.assertFalse((self.root/'source/wlre/resources'/SEED).exists())

    def test_existing_workspace_refused_before_copy(self):
        with self.assertRaisesRegex(ValueError,'new isolated'):prepare(self.root,self.root)
