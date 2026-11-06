"""Four pinned far-query diagnostics with a separate 400,000-step hard cap.

The default nearest probe still uses 200,000. No product or path-pipeline limit
changes, no native-code substitution, and no movement authority.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
from tools.review_navigation_nearest import oracle
from tools.review_navigation_rotation import IL2CPP_SHA

MODELS=(13221,13223,13225,13226)


def review(libil2cpp,cache_dir):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_PC
    from wlre.services.world.astar_cache import review_cache,MAX_BYTES
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    rows=[]
    for model in MODELS:
        with (Path(cache_dir)/f'M{model}-astar-cache.zip').open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=REVIEWED_MODELS[model]:raise ValueError('Unverified graph')
        record=review_cache(raw);tile=record['mesh']['tiles'][0];vertices=tile['vertices_a_int3'];faces=tile['triangles']
        if not 1<=len(faces)<=256:raise ValueError('Diagnostic graph bound')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:settings=json.loads(z.read('graph0.json'))
        if settings['nearestSearchOnlyXZ']:raise ValueError('Unsupported XZ-only profile')
        state={};call=oracle(libil2cpp,_state=state,_outer_instruction_limit=400000);u=state['vm'];counts={};active=[False]
        def count(machine,address,size,user):
            if address==0x1a7a794:active[0]=True;counts.clear()
            if active[0]:counts[address]=counts.get(address,0)+1
        hook=u.hook_add(UC_HOOK_CODE,count)
        point=[0,max(v[1] for v in vertices)/1000+101,0]
        try:
            output=call(vertices,faces,point,origin=[v/1000 for v in record['origin']],outer=True,
                        full_search=False,max_distance=100,node_flags=[f for p,f in tile['node_metadata']],tag_mask=9,
                        cell_size=settings['cellSize'],tile_cells=(settings['tileSizeX'],settings['tileSizeZ']))
            if output['node'] is not None:raise ValueError('Far query unexpectedly selected node')
            status='completed_native_rejection'
        except ValueError as error:
            if str(error)!='Instruction budget':raise
            output=None;status='unverified_instruction_budget'
        finally:u.hook_del(hook)
        rows.append(dict(model=model,sha256=hashlib.sha256(raw).hexdigest(),triangles=len(faces),point=point,
                         minimum_vertical_distance=101,maximum_nearest_distance=100,status=status,output=output,
                         native_query_instructions=sum(counts.values()),vertex_calls=counts.get(0x27a12ec,0),
                         final_pc=hex(u.reg_read(UC_ARM64_REG_PC))))
    return dict(il2cpp_sha256=IL2CPP_SHA,cases=rows,diagnostic_instruction_cap=400000,default_cap_unchanged=200000,
                all_completed=all(r['status']=='completed_native_rejection' for r in rows),
                can_send_packets=False,runtime_settings_verified=False,scope=__doc__)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--libil2cpp',required=True);p.add_argument('--cache-dir',required=True);a=p.parse_args()
    print(json.dumps(review(a.libil2cpp,a.cache_dir),sort_keys=True))


if __name__=='__main__':main()
