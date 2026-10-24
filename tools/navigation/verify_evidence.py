"""Audit passive navigation evidence and independent world-position references.

Formula roundtrips, local requests and destination notices are never promoted
to proof of server arrival. This report cannot authorize game movement.
"""
import argparse
import json
import math
from pathlib import Path
from wlre.services.world.topology_1275 import packet_to_world_xz


class EvidenceError(ValueError):pass


def _coordinate(value):
    if type(value) not in (float,int) or not math.isfinite(value):raise EvidenceError('座標必須是有限數值')
    return value


def surface_checks(document,candidates):
    """Check formula-predicted positions, without treating them as independent references."""
    from tools.navigation.scan import to_offline_mesh,validate
    from wlre.services.world.navigation import NavigationError
    meshes={};results=[]
    for row in document['events']:
        if row.get('kind')!='position_fix':continue
        stage=document.get('stages',{}).get(str(row['scene']),{})
        model=stage.get('model_id');candidate=candidates.get(model)
        if candidate is None:continue
        if (candidate.get('kind')!='offline_recast_candidate' or candidate.get('resource_revision')!=1275
                or candidate.get('can_send_packets') is not False
                or str(candidate.get('source',{}).get('model_id'))!=str(model)):
            raise EvidenceError('候選網格來源或版本與目前地圖不符')
        if model not in meshes:
            if candidate.get('triangles'):
                validate({'coordinate_space':'unity_world_y_up','vertices':candidate['vertices'],
                          'triangles':candidate['triangles']},candidate['settings'])
            meshes[model]=to_offline_mesh(candidate)
        _coordinate(stage.get('offset_y'))
        x,z=packet_to_world_xz(stage,row['x'],row['y'])
        result={'sequence':row['sequence'],'scene':row['scene'],'model_id':model,
            'formula_predicted_world_xz':[x,z],'independent_world_reference_verified':False}
        try:
            face,point=meshes[model].locate(x*1000,z*1000)
            result.update(formula_prediction_on_candidate=True,face=face,surface_xyz_metres=[v/1000 for v in point])
        except NavigationError as exc:
            result.update(formula_prediction_on_candidate=False,reason=str(exc))
        results.append(result)
    return results


