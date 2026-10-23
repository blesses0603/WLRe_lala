"""1275 Eve read-only source and ZIP safety tests; no external game files in CI."""
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from wlre.services.world.npc_1275_eve import FILES, verify_file, read_verified_zip


class Eve1275Tests(unittest.TestCase):
    def test_invalid_bytes_rejected(self):
        for name in FILES:
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_file(name, b'not-an-Eve-index')

    def test_unknown_version_rejected(self):
        with self.assertRaises(ValueError):
            verify_file('npc_event_index_1262.json.gz', b'')

    def test_unexpected_zip_entry_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'unexpected.zip'
            with ZipFile(path,'w') as z:
                z.writestr('README.txt','test')
                z.writestr('../../unexpected','not allowed')
            with self.assertRaises(ValueError):
                read_verified_zip(path)


if __name__=='__main__': unittest.main()
