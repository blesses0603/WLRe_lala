"""Conditional Bangkok screen calibration; never infer scale from the stopping point."""
import math
from itertools import product


def target_bounds(click_x, click_y, origin_x, origin_y, scale):
    """Closed intervals; origin is FULL texture top-left, scale is screen px/texel.

    Requires independently measured axis-aligned, uniformly scaled calibration.
    A visible clip rectangle is not a valid substitute for the full origin.
    The returned rectangle bounds input uncertainty, not physics or path snapping.
    """
    intervals=(click_x, click_y, origin_x, origin_y, scale)
    for pair in intervals:
        if len(pair)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in pair):
            raise ValueError('Finite interval required')
        if pair[0]>pair[1]:raise ValueError('Reversed interval')
    if scale[0]<=0:raise ValueError('Positive calibrated scale required')
    values=[(6*((x-l)/s-12),6*((y-t)/s-12))
            for x,y,l,t,s in product(*intervals)]
    return tuple((min(p[i] for p in values),max(p[i] for p in values)) for i in (0,1))


def sensitivity():
    """Illustrations ONLY: these scales and full-image origins are not measured."""
    return [dict(assumed_scale=s,assumed_full_origin=[675,182],
                 nominal=target_bounds((759,759),(410,410),(675,675),(182,182),(s,s)),
                 click_only=target_bounds((757,761),(408,412),(675,675),(182,182),(s,s)),
                 packet_units_per_screen_pixel=6/s,
                 measured_calibration=False,can_send_packets=False)
            for s in (.25,.275,.3)]


def review(snapshot, images):
    import hashlib
    import json
    from pathlib import Path
    from tools.review_navigation_corner_following import CATALOG, OBSERVATIONS, distance_to_polyline, follow
    from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
    from wlre.services.world.navigation import NavigationError
    from wlre.services.world.navigation_preview import PreviewRepository
    from wlre.services.world.smallmap_database import ImageCatalog
    snapshot=Path(snapshot)
    v=json.loads((snapshot/'current-identity.json').read_text())
    identity=OfficialCatalogIdentity(v['data_ver'],v['exe_version'],tuple(PackageRevision(**p) for p in v['packages']))
    if identity.key!=CATALOG:raise ValueError('Unreviewed catalog')
    png=ImageCatalog(Path(images),identity.key,frozenset([12600])).png(12600)
    sha=hashlib.sha256(png).hexdigest()
    if sha!='8451d7a98f5dcda8e3f8b0b9fd4565b698f2f0d1ec39ddabf8d7f9650e88c5c0':
        raise ValueError('Unreviewed Bangkok image')
    repo=PreviewRepository(identity,json.loads((snapshot/'current-stages.json').read_text()))
    rows=sensitivity()
    for row in rows:
        target=[b[0] for b in row['nominal']]
        try:
            route=repo.route(12600,(4836,5154),target,download=False,travel_mode='land',smooth=True)
        except NavigationError as error:
            row['preview_rejection']=str(error)
            continue
        row['conditional_path']=route['packet_points_xy_float']
        row['motion_cases']=[]
        for fps in (30,60,120):
            trace,_=follow(row['conditional_path'],fps,40)
            row['motion_cases'].append(dict(fps=fps,stop=trace[-1],
                stop_distance=math.dist(trace[-1],(1850,4915)),
                max_corner_distance=max(distance_to_polyline((x,y),trace) for _,x,y in OBSERVATIONS)))
    return dict(catalog_key=identity.key,png_sha256=sha,conditional_cases=rows,
                target_recovered=False,actual_frame_available=False,can_send_packets=False,
                limitations=['Click/origin supplied as text by frame reviewer, not independently registered.',
                             'Scales are illustrative, not measurements or confidence bounds.',
                             'Visible crop origin may differ from full image origin.',
                             'Motion is a Python model without actual collision or frame timing.'])


if __name__=='__main__':
    import argparse
    import json
    from pathlib import Path
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('snapshot','images','output'):p.add_argument('--'+arg,required=True,type=Path)
    a=p.parse_args();result=review(a.snapshot,a.images)
    a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
