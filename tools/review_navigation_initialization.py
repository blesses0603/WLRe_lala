"""Compose bounded native initialization probes, with explicit modf modeling.

This stops short of GetNearest and never produces movement authority.
"""
import argparse
import json
from tools.review_navigation_bbtree import oracle as tree_oracle,validate_tree
from tools.review_navigation_groups import multiple_vectors
from tools.review_navigation_vertices import vectors as vertex_vectors


def vectors(path):
    vertices=vertex_vectors(path,modeled_center=True)
    rects=[row['official_output']['bounds'] for row in vertices['cases']]
    centers=[row['official_output']['center'] for row in vertices['cases']]
    tree=tree_oracle(path)(rects,centers)
    validate_tree(tree,rects)
    groups=multiple_vectors(path)
    return dict(vertices_and_modeled_centers=vertices,native_tree=tree,
                grouped_areas=groups,can_send_packets=False,
                scope='Two composed synthetic chains: vertex/center(with modf model)/BBTree, and grouping/Area. No combined live graph, GetNearest or vectorPath.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libil2cpp',required=True)
    args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
