"""1275 DailyTaskData_C 安全解析回歸測試，不倚賴遊戲原始資料。"""
import struct
import unittest

from wlre.services.world.daily_task_1275 import parse_daily_tasks


def sample_daily():
    group = struct.pack("<BBB", 1, 1, 1)
    row = struct.pack("<HBBIBHHHBBB", 1, 1, 1, 38681, 1, 1, 0, 0, 0, 0, 0)
    awards = struct.pack("<BII", 12, 1, 10) + struct.pack("<BII", 0, 0, 0)
    return struct.pack("<i", 1) + group + struct.pack("<i", 1) + row + awards


class DailyTask1275Tests(unittest.TestCase):
    def test_valid_official_layout(self):
        data = parse_daily_tasks(sample_daily())
        self.assertEqual((data["group_count"], data["task_count"]), (1, 1))
        self.assertEqual(data["tasks"][0]["awards"][0], {"kind": 12, "id": 1, "value": 10})
        self.assertEqual(data["missing_group_ids"], [])

    def test_corrupt_or_trailing_bytes_rejected(self):
        source = sample_daily()
        for bad in (source[:-1], source + b"\\0", source[:5]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                parse_daily_tasks(bad)

    def test_duplicate_group_rejected(self):
        src = sample_daily()
        bad = struct.pack("<i", 2) + struct.pack("<BBB", 1, 1, 1) * 2 + src[7:]
        with self.assertRaises(ValueError):
            parse_daily_tasks(bad)

    def test_invalid_refresh_rejected(self):
        src = bytearray(sample_daily())
        src[5] = 7
        with self.assertRaises(ValueError):
            parse_daily_tasks(bytes(src))


if __name__ == "__main__":
    unittest.main()
