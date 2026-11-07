"""Single bounded UI preview job; results expire with scene/runtime changes."""
import copy
import json
import math
import threading
from wlre.services.world.dynamic_bundle_runtime import current_runtime
from wlre.services.world.navigation_preview import PreviewRepository


def signature(state):
    player=state.get('player',{});navigation=state.get('navigation',{})
    return json.dumps([player.get('role_id'),player.get('scene'),navigation.get('revision'),
                       navigation.get('stale'),navigation.get('house_context')],sort_keys=True)


class PreviewJob:
    def __init__(self,repository_factory=PreviewRepository,runtime_getter=current_runtime):
        self.factory=repository_factory;self.runtime_getter=runtime_getter
        self.lock=threading.Lock();self.worker=None;self.closed=False
        self.value={'status':'idle','message':'僅供預覽，不會執行角色移動。'}
        self.runtime=None;self.state_key=None

    def start(self,state,map_id,start,end,*,travel_mode='land',smooth=False,download=False):
        runtime=self.runtime_getter()
        if runtime is None:raise ValueError('請先完成官方資料同步。')
        map_id=int(map_id);start=tuple(map(float,start));end=tuple(map(float,end))
        if not 1<=map_id<=65535 or len(start)!=2 or len(end)!=2 or any(not math.isfinite(x) or not 0<=x<=65535 for x in start+end):
            raise ValueError('請輸入有效的地圖 ID 與 X／Y 座標。')
        navigation=copy.deepcopy(state.get('navigation',{}));key=signature(state)
        with self.lock:
            if self.closed:raise ValueError('預覽視窗已關閉。')
            if self.worker and self.worker.is_alive():raise ValueError('上一筆預覽仍在處理。')
            self.runtime=runtime;self.state_key=key
            self.value={'status':'working','message':'正在校驗官方導航資料…'}
            def run():
                try:
                    repository=self.factory(runtime.catalog_identity,runtime.stages)
                    result=repository.route(map_id,start,end,travel_mode=travel_mode,smooth=smooth,
                                            download=download,navigation_state=navigation)
                    if result.get('can_send_packets') is not False:raise ValueError('預覽結果缺少禁止移動標記。')
                    value={'status':'ready','message':f"路徑 {len(result['points'])} 點｜成本 {result['cost']}｜僅供預覽",'result':result}
                except Exception as error:
                    value={'status':'error','message':str(error)[:300] or type(error).__name__}
                with self.lock:
                    if not self.closed:self.value=value
            self.worker=threading.Thread(target=run,name='navigation-preview',daemon=True);self.worker.start()

    def poll(self,state):
        with self.lock:
            if self.closed:return {'status':'closed','message':'預覽已關閉。'}
            if self.runtime is not None and (self.runtime_getter() is not self.runtime or signature(state)!=self.state_key):
                return {'status':'stale','message':'場景、障礙或官方版本已變更，請重新預覽。'}
            return copy.deepcopy(self.value)

    def close(self):
        with self.lock:self.closed=True
