import math
from pathlib import Path
import tempfile
import unittest
from tools.review_house_colliders import transform_matrix,multiply,box_corners,IDENTITY,inspect_bundle


def transform(position=(0,0,0),rotation=(0,0,0,1),scale=(1,1,1)):
    return dict(m_LocalPosition=dict(zip('xyz',position)),m_LocalRotation=dict(zip('xyzw',rotation)),m_LocalScale=dict(zip('xyz',scale)))


class ColliderTests(unittest.TestCase):
    def test_rotated_scaled_box_and_parent_translation(self):
        q=math.sqrt(.5)
        local=transform_matrix(transform((1,2,3),(0,q,0,q),(2,3,4)))
        parent=transform_matrix(transform((10,0,0)))
        corners=box_corners(multiply(parent,local),dict(x=0,y=0,z=0),dict(x=2,y=2,z=2))
        for axis,bounds in enumerate(((7,15),(-1,5),(1,5))):
            self.assertAlmostEqual(min(p[axis] for p in corners),bounds[0])
            self.assertAlmostEqual(max(p[axis] for p in corners),bounds[1])

    def test_unknown_transform_or_dimensions_rejected(self):
        for tree in (transform(scale=(0,1,1)),transform(rotation=(0,0,0,2)),transform(position=(float('nan'),0,0))):
            with self.assertRaises(ValueError):transform_matrix(tree)
        with self.assertRaises(ValueError):box_corners(IDENTITY,dict(x=0,y=0,z=0),dict(x=-1,y=1,z=1))

    def test_unreviewed_bundle_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'unknown.bundle';p.write_bytes(b'not a Unity bundle')
            with self.assertRaisesRegex(ValueError,'fingerprint'):inspect_bundle(p)


if __name__=='__main__':unittest.main()
