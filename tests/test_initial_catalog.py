import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from wlre.paths import RESOURCE_ROOT
from wlre.storage.initial_catalog import NAMES, build_seed, verify_seed, provision_seed


class InitialCatalogTests(unittest.TestCase):
    def test_seed_build_verify_and_provision(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = build_seed(RESOURCE_ROOT, root / 'seed.sqlite3')
            self.assertTrue(verify_seed(seed))
            user = root / 'user.sqlite3'
            provision_seed(seed, user)
            provision_seed(seed, user)
            with closing(sqlite3.connect(user)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM bundled_active').fetchone()[0], len(NAMES))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM bundled_resources').fetchone()[0], len(NAMES))

    def test_corrupt_seed_fails_closed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = build_seed(RESOURCE_ROOT, root / 'seed.sqlite3')
            with closing(sqlite3.connect(seed)) as db, db:
                db.execute('INSERT INTO bundled_active VALUES (?,?)', ('unexpected', '0'*64))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', ('unexpected', '0'*64, b'corrupt'))
            with self.assertRaises(ValueError):
                verify_seed(seed)


if __name__ == '__main__':
    unittest.main()
