"""Offline registration of an external Bangkok click frame to verified map artwork.

Requires optional research-only numpy/OpenCV; no video or player data is bundled.
Pixel positions use continuous image-edge coordinates. No endpoint-based fitting.
"""
import argparse
import hashlib
import json
from pathlib import Path


def register(frame, artwork):
    import cv2
    import numpy as np
    if frame.shape[:2]!=(572,962) or artwork.shape[:2]!=(1024,1024):
        raise ValueError('Unreviewed frame or artwork dimensions')
    # Exclude title/borders and most overlay controls; descriptor ratio and RANSAC
    # reject remaining NPC/route/cursor overlays. Match static texture only.
    small=cv2.resize(artwork,(280,280))
    crop=frame[182:440,675:944]
    sift=cv2.SIFT_create(contrastThreshold=.02)
    ka,da=sift.detectAndCompute(cv2.cvtColor(small,cv2.COLOR_BGR2GRAY),None)
    kb,db=sift.detectAndCompute(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),None)
    if da is None or db is None:raise ValueError('Missing static features')
    pairs=cv2.BFMatcher().knnMatch(da,db,k=2)
    points={}
    for pair in pairs:
        if len(pair)!=2:continue
        m,n=pair
        if m.distance>=.7*n.distance:continue
        # Correct resize pixel-center convention; convert both images to edges.
        source=(np.array(ka[m.queryIdx].pt)+.5)*1024/280
        target=np.array(kb[m.trainIdx].pt)+[675.5,182.5]
        points[tuple(np.round(source,2))]=(source,target)
    if len(points)<30:raise ValueError('Too few independent features')
    source=np.array([p[0] for p in points.values()]);target=np.array([p[1] for p in points.values()])
    # Spatial checkerboard holdout BEFORE estimating the transform.
    train=(np.floor(source[:,0]/128)+np.floor(source[:,1]/128)).astype(int)%2==0
    if min(sum(train),sum(~train))<10:raise ValueError('Insufficient spatial coverage')
    cv2.setRNGSeed(65)
    matrix,mask=cv2.estimateAffinePartial2D(source[train],target[train],method=cv2.RANSAC,
        ransacReprojThreshold=1,maxIters=10000,confidence=.999)
    if matrix is None:raise ValueError('Calibration failed')
    residual=np.linalg.norm(source@matrix[:,:2].T+matrix[:,2]-target,axis=1)
    accepted=(residual<=1.5)&(~train)
    if sum(accepted)<20:raise ValueError('Held-out calibration insufficient')
    # Full affine comparison detects significant anisotropy/shear rather than
    # silently forcing every frame into the similarity model.
    affine,_=cv2.estimateAffine2D(source[train],target[train],method=cv2.RANSAC,ransacReprojThreshold=1)
    singular=np.linalg.svd(affine[:,:2],compute_uv=False)
    if singular.max()/singular.min()>1.01:raise ValueError('Nonuniform scale requires separate review')
    inverse=np.linalg.inv(matrix[:,:2])
    # +/-2 click pixels supplied by frame reviewer, plus an explicit 1.5 px
    # registration allowance. This is a sensitivity envelope, not confidence.
    clicks=np.array([[x,y] for x in (755.5,762.5) for y in (406.5,413.5)])
    mapped=(clicks-matrix[:,2])@inverse.T*6-72
    nominal=(np.array([759.,410.])-matrix[:,2])@inverse.T*6-72
    rows=[dict(texture=s.tolist(),screen=t.tolist(),held_out=bool(not tr),residual=float(e))
          for s,t,tr,e in zip(source,target,train,residual)]
    return dict(matrix=matrix.tolist(),affine_singular_values=singular.tolist(),
        matches=len(points),training=int(sum(train)),training_ransac_inliers=int(mask.sum()),
        holdout_total=int(sum(~train)),holdout_within_1_5=int(sum(accepted)),
        holdout_median=float(np.median(residual[~train])),
        holdout_accepted_max=float(max(residual[accepted])),
        nominal_target=nominal.tolist(),target_envelope=[mapped.min(axis=0).tolist(),mapped.max(axis=0).tolist()],
        click=[759,410],click_uncertainty=2,registration_allowance=1.5,
        correspondences=rows,can_send_packets=False,
        limitations=['Envelope uses explicit allowances, not a statistical confidence interval.',
        'UI event hotspot/timing, floor correction and runtime path remain unobserved.',
        'Static features calibrate the image; endpoint is never a calibration input.'])


def compare_targets(registration, snapshot):
    import math
    from tools.review_navigation_corner_following import CATALOG, OBSERVATIONS, follow, distance_to_polyline
    from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
    from wlre.services.world.navigation_preview import PreviewRepository
    from wlre.services.world.navigation import NavigationError
    snapshot=Path(snapshot);v=json.loads((snapshot/'current-identity.json').read_text())
    identity=OfficialCatalogIdentity(v['data_ver'],v['exe_version'],tuple(PackageRevision(**p) for p in v['packages']))
    if identity.key!=CATALOG:raise ValueError('Unreviewed catalog')
    repo=PreviewRepository(identity,json.loads((snapshot/'current-stages.json').read_text()))
    low,high=registration['target_envelope'];center=registration['nominal_target']
    rows=[]
    for x in (low[0],center[0],high[0]):
        for y in (low[1],center[1],high[1]):
            row=dict(target=[x,y],nominal=(x==center[0] and y==center[1]));rows.append(row)
            try:route=repo.route(12600,(4836,5154),(x,y),download=False,travel_mode='land',smooth=True)
            except NavigationError as error:
                row['rejection']=str(error);continue
            row['path']=route['packet_points_xy_float'];row['models']=[]
            for fps in (30,60,120):
                trace,_=follow(row['path'],fps,40)
                row['models'].append(dict(fps=fps,stopping_position=trace[-1],
                    distance_to_observed_stop=math.dist(trace[-1],(1850,4915)),
                    max_corner_distance=max(distance_to_polyline((a,b),trace) for _,a,b in OBSERVATIONS)))
    return dict(catalog=CATALOG,sampled_targets=rows,can_send_packets=False,
                scope='Nine fixed rectangle samples, not exhaustive interval proof or a best-fit search; Python identity-collision model.')


def main():
    import cv2
    p=argparse.ArgumentParser(description=__doc__)
    for x in ('frame','artwork','output'):p.add_argument('--'+x,required=True,type=Path)
    p.add_argument('--snapshot',type=Path)
    a=p.parse_args()
    if hashlib.sha256(a.artwork.read_bytes()).hexdigest()!='8451d7a98f5dcda8e3f8b0b9fd4565b698f2f0d1ec39ddabf8d7f9650e88c5c0':
        raise ValueError('Unreviewed artwork')
    r=register(cv2.imread(str(a.frame)),cv2.imread(str(a.artwork)))
    if a.snapshot:r['comparison']=compare_targets(r,a.snapshot)
    r['frame_sha256']=hashlib.sha256(a.frame.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k not in ('correspondences','comparison')}))


if __name__=='__main__':main()