def audit(document,candidate_models=None,candidates=None):
    if (not isinstance(document,dict) or document.get('schema_version')!=1
            or document.get('resource_revision')!=1275
            or document.get('capture_type')!='lala_passive_navigation_events'):
        raise EvidenceError('需要1275被動導航驗證紀錄')
    events=document.get('events');references=document.get('reference_points',[]);stages=document.get('stages',{})
    if (not isinstance(events,list) or len(events)>256 or not isinstance(references,list)
            or len(references)>256 or not isinstance(stages,dict)):
        raise EvidenceError('驗證紀錄格式錯誤')
    fixes={};changes=[];notices=0;previous=-1;previous_revision=None
    for row in events:
        if not isinstance(row,dict) or type(row.get('sequence')) is not int or row['sequence']<=previous:
            raise EvidenceError('封包觀測次序重複或倒退')
        previous=row['sequence']
        if row.get('kind')=='position_fix':
            if row.get('source') not in ('S3-1','S7-1','S12-1'):raise EvidenceError('不是已知的伺服器定位來源')
            for name in ('x','y'):
                if not 0<=_coordinate(row[name])<=65535:raise EvidenceError('定位超出UInt16')
            fixes[row['sequence']]=row
        elif row.get('kind')=='geometry_change':
            revision=row.get('navigation_revision')
            changes.append({**row,'revision_advanced':type(revision) is int and previous_revision is not None and revision>previous_revision})
        elif row.get('kind') in ('destination_notice','local_request'):notices+=1
        if type(row.get('navigation_revision')) is int:previous_revision=row['navigation_revision']
    grouped={};used=set()
    for ref in references:
        if not isinstance(ref,dict) or ref.get('reference_source')!='independent_game_world_reference':
            raise EvidenceError('世界座標必須是獨立觀測，不能由換算公式自行產生')
        sequence=ref.get('sequence')
        if type(sequence) is not int:raise EvidenceError('參考點序號必須是整數')
        fix=fixes.get(sequence)
        if fix is None or sequence in used:raise EvidenceError('參考點必須對應不同的伺服器定位觀測')
        used.add(sequence);scene=fix['scene'];stage=stages.get(str(scene))
        if not isinstance(stage,dict):raise EvidenceError('缺少該場景的1275來源座標設定')
        _coordinate(stage.get('offset_y'))
        world=ref.get('world_xz')
        if not isinstance(world,list) or len(world)!=2:raise EvidenceError('需要兩維世界座標')
        wx,wz=map(_coordinate,world)
        x,z=packet_to_world_xz(stage,fix['x'],fix['y'])
        grouped.setdefault(scene,[]).append({'packet_xy':[fix['x'],fix['y']],
            'error_metres':math.hypot(x-wx,z-wz),'sequence':sequence})
    reports=[]
    for scene,rows in grouped.items():
        noncollinear=False
        if len(rows)>=3:
            a=rows[0]['packet_xy']
            for i in range(1,len(rows)):
                b=rows[i]['packet_xy']
                for row in rows[i+1:]:
                    c=row['packet_xy']
                    if abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))>1:noncollinear=True
        max_error=max(row['error_metres'] for row in rows)
        reports.append({'scene':scene,'references':len(rows),'noncollinear':noncollinear,
            'max_error_metres':max_error,'reference_consistency':
                'insufficient_points' if not noncollinear else 'consistent' if max_error<=.02 else 'mismatch'})
    relevant=[r for r in changes if r.get('affects_current_map')]
    observed_scenes=sorted({r['scene'] for r in fixes.values()})
    coverage=[{'scene':scene,'model_id':stages.get(str(scene),{}).get('model_id'),
        'candidate_available':None if candidate_models is None else stages.get(str(scene),{}).get('model_id') in candidate_models}
        for scene in observed_scenes]
    return {'position_fixes':len(fixes),'local_requests_and_notices':notices,
        'coordinate_reference_checks':reports,'scene_candidate_coverage':coverage,
        'candidate_surface_checks':surface_checks(document,candidates) if candidates is not None else [],
        'geometry_changes':len(relevant),
        'non_current_map_geometry_events':len(changes)-len(relevant),
        'geometry_invalidation_observed':bool(relevant) and all(r.get('stale') and r['revision_advanced'] for r in relevant),
        'geometry_rebuild_required':bool(relevant),'recording_truncated':bool(document.get('dropped')),
        'world_reference_provenance_requires_review':True,
        'dynamic_geometry_verified':False,'live_movement_verified':False,'can_send_packets':False,
        'status':'needs_scene_candidate' if any(r['candidate_available'] is False for r in coverage) else 'needs_live_evidence' if not reports else 'reference_checks_only'}


def main():
    p=argparse.ArgumentParser(description='檢查導航定位／障礙驗證資料，不送遊戲封包')
    p.add_argument('evidence',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--candidate-dir',type=Path,help='另檢查登入地圖是否有對應候選網格')
    a=p.parse_args();models=None;candidates=None
    if a.candidate_dir:
        models=set();candidates={}
        for path in a.candidate_dir.glob('*_candidate.json'):
            candidate=json.loads(path.read_text(encoding='utf8'))
            if candidate.get('kind')=='offline_recast_candidate' and candidate.get('can_send_packets') is False:
                model=int(candidate['source']['model_id']);models.add(model);candidates[model]=candidate
    result=audit(json.loads(a.evidence.read_text(encoding='utf8')),models,candidates)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:
        with a.output.open('x',encoding='utf8') as stream:stream.write(text)
    print(text)

if __name__=='__main__':main()
