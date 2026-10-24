"""Tests covering YooAsset 2.2.5 binary layout and ID-independent diff."""

import struct
import unittest

try:
    from tools.resources.lala_manifest_full_index import ParseError, parse_manifest, diff_records, dependency_impact, validate_private_output
except ModuleNotFoundError:
    from lala_manifest_full_index import ParseError, parse_manifest, diff_records, dependency_impact, validate_private_output


def utf8(text):
    raw = text.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def str_array(items):
    return struct.pack("<H", len(items)) + b"".join(utf8(item) for item in items)


def i32_array(items):
    return struct.pack("<H", len(items)) + b"".join(struct.pack("<i", i) for i in items)


def sample_manifest(order=("a", "b"), broken=False):
    data = struct.pack("<I", 0x00594F4F) + utf8("2.2.5")
    data += struct.pack("<BBBii", 1, 0, 1, 0, 2)
    data += utf8("ScriptableBuildPipeline") + utf8("MainPackage") + utf8("1275_test") + utf8("")
    data += struct.pack("<i", 2)
    for name in ("a", "b"):
        data += utf8(name) + utf8(f"Assets/{name}") + utf8(f"guid-{name}") + str_array([])
        data += struct.pack("<i", order.index(name))
    data += struct.pack("<i", len(order))
    for name in order:
        data += utf8(name) + struct.pack("<I", 123) + utf8(f"filehash-{name}") + utf8("crc")
        data += struct.pack("<qB", 42, 0) + str_array([]) + i32_array([] if name == "a" else [order.index("a")])
    return data[:-1] if broken else data


class FullIndexTests(unittest.TestCase):
    def test_full_parse_and_asset_bundle_ids(self):
        index = parse_manifest(sample_manifest())
        self.assertEqual(index["asset_count"], 2)
        self.assertEqual(index["bundle_count"], 2)
        self.assertEqual(index["assets"][0]["bundle_name"], "a")
        self.assertEqual(index["bundles"][1]["dependencies"], ["a"])

    def test_order_change_not_a_content_change(self):
        original = parse_manifest(sample_manifest())
        reordered = parse_manifest(sample_manifest(("b", "a")))
        self.assertEqual(diff_records(original, reordered, "bundle")["modified_count"], 0)
        self.assertEqual(diff_records(original, reordered, "asset")["modified_count"], 0)

    def test_dependency_propagation(self):
        index = parse_manifest(sample_manifest())
        impact = dependency_impact(index, {"added": [], "modified": ["a"]})
        self.assertEqual(impact["changed_bundle_count"], 1)
        self.assertEqual(impact["dependency_affected_bundle_count"], 2)
        self.assertEqual(impact["direct_asset_count"], 1)
        self.assertEqual(impact["possibly_affected_asset_count"], 2)

    def test_reject_truncated_data(self):
        with self.assertRaises(ParseError):
            parse_manifest(sample_manifest(broken=True))

    def test_reject_git_worktree_output(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            with self.assertRaises(ParseError):
                validate_private_output(root / "private_indexes")


if __name__ == "__main__":
    unittest.main()
