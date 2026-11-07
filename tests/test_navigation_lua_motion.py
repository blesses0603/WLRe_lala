import tempfile
from pathlib import Path
import unittest
from tools.review_navigation_lua_motion import oracle


class LuaMotionSourceGuards(unittest.TestCase):
    def test_unreviewed_source_never_executes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.lua';p.write_text('error("must not execute")')
            with self.assertRaisesRegex(ValueError,'Unverified'):oracle(p)

    def test_oversize_source_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.lua';p.write_bytes(b' '* (128*1024+1))
            with self.assertRaisesRegex(ValueError,'size limit'):oracle(p)
