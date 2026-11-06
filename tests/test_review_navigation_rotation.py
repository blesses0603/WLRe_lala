from pathlib import Path
import tempfile
import unittest
from tools.review_navigation_rotation import from_to_oracle,multiply_oracle,validate_vector


class RotationOracleBoundaryTests(unittest.TestCase):
    def test_unknown_library_rejected_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unknown.so';path.write_bytes(b'not official code')
            for factory in (from_to_oracle,multiply_oracle):
                with self.assertRaisesRegex(ValueError,'digest'):factory(path)
            with path.open('wb') as output:output.truncate(96*1024*1024+1)
            with self.assertRaisesRegex(ValueError,'size limit'):from_to_oracle(path)

    def test_invalid_and_unbounded_inputs(self):
        for values in ((float('nan'),0,0),(float('inf'),0,0),(1000001,0,0),(1,2)):
            with self.assertRaises(ValueError):validate_vector(values,3)
        validate_vector((0,0,0),3)
