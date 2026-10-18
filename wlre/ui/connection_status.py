"""Keep transport status independent of the last character snapshot."""
import time
from wlre.network.connection_health import QUIET_AFTER

REASONS = {'server_closed':'伺服器已關閉連線','network_error':'網路錯誤，連線已結束',
           'client_error':'連線處理異常，已結束','stopped':'已手動中斷','duration':'連線作業已結束'}


class ConnectionStatus:
    def __init__(self, clock=time.monotonic):
        self.clock=clock; self.reset()
    def reset(self): self.value=None; self.received=None
    def update(self, value): self.value=dict(value); self.received=self.clock()
    def text(self, running=False):
        value=self.value
        if not value: return '連線建立／驗證中' if running else '尚未連線'
        if value['status']=='closed':
            result=REASONS.get(value.get('reason'),'連線已結束')
            if value.get('errno') is not None: result+=f"（代碼 {value['errno']}）"
            return result
        if not running: return '連線作業已停止，等待結束原因'
        age=max(0,value['age']+self.clock()-self.received)
        stamp=value.get('last_received_at')
        last=time.strftime('%H:%M:%S',time.localtime(stamp)) if stamp is not None else '尚無回應'
        title=('連線待確認' if age>=QUIET_AFTER else '伺服器有回應' if stamp is not None else '等待伺服器回應')
        return f'{title}｜最後 {last}（{int(age)} 秒前）' if stamp is not None else f'{title}｜尚未收到資料 {int(age)} 秒'
