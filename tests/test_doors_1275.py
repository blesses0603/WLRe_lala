"""1275 Eve door snapshot regression tests. Source pin required in all calls."""
import unittest
from wlre.services.world.doors_1275 import DoorSourceError, parse_doors_1275


class NewDoor1275Tests(unittest.TestCase):
    def test_unknown_source_rejected(self):
        with self.assertRaises(DoorSourceError):
            parse_doors_1275(b'Eve not verified')

    def test_no_cross_version_fallback(self):
        with self.assertRaises(DoorSourceError):
            parse_doors_1275(None)

    def test_wrong_hash_rejected_before_event_parsing(self):
        with self.assertRaises(DoorSourceError):
            parse_doors_1275(b'\0' * 256)


if __name__ == '__main__':
    unittest.main()
